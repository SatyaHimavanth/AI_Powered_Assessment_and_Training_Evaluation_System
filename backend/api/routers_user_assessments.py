import json
import re
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import List
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.llms import get_chat_model
from core.auth import get_current_user
from db.database import SessionLocal
from db.models import (
    Answer,
    Assessment,
    AssessmentQuestion,
    AssessmentQuestionSection,
    Assignment,
    Attempt,
    AttemptStatus,
    BatchUser,
    Batch,
    BatchStatus,
    EvaluationJob,
    EvaluationJobStatus,
    EvaluationType,
    Question,
    QuestionOption,
    QuestionType,
    TestCase,
    Topic,
    TopicScore,
    User,
    AssessmentQuestionItem,
)
from db.async_helpers import run_db_sync
from db.database import SessionLocal

router = APIRouter(prefix="/user/assessments", tags=["user-assessments"])


def _as_utc_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_utc_iso(dt: datetime | None) -> str | None:
    aware = _as_utc_aware(dt)
    if aware is None:
        return None
    return aware.isoformat().replace("+00:00", "Z")


def _attempt_sort_key(attempt: Attempt) -> tuple[datetime, datetime, int, str]:
    min_dt = datetime.min.replace(tzinfo=timezone.utc)
    status_rank = {
        AttemptStatus.completed: 3,
        AttemptStatus.in_progress: 2,
        AttemptStatus.missed: 1,
    }.get(attempt.status, 0)
    return (
        _as_utc_aware(attempt.started_at) or min_dt,
        _as_utc_aware(attempt.submitted_at) or min_dt,
        status_rank,
        str(attempt.id),
    )


def _latest_attempt_for_user_assessment(
    db: Session,
    user_id: UUID,
    assessment_id: UUID,
) -> Attempt | None:
    attempts = (
        db.query(Attempt)
        .filter(Attempt.assessment_id == assessment_id, Attempt.user_id == user_id)
        .all()
    )
    return max(attempts, key=_attempt_sort_key) if attempts else None


def _completed_attempt_for_user_assessment(
    db: Session,
    user_id: UUID,
    assessment_id: UUID,
) -> Attempt | None:
    completed_attempts = (
        db.query(Attempt)
        .filter(
            Attempt.assessment_id == assessment_id,
            Attempt.user_id == user_id,
            Attempt.status == AttemptStatus.completed,
        )
        .all()
    )
    return max(completed_attempts, key=_attempt_sort_key) if completed_attempts else None


# ---------- Schemas ---------- #


class OptionOut(BaseModel):
    id: UUID
    text: str


class TestCaseSampleOut(BaseModel):
    id: UUID
    input_data: str
    expected_output: str


class QuestionOut(BaseModel):
    id: UUID
    type: str
    question: str
    difficulty: str
    section_name: str
    options: List[OptionOut]
    test_cases: List[TestCaseSampleOut] = []
    default_code: str | None = None


class UserAssessmentItem(BaseModel):
    id: UUID
    title: str
    description: str | None
    duration: int
    total_questions: int
    start_time: str | None
    end_time: str | None
    status: str  # "pending" | "evaluating" | "completed" | "incomplete" | "missed"
    attempt_id: str | None


class SavedAnswerOut(BaseModel):
    question_id: UUID
    answer: str


class StartAttemptResponse(BaseModel):
    attempt_id: UUID
    assessment_title: str
    duration: int
    total_questions: int
    questions: List[QuestionOut]
    saved_answers: List[SavedAnswerOut] = []
    time_elapsed_seconds: int = 0
    tab_violations: int = 0


class SubmitAnswerRequest(BaseModel):
    question_id: UUID
    answer: str


class SubmitAssessmentRequest(BaseModel):
    answers: List[SubmitAnswerRequest]


class SubmitResponse(BaseModel):
    message: str
    status: str


def _is_attempt_fully_evaluated(db: Session, attempt: Attempt) -> bool:
    if attempt.score is None:
        return False
    pending_answers = (
        db.query(Answer)
        .filter(Answer.attempt_id == attempt.id, Answer.score.is_(None))
        .count()
    )
    return pending_answers == 0


# ---------- User Batches ---------- #


class UserBatchOut(BaseModel):
    id: UUID
    name: str
    description: str | None
    status: str
    user_count: int


@router.get("/batches", response_model=List[UserBatchOut])
async def get_my_batches(
    user: User = Depends(get_current_user),
):
    """Get batches the current user is a member of."""

    def _sync_work():
        db = SessionLocal()
        try:
            links = db.query(BatchUser).filter(BatchUser.user_id == user.id).all()
            batch_ids = [l.batch_id for l in links]
            if not batch_ids:
                return []

            batches = db.query(Batch).filter(Batch.id.in_(batch_ids)).order_by(Batch.name).all()
            result: List[UserBatchOut] = []
            for b in batches:
                count = db.query(BatchUser).filter(BatchUser.batch_id == b.id).count()
                result.append(UserBatchOut(
                    id=b.id,
                    name=b.name,
                    description=b.description,
                    status=b.status.value if b.status else "current",
                    user_count=count,
                ))
            return result
        finally:
            db.close()

    return await run_db_sync(_sync_work)


# ---------- Endpoints ---------- #


@router.get("/", response_model=List[UserAssessmentItem])
async def get_my_assessments(
    user: User = Depends(get_current_user),
):
    """Get all assessments assigned to the current user via their batches."""
    
    def _sync_work():
        db = SessionLocal()
        try:
            # Get user's batch IDs (include archived batches so users keep access to assigned assessments)
            batch_links = db.query(BatchUser).filter(BatchUser.user_id == user.id).all()
            batch_ids = [bl.batch_id for bl in batch_links]

            if not batch_ids:
                return []

            # Get assignments for those batches
            assignments = (
                db.query(Assignment)
                .filter(Assignment.batch_id.in_(batch_ids))
                .all()
            )

            assessment_ids = list(set(a.assessment_id for a in assignments))
            if not assessment_ids:
                return []

            assessments = (
                db.query(Assessment)
                .filter(Assessment.id.in_(assessment_ids))
                .all()
            )

            result = []
            now = datetime.now(timezone.utc)

            for a in assessments:
                # Check if user already attempted. There can be historical missed
                # attempts; use the latest so an older missed row does not hide a
                # submitted attempt on the dashboard.
                attempt = (
                    _completed_attempt_for_user_assessment(db, user.id, a.id)
                    or _latest_attempt_for_user_assessment(db, user.id, a.id)
                )

                # Skip archived assessments for users who haven't attempted them
                if not attempt and getattr(a, "is_archived", False):
                    continue

                total_q = (
                    db.query(AssessmentQuestion)
                    .filter(AssessmentQuestion.assessment_id == a.id)
                    .count()
                )

                # Determine status
                if attempt:
                    if attempt.status == AttemptStatus.completed and not _is_attempt_fully_evaluated(db, attempt):
                        status = "evaluating"
                    elif attempt.status == AttemptStatus.completed:
                        status = "completed"
                    elif attempt.status == AttemptStatus.in_progress:
                        status = "incomplete"
                    else:
                        status = "missed"
                elif a.end_time and now > a.end_time:
                    status = "missed"
                else:
                    status = "pending"

                result.append(UserAssessmentItem(
                    id=a.id,
                    title=a.title,
                    description=a.description,
                    duration=a.duration,
                    total_questions=total_q,
                    start_time=_to_utc_iso(a.start_time),
                    end_time=_to_utc_iso(a.end_time),
                    status=status,
                    attempt_id=str(attempt.id) if attempt else None,
                ))

            return result
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.post("/start/{assessment_id}", response_model=StartAttemptResponse)
async def start_assessment(
    assessment_id: UUID,
    user: User = Depends(get_current_user),
):
    """Start an assessment attempt. Fails if already attempted or outside time window."""
    

    def _sync_work():
        db = SessionLocal()
        try:
            assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
            if not assessment:
                raise HTTPException(status_code=404, detail="Assessment not found")

            # Serialize start requests from the same user. This prevents rapid
            # double-clicks or concurrent requests from both seeing "no attempt"
            # and creating duplicate in-progress attempts.
            db.query(User).filter(User.id == user.id).with_for_update().first()

            # Check user is assigned to this assessment
            batch_links = db.query(BatchUser).filter(BatchUser.user_id == user.id).all()
            batch_ids = [bl.batch_id for bl in batch_links]
            assigned = (
                db.query(Assignment)
                .filter(
                    Assignment.assessment_id == assessment_id,
                    Assignment.batch_id.in_(batch_ids),
                )
                .first()
            )
            if not assigned:
                raise HTTPException(status_code=403, detail="You are not assigned to this assessment")

            # Check if already attempted. Prefer any completed attempt first so
            # a stale missed/in-progress row cannot allow or block incorrectly.
            existing = _completed_attempt_for_user_assessment(db, user.id, assessment_id)
            if not existing:
                existing = _latest_attempt_for_user_assessment(db, user.id, assessment_id)
            # Prevent starting a newly archived assessment for users without an existing attempt
            if getattr(assessment, "is_archived", False) and not existing:
                raise HTTPException(status_code=403, detail="Assessment is archived and cannot be started")
            if existing:
                # Allow resumption if in_progress and within duration window
                if existing.status == AttemptStatus.in_progress:
                    now_naive = datetime.now(timezone.utc)
                    time_elapsed = (now_naive - existing.started_at) if existing.started_at else timedelta.max
                    if time_elapsed < timedelta(minutes=assessment.duration):
                        # Return existing attempt data for resumption
                        aq_links = (
                            db.query(AssessmentQuestion)
                            .filter(AssessmentQuestion.assessment_id == assessment_id)
                            .order_by(AssessmentQuestion.id.asc())
                            .all()
                        )
                        section_links = (
                            db.query(AssessmentQuestionSection)
                            .filter(AssessmentQuestionSection.assessment_id == assessment_id)
                            .all()
                        )
                        section_map: dict[str, str] = {}
                        for link in section_links:
                            if getattr(link, "assessment_item_id", None):
                                section_map[str(link.assessment_item_id)] = (link.section_name or "General")
                            else:
                                section_map[str(link.question_id)] = (link.section_name or "General")

                        questions_out = []
                        for aq in aq_links:
                            # Per-assessment item
                            if getattr(aq, "assessment_item_id", None):
                                item = db.query(AssessmentQuestionItem).filter(AssessmentQuestionItem.id == aq.assessment_item_id).first()
                                if not item:
                                    continue
                                opts = []
                                if item.options:
                                    for o in item.options:
                                        opts.append(OptionOut(id=o.get("id"), text=o.get("option_text")))
                                sample_tcs = []
                                # test_cases for per-assessment items may be stored in item.test_cases
                                if item.test_cases:
                                    for tc in (item.test_cases or [])[:2]:
                                        sample_tcs.append(TestCaseSampleOut(id=tc.get("id") or None, input_data=tc.get("input", ""), expected_output=tc.get("expected_output", "")))
                                questions_out.append(QuestionOut(
                                    id=item.id,
                                    type=(item.question_type or "text"),
                                    question=item.question_text,
                                    difficulty=(item.difficulty or "medium"),
                                    section_name=section_map.get(str(item.id), "General"),
                                    options=opts,
                                    test_cases=sample_tcs,
                                    default_code=item.default_code,
                                ))
                            else:
                                q = db.query(Question).filter(Question.id == aq.question_id).first()
                                if not q:
                                    continue
                                options = db.query(QuestionOption).filter(QuestionOption.question_id == q.id).all()
                                # Include sample test cases for coding questions
                                sample_tcs = []
                                if q.type == QuestionType.coding:
                                    tcs = db.query(TestCase).filter(TestCase.question_id == q.id, TestCase.is_sample == True).limit(2).all()
                                    sample_tcs = [TestCaseSampleOut(id=tc.id, input_data=tc.input_data, expected_output=tc.expected_output) for tc in tcs]
                                questions_out.append(QuestionOut(
                                    id=q.id,
                                    type=q.type.value,
                                    question=q.question,
                                    difficulty=q.difficulty.value,
                                    section_name=section_map.get(str(q.id), "General"),
                                    options=[OptionOut(id=o.id, text=o.option_text) for o in options],
                                    test_cases=sample_tcs,
                                    default_code=q.default_code,
                                ))

                        # Fetch saved answers for this attempt (may reference question_id or assessment_item_id)
                        saved = db.query(Answer).filter(Answer.attempt_id == existing.id).all()
                        saved_answers_out = [SavedAnswerOut(question_id=(a.assessment_item_id or a.question_id), answer=a.answer or "") for a in saved]

                        # Calculate time already elapsed
                        elapsed = int((now_naive - existing.started_at).total_seconds()) if existing.started_at else 0

                        return StartAttemptResponse(
                            attempt_id=existing.id,
                            assessment_title=assessment.title,
                            duration=assessment.duration,
                            total_questions=len(questions_out),
                            questions=questions_out,
                            saved_answers=saved_answers_out,
                            time_elapsed_seconds=elapsed,
                            tab_violations=existing.tab_violations or 0,
                        )
                    else:
                        # Attempt expired (>30 minutes), mark as missed and create new one
                        existing.status = AttemptStatus.missed
                        db.commit()
                else:
                    # Already completed or marked as missed
                    raise HTTPException(status_code=400, detail="You have already attempted this assessment")
    
            # Create new attempt
            now = datetime.now(timezone.utc)
            if assessment.start_time and now < assessment.start_time:
                raise HTTPException(status_code=400, detail="Assessment has not started yet")
            if assessment.end_time and now > assessment.end_time:
                raise HTTPException(status_code=400, detail="Assessment time window has ended")

            # Create attempt
            attempt = Attempt(
                user_id=user.id,
                assessment_id=assessment_id,
                started_at=now,
                status=AttemptStatus.in_progress,
            )
            db.add(attempt)
            db.commit()
            db.refresh(attempt)

            # Get questions for this assessment in insertion order.
            # This preserves section-wise sequence as selected during assessment creation.
            aq_links = (
                db.query(AssessmentQuestion)
                .filter(AssessmentQuestion.assessment_id == assessment_id)
                .order_by(AssessmentQuestion.id.asc())
                .all()
            )

            section_links = (
                db.query(AssessmentQuestionSection)
                .filter(AssessmentQuestionSection.assessment_id == assessment_id)
                .all()
            )
            section_map: dict[str, str] = {}
            for link in section_links:
                if getattr(link, "assessment_item_id", None):
                    section_map[str(link.assessment_item_id)] = (link.section_name or "General")
                else:
                    section_map[str(link.question_id)] = (link.section_name or "General")

            questions_out = []
            for aq in aq_links:
                if getattr(aq, "assessment_item_id", None):
                    item = db.query(AssessmentQuestionItem).filter(AssessmentQuestionItem.id == aq.assessment_item_id).first()
                    if not item:
                        continue
                    opts = []
                    if item.options:
                        for o in item.options:
                            opts.append(OptionOut(id=o.get("id"), text=o.get("option_text")))
                    sample_tcs = []
                    if item.test_cases:
                        for tc in (item.test_cases or [])[:2]:
                            sample_tcs.append(TestCaseSampleOut(id=tc.get("id") or None, input_data=tc.get("input", ""), expected_output=tc.get("expected_output", "")))
                    questions_out.append(QuestionOut(
                        id=item.id,
                        type=(item.question_type or "text"),
                        question=item.question_text,
                        difficulty=(item.difficulty or "medium"),
                        section_name=section_map.get(str(item.id), "General"),
                        options=opts,
                        test_cases=sample_tcs,
                        default_code=item.default_code,
                    ))
                else:
                    q = db.query(Question).filter(Question.id == aq.question_id).first()
                    if not q:
                        continue
                    options = db.query(QuestionOption).filter(QuestionOption.question_id == q.id).all()
                    # Include sample test cases for coding questions (max 2 to prevent hardcoding)
                    sample_tcs = []
                    if q.type == QuestionType.coding:
                        tcs = db.query(TestCase).filter(TestCase.question_id == q.id, TestCase.is_sample == True).limit(2).all()
                        sample_tcs = [TestCaseSampleOut(id=tc.id, input_data=tc.input_data, expected_output=tc.expected_output) for tc in tcs]
                    questions_out.append(QuestionOut(
                        id=q.id,
                        type=q.type.value,
                        question=q.question,
                        difficulty=q.difficulty.value,
                        section_name=section_map.get(str(q.id), "General"),
                        options=[OptionOut(id=o.id, text=o.option_text) for o in options],
                        test_cases=sample_tcs,
                        default_code=q.default_code,
                    ))

            return StartAttemptResponse(
                attempt_id=attempt.id,
                assessment_title=assessment.title,
                duration=assessment.duration,
                total_questions=len(questions_out),
                questions=questions_out,
            )
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.post("/save-answer")
async def save_answer(
    body: SubmitAnswerRequest,
    attempt_id: UUID,
    user: User = Depends(get_current_user),
):
    """Save a single answer during the exam (auto-save). Upserts the answer record."""
    

    def _sync_work():
        db = SessionLocal()
        try:
            attempt = db.query(Attempt).filter(Attempt.id == attempt_id, Attempt.user_id == user.id).first()
            if not attempt:
                raise HTTPException(status_code=404, detail="Attempt not found")

            if attempt.status != AttemptStatus.in_progress:
                raise HTTPException(status_code=400, detail="Attempt is not in progress")

            # Upsert: update if exists, create if not
            # Determine whether this question id is a per-assessment item or a global Question
            item = db.query(AssessmentQuestionItem).filter(AssessmentQuestionItem.id == body.question_id).first()
            if item:
                existing = (
                    db.query(Answer)
                    .filter(Answer.attempt_id == attempt_id, Answer.assessment_item_id == body.question_id)
                    .first()
                )
                if existing:
                    existing.answer = body.answer
                else:
                    new_answer = Answer(
                        attempt_id=attempt_id,
                        assessment_item_id=body.question_id,
                        answer=body.answer,
                    )
                    db.add(new_answer)
            else:
                existing = (
                    db.query(Answer)
                    .filter(Answer.attempt_id == attempt_id, Answer.question_id == body.question_id)
                    .first()
                )
                if existing:
                    existing.answer = body.answer
                else:
                    new_answer = Answer(
                        attempt_id=attempt_id,
                        question_id=body.question_id,
                        answer=body.answer,
                    )
                    db.add(new_answer)

            db.commit()
            return {"status": "saved"}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.post("/save-violations")
async def save_violations(
    attempt_id: UUID,
    violations: int,
    user: User = Depends(get_current_user),
):
    """Persist the current violation count for an in-progress attempt."""
    

    def _sync_work():
        db = SessionLocal()
        try:
            attempt = db.query(Attempt).filter(Attempt.id == attempt_id, Attempt.user_id == user.id).first()
            if not attempt:
                raise HTTPException(status_code=404, detail="Attempt not found")
            if attempt.status != AttemptStatus.in_progress:
                raise HTTPException(status_code=400, detail="Attempt is not in progress")

            attempt.tab_violations = violations
            db.commit()
            return {"status": "saved", "violations": violations}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.post("/submit/{attempt_id}", response_model=SubmitResponse)
async def submit_assessment(
    attempt_id: UUID,
    body: SubmitAssessmentRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    """Submit answers for an assessment attempt."""
    

    def _sync_work():
        db = SessionLocal()
        try:
            attempt = db.query(Attempt).filter(Attempt.id == attempt_id, Attempt.user_id == user.id).first()
            if not attempt:
                raise HTTPException(status_code=404, detail="Attempt not found")

            if attempt.status != AttemptStatus.in_progress:
                raise HTTPException(status_code=400, detail="This attempt is already finalized")

            # Save answers (upsert - some may already exist from auto-save)
            for ans in body.answers:
                # detect per-assessment item
                item = db.query(AssessmentQuestionItem).filter(AssessmentQuestionItem.id == ans.question_id).first()
                if item:
                    existing_ans = (
                        db.query(Answer)
                        .filter(Answer.attempt_id == attempt_id, Answer.assessment_item_id == ans.question_id)
                        .first()
                    )
                    if existing_ans:
                        existing_ans.answer = ans.answer
                    else:
                        answer = Answer(
                            attempt_id=attempt_id,
                            assessment_item_id=ans.question_id,
                            answer=ans.answer,
                        )
                        db.add(answer)
                else:
                    existing_ans = (
                        db.query(Answer)
                        .filter(Answer.attempt_id == attempt_id, Answer.question_id == ans.question_id)
                        .first()
                    )
                    if existing_ans:
                        existing_ans.answer = ans.answer
                    else:
                        answer = Answer(
                            attempt_id=attempt_id,
                            question_id=ans.question_id,
                            answer=ans.answer,
                        )
                        db.add(answer)

            attempt.submitted_at = datetime.now(timezone.utc)
            attempt.status = AttemptStatus.completed
            db.commit()
            
            # Create evaluation job instead of direct background task
            eval_job = EvaluationJob(
                attempt_id=attempt.id,
                status=EvaluationJobStatus.pending,
            )
            db.add(eval_job)
            db.commit()

            return {"message": "Assessment submitted successfully. Evaluation started.", "status": "evaluating"}
        finally:
            db.close()

    result = await run_db_sync(_sync_work)
    return SubmitResponse(**result)


@router.post("/abort/{attempt_id}", response_model=SubmitResponse)
async def abort_assessment(
    attempt_id: UUID,
    body: SubmitAssessmentRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    """Abort an assessment (tab violation limit exceeded). Saves partial answers."""
    

    def _sync_work():
        db = SessionLocal()
        try:
            attempt = db.query(Attempt).filter(Attempt.id == attempt_id, Attempt.user_id == user.id).first()
            if not attempt:
                raise HTTPException(status_code=404, detail="Attempt not found")

            if attempt.status != AttemptStatus.in_progress:
                raise HTTPException(status_code=400, detail="This attempt is already finalized")

            # Save partial answers (upsert - some may exist from auto-save)
            for ans in body.answers:
                if ans.answer.strip():
                    item = db.query(AssessmentQuestionItem).filter(AssessmentQuestionItem.id == ans.question_id).first()
                    if item:
                        existing_ans = (
                            db.query(Answer)
                            .filter(Answer.attempt_id == attempt_id, Answer.assessment_item_id == ans.question_id)
                            .first()
                        )
                        if existing_ans:
                            existing_ans.answer = ans.answer
                        else:
                            answer = Answer(
                                attempt_id=attempt_id,
                                assessment_item_id=ans.question_id,
                                answer=ans.answer,
                            )
                            db.add(answer)
                    else:
                        existing_ans = (
                            db.query(Answer)
                            .filter(Answer.attempt_id == attempt_id, Answer.question_id == ans.question_id)
                            .first()
                        )
                        if existing_ans:
                            existing_ans.answer = ans.answer
                        else:
                            answer = Answer(
                                attempt_id=attempt_id,
                                question_id=ans.question_id,
                                answer=ans.answer,
                            )
                            db.add(answer)

            attempt.submitted_at = datetime.now(timezone.utc)
            attempt.status = AttemptStatus.missed  # marked incomplete
            db.commit()
            
            # Create evaluation job instead of direct background task
            eval_job = EvaluationJob(
                attempt_id=attempt.id,
                status=EvaluationJobStatus.pending,
            )
            db.add(eval_job)
            db.commit()

            return {"message": "Assessment aborted due to violations", "status": "incomplete"}
        finally:
            db.close()

    result = await run_db_sync(_sync_work)
    return SubmitResponse(**result)


# ---------- User Results ---------- #


class AnswerReviewItem(BaseModel):
    question_id: UUID
    question_text: str
    question_type: str
    topic_name: str
    your_answer: str
    correct_answer: str
    is_correct: bool
    score: float | None
    suggestion: str | None


class TopicScoreItem(BaseModel):
    topic_name: str
    total: int
    correct: float
    percentage: float


class UserResultsOut(BaseModel):
    assessment_title: str
    status: str
    score: float | None
    evaluation_pending: bool
    total_questions: int
    answered: int
    correct_count: int
    started_at: str | None
    submitted_at: str | None
    topic_scores: List[TopicScoreItem]
    answers: List[AnswerReviewItem]


@router.get("/{assessment_id}/results", response_model=UserResultsOut)
async def get_my_results(
    assessment_id: UUID,
    user: User = Depends(get_current_user),
):
    

    def _sync_work():
        db = SessionLocal()
        try:
            attempt = (
                _completed_attempt_for_user_assessment(db, user.id, assessment_id)
                or _latest_attempt_for_user_assessment(db, user.id, assessment_id)
            )
            if not attempt:
                raise HTTPException(status_code=404, detail="No attempt found for this assessment")

            try:
                from .results_helpers import build_attempt_results
            except Exception:
                raise HTTPException(status_code=500, detail="Failed to load results helper")

            try:
                return build_attempt_results(db, attempt)
            except ValueError as e:
                raise HTTPException(status_code=404, detail=str(e))
        finally:
            db.close()

    return await run_db_sync(_sync_work)


def _safe_filename_part(value: str) -> str:
    sanitized = re.sub(r'[^A-Za-z0-9._-]+', '_', value.strip())
    return sanitized.strip('_') or 'value'


@router.get("/{assessment_id}/export")
async def export_my_results(
    assessment_id: UUID,
    user: User = Depends(get_current_user),
):
    """Export completed assessment results as Excel."""
    

    def _sync_work():
        db = SessionLocal()
        try:
            attempt = (
                _completed_attempt_for_user_assessment(db, user.id, assessment_id)
                or _latest_attempt_for_user_assessment(db, user.id, assessment_id)
            )
            if not attempt:
                raise HTTPException(status_code=404, detail="No attempt found for this assessment")
            if attempt.status != AttemptStatus.completed:
                raise HTTPException(status_code=400, detail="Results export is only available for completed assessments")

            assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
            if not assessment:
                raise HTTPException(status_code=404, detail="Assessment not found")

            try:
                from .results_helpers import build_attempt_results
            except Exception:
                raise HTTPException(status_code=500, detail="Failed to load results helper")

            try:
                results = build_attempt_results(db, attempt)
            except ValueError as e:
                raise HTTPException(status_code=404, detail=str(e))

            return {"results": results, "assessment_title": assessment.title, "attempt_started_at": attempt.started_at.isoformat() if attempt.started_at else None}
        finally:
            db.close()

    payload = await run_db_sync(_sync_work)
    results = payload.get("results", {})
    assessment_title = payload.get("assessment_title")
    started_iso = payload.get("attempt_started_at")

    workbook = Workbook()
    summary_sheet = workbook.active
    summary_sheet.title = "Summary"
    summary_sheet.append(["Username", user.username])
    summary_sheet.append(["Name", user.name])
    summary_sheet.append(["Assessment", assessment_title])
    summary_sheet.append(["Started At", results.get("started_at") or ""])
    summary_sheet.append(["Submitted At", results.get("submitted_at") or ""])
    summary_sheet.append(["Status", results.get("status")])
    summary_sheet.append(["Score", results.get("score") if results.get("score") is not None else "Pending"])
    summary_sheet.append(["Answered", f"{results.get('answered')}/{results.get('total_questions')}"])
    summary_sheet.append([])
    summary_sheet.append(["Topic", "Earned", "Total", "Percentage"])
    for topic_score in results.get("topic_scores", []):
        summary_sheet.append([
            topic_score.get("topic_name"),
            topic_score.get("correct"),
            topic_score.get("total"),
            topic_score.get("percentage"),
        ])

    detail_sheet = workbook.create_sheet("Question Review")
    detail_sheet.append([
        "Question No",
        "Topic",
        "Type",
        "Question",
        "Your Answer",
        "Correct Answer",
        "Score",
        "Suggestion",
    ])
    for index, answer in enumerate(results.get("answers", []), start=1):
        detail_sheet.append([
            index,
            answer.get("topic_name"),
            answer.get("question_type"),
            answer.get("question_text"),
            answer.get("your_answer"),
            answer.get("correct_answer"),
            answer.get("score") if answer.get("score") is not None else "Pending",
            answer.get("suggestion") or "",
        ])

    buffer = BytesIO()
    workbook.save(buffer)
    buffer.seek(0)

    # Parse start time for filename; fallback to now
    if started_iso:
        try:
            started_dt = datetime.fromisoformat(started_iso.replace("Z", "+00:00"))
        except Exception:
            started_dt = datetime.now(timezone.utc)
    else:
        started_dt = datetime.now(timezone.utc)

    filename = (
        f"{_safe_filename_part(user.username)}_"
        f"{_safe_filename_part(assessment_title)}_"
        f"{started_dt.strftime('%Y%m%d_%H%M%S')}.xlsx"
    )

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------- User Performance Report ---------- #


class UserTopicPerformance(BaseModel):
    topic_name: str
    average_percentage: float
    assessment_count: int


class UserPerformanceReport(BaseModel):
    user_name: str
    username: str
    email: str
    total_assessments: int
    completed_assessments: int
    average_score: float | None
    topic_performance: List[UserTopicPerformance]
    improvement_areas: List[str]


@router.get("/me/performance", response_model=UserPerformanceReport)
async def get_my_performance(
    user: User = Depends(get_current_user),
):
    """Get current user's performance report across all assessments."""
    
    from db.models import AttemptStatus

    def _sync_work():
        db = SessionLocal()
        try:
            # Get all attempts for this user
            attempts = db.query(Attempt).filter(Attempt.user_id == user.id).all()
            total_assessments = len(attempts)
            completed_assessments = len([a for a in attempts if a.status == AttemptStatus.completed])

            # Calculate average score
            completed_scores = [a.score for a in attempts if a.score is not None]
            average_score = round(sum(completed_scores) / len(completed_scores), 1) if completed_scores else None

            # Calculate topic-wise performance across all attempts
            topic_stats: dict[str, dict] = {}
            for attempt in attempts:
                answers = db.query(Answer).filter(Answer.attempt_id == attempt.id).all()
                per_attempt_topic_scores: dict[str, list[float]] = {}

                for answer in answers:
                    q = None
                    item = None
                    if getattr(answer, "question_id", None):
                        q = db.query(Question).filter(Question.id == answer.question_id).first()
                    elif getattr(answer, "assessment_item_id", None):
                        item = db.query(AssessmentQuestionItem).filter(AssessmentQuestionItem.id == answer.assessment_item_id).first()
                    if not q and not item:
                        continue

                    topic_name = q.topic.name if q and q.topic else (item.topic or "General")

                    # only include evaluated answers in per-attempt averages
                    if answer.score is None:
                        continue

                    per_attempt_topic_scores.setdefault(topic_name, []).append(float(answer.score or 0.0))

                # Aggregate per-topic stats for this attempt
                for topic_name, scores in per_attempt_topic_scores.items():
                    if not scores:
                        continue
                    attempt_pct = (sum(scores) / len(scores)) * 100
                    if topic_name not in topic_stats:
                        topic_stats[topic_name] = {"scores": [], "attempts": 0}
                    topic_stats[topic_name]["scores"].append(attempt_pct)
                    topic_stats[topic_name]["attempts"] += 1

            # Build topic performance list
            topic_performance: List[dict] = []
            for topic_name, stats in topic_stats.items():
                if stats["scores"]:
                    avg_pct = round(sum(stats["scores"]) / len(stats["scores"]), 1)
                    topic_performance.append({"topic_name": topic_name, "average_percentage": avg_pct, "assessment_count": stats["attempts"]})

            # Generate improvement suggestions based on topic performance
            improvement_areas: List[str] = []
            low_topics = [tp for tp in topic_performance if tp["average_percentage"] < 50]
            if low_topics:
                for lt in sorted(low_topics, key=lambda x: x["average_percentage"])[:3]:
                    improvement_areas.append(f"Focus on {lt['topic_name']} (Current: {lt['average_percentage']}%)")

            if not improvement_areas and topic_performance:
                for tp in sorted(topic_performance, key=lambda x: x["average_percentage"])[:2]:
                    improvement_areas.append(f"Strengthen {tp['topic_name']} (Current: {tp['average_percentage']}%)")

            return {
                "user_name": user.name,
                "username": user.username,
                "email": user.email,
                "total_assessments": total_assessments,
                "completed_assessments": completed_assessments,
                "average_score": average_score,
                "topic_performance": topic_performance,
                "improvement_areas": improvement_areas,
            }
        finally:
            db.close()

    payload = await run_db_sync(_sync_work)
    return UserPerformanceReport(**payload)
