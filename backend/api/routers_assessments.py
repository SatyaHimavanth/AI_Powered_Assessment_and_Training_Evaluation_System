from datetime import datetime, timezone
from io import BytesIO
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
import re

from core.auth import require_admin
from db.database import SessionLocal
from db.async_helpers import run_db_sync
from db.models import (
    Answer,
    Assessment,
    AssessmentQuestion,
    AssessmentQuestionSection,
    AssessmentTopic,
    Assignment,
    Attempt,
    AttemptStatus,
    Batch,
    BatchUser,
    Difficulty,
    EvaluationJob,
    Question,
    AssessmentQuestionItem,
    QuestionType,
    TopicScore,
    Topic,
    User,
)

router = APIRouter(prefix="/assessments", tags=["assessments"])


def _parse_to_utc_naive(value: str) -> datetime:
    """Parse ISO string to a UTC-aware datetime."""
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"

    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        # Treat naive datetime as UTC.
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_utc_iso(dt: datetime | None) -> str | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


# ---------- Schemas ---------- #


class TopicConfig(BaseModel):
    topic_id: UUID
    question_type: str
    difficulty: str
    question_count: int
    section_name: str = "General"


class CreateAssessmentRequest(BaseModel):
    title: str
    description: str = ""
    duration: int = 60  # minutes
    negative_marking: bool = False
    topics: List[TopicConfig]
    batch_ids: List[UUID] = []
    start_time: str | None = None
    end_time: str | None = None


class AssessmentTopicOut(BaseModel):
    topic_name: str
    question_type: str
    difficulty: str
    question_count: int
    selected_count: int
    section_name: str = "General"


class AssessmentOut(BaseModel):
    id: UUID
    title: str
    description: str | None
    duration: int
    negative_marking: bool = False
    is_archived: bool = False
    total_questions: int
    topics: List[AssessmentTopicOut]
    batch_names: List[str] = []
    start_time: str | None = None
    end_time: str | None = None
    created_at: str

    class Config:
        from_attributes = True


class AssessmentListItem(BaseModel):
    id: UUID
    title: str
    description: str | None
    duration: int
    negative_marking: bool = False
    is_archived: bool = False
    total_questions: int
    batch_names: List[str] = []
    start_time: str | None = None
    end_time: str | None = None
    created_at: str

    class Config:
        from_attributes = True


class AssessmentListResponse(BaseModel):
    items: List[AssessmentListItem]
    total: int
    page: int
    limit: int


class AvailableCountRequest(BaseModel):
    topic_id: UUID
    question_type: str
    difficulty: str


class AvailableCountResponse(BaseModel):
    available: int


# ---------- Endpoints ---------- #


@router.post("/available-count", response_model=AvailableCountResponse)
async def get_available_count(
    body: AvailableCountRequest,
    _admin: User = Depends(require_admin),
):
    """Get available question count for a topic/type/difficulty combination. Offloads DB count to threadpool."""
    try:
        q_type = QuestionType(body.question_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid question type: {body.question_type}")
    try:
        diff = Difficulty(body.difficulty)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid difficulty: {body.difficulty}")

    # uses module-level `run_db_sync` and `SessionLocal`

    def _sync_work():
        db = SessionLocal()
        try:
            return (
                db.query(Question)
                .filter(
                    Question.topic_id == body.topic_id,
                    Question.type == q_type,
                    Question.difficulty == diff,
                    Question.is_archived == False,
                )
                .count()
            )
        finally:
            db.close()

    count = await run_db_sync(_sync_work)
    return AvailableCountResponse(available=count)


@router.post("/create", response_model=AssessmentOut)
async def create_assessment(
    body: CreateAssessmentRequest,
    _admin: User = Depends(require_admin),
):
    """Create an assessment by selecting random questions matching topic configs.

    Offloads the DB-heavy selection/creation work to a threadpool via `run_db_sync`.
    """
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="Assessment title is required")
    if not body.topics:
        raise HTTPException(status_code=400, detail="At least one topic configuration is required")

    # Parse start/end times (light, non-DB work)
    start_dt = None
    end_dt = None
    if body.start_time:
        try:
            start_dt = _parse_to_utc_naive(body.start_time)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_time format (use ISO format)")
    if body.end_time:
        try:
            end_dt = _parse_to_utc_naive(body.end_time)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_time format (use ISO format)")
    if start_dt and end_dt and end_dt <= start_dt:
        raise HTTPException(status_code=400, detail="end_time must be after start_time")

    # uses module-level `run_db_sync` and `SessionLocal`

    def _sync_work():
        db = SessionLocal()
        try:
            # Validate batch_ids exist and collect names
            batch_names: List[str] = []
            if body.batch_ids:
                for bid in body.batch_ids:
                    batch = db.query(Batch).filter(Batch.id == bid).first()
                    if not batch:
                        raise HTTPException(status_code=400, detail=f"Batch {bid} not found")
                    batch_names.append(batch.name)

            # Create assessment record
            assessment = Assessment(
                title=body.title.strip(),
                description=body.description.strip() or None,
                duration=body.duration,
                negative_marking=body.negative_marking,
                start_time=start_dt,
                end_time=end_dt,
                created_by=_admin.id,
            )
            db.add(assessment)
            db.flush()

            topic_results: List[AssessmentTopicOut] = []
            total_questions = 0

            # Validate configs and aggregate requested
            grouped_requested: dict[tuple[UUID, QuestionType, Difficulty], int] = {}
            validated_configs = []
            for tc in body.topics:
                topic = db.query(Topic).filter(Topic.id == tc.topic_id).first()
                if not topic:
                    raise HTTPException(status_code=400, detail=f"Topic {tc.topic_id} not found")

                try:
                    q_type = QuestionType(tc.question_type)
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"Invalid question type: {tc.question_type}")
                try:
                    diff = Difficulty(tc.difficulty)
                except ValueError:
                    raise HTTPException(status_code=400, detail=f"Invalid difficulty: {tc.difficulty}")

                if tc.question_count < 1:
                    raise HTTPException(status_code=400, detail="Question count must be at least 1")

                section_name = (tc.section_name or "General").strip() or "General"
                key = (tc.topic_id, q_type, diff)
                grouped_requested[key] = grouped_requested.get(key, 0) + tc.question_count
                validated_configs.append((tc, topic, q_type, diff, section_name))

            # Validate availability
            for key, requested_total in grouped_requested.items():
                topic_id, q_type, diff = key
                topic = db.query(Topic).filter(Topic.id == topic_id).first()
                available_count = (
                    db.query(Question)
                    .filter(
                        Question.topic_id == topic_id,
                        Question.type == q_type,
                        Question.difficulty == diff,
                        Question.is_archived == False,
                    )
                    .count()
                )
                if requested_total > available_count:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Requested {requested_total} questions for "
                            f"{topic.name if topic else topic_id}/{q_type.value}/{diff.value}, "
                            f"but only {available_count} available"
                        ),
                    )

            selected_question_ids: set[UUID] = set()

            for tc, topic, q_type, diff, section_name in validated_configs:
                at = AssessmentTopic(
                    assessment_id=assessment.id,
                    topic_id=tc.topic_id,
                    question_type=q_type,
                    difficulty=diff,
                    question_count=tc.question_count,
                )
                db.add(at)

                matching_questions = (
                    db.query(Question)
                    .filter(
                        Question.topic_id == tc.topic_id,
                        Question.type == q_type,
                        Question.difficulty == diff,
                        Question.is_archived == False,
                        Question.id.notin_(list(selected_question_ids)) if selected_question_ids else True,
                    )
                    .order_by(func.random())
                    .limit(tc.question_count)
                    .all()
                )

                if len(matching_questions) < tc.question_count:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Not enough unique questions left for section '{section_name}' "
                            f"in {topic.name}/{tc.question_type}/{tc.difficulty}"
                        ),
                    )

                for q in matching_questions:
                    selected_question_ids.add(q.id)
                    aq = AssessmentQuestion(
                        assessment_id=assessment.id,
                        question_id=q.id,
                    )
                    db.add(aq)
                    db.add(AssessmentQuestionSection(
                        assessment_id=assessment.id,
                        question_id=q.id,
                        section_name=section_name,
                    ))

                total_questions += len(matching_questions)

                topic_results.append(AssessmentTopicOut(
                    topic_name=topic.name,
                    question_type=tc.question_type,
                    difficulty=tc.difficulty,
                    question_count=tc.question_count,
                    selected_count=len(matching_questions),
                    section_name=section_name,
                ))

            for bid in body.batch_ids:
                assignment = Assignment(
                    assessment_id=assessment.id,
                    batch_id=bid,
                )
                db.add(assignment)

            db.commit()

            return {
                "id": assessment.id,
                "title": assessment.title,
                "description": assessment.description,
                "duration": assessment.duration,
                "negative_marking": assessment.negative_marking,
                "is_archived": getattr(assessment, "is_archived", False),
                "total_questions": total_questions,
                "topics": topic_results,
                "batch_names": batch_names,
                "start_time": _to_utc_iso(assessment.start_time),
                "end_time": _to_utc_iso(assessment.end_time),
                "created_at": assessment.created_at.isoformat(),
            }
        finally:
            db.close()

    out = await run_db_sync(_sync_work)
    return AssessmentOut(**out)


@router.get("/", response_model=AssessmentListResponse)
async def list_assessments(
    batch_id: UUID | None = None,
    status: str | None = None,
    limit: int = 0,
    page: int = 1,
    _admin: User = Depends(require_admin),
):
    """List assessments with optional filtering and pagination.

    This endpoint runs the DB-intensive work in a threadpool using
    `db.async_helpers.run_db_sync` so the event loop is not blocked.
    """
    

    def _sync_work():
        db = SessionLocal()
        try:
            q = db.query(Assessment)
            if batch_id:
                q = q.join(Assignment, Assignment.assessment_id == Assessment.id).filter(Assignment.batch_id == batch_id)

            now = datetime.now(timezone.utc)
            if status:
                s = status.lower()
                if s == "upcoming":
                    q = q.filter(Assessment.start_time != None, Assessment.start_time > now)
                elif s in ("completed", "complete"):
                    q = q.filter(Assessment.end_time != None, Assessment.end_time <= now)
                elif s in ("ongoing", "current", "in_progress"):
                    q = q.filter(
                        ((Assessment.start_time == None) | (Assessment.start_time <= now))
                        & ((Assessment.end_time == None) | (Assessment.end_time > now))
                    )

            q = q.order_by(Assessment.created_at.desc())
            total = q.count()

            if limit and limit > 0:
                q = q.limit(limit).offset((max(page, 1) - 1) * limit)

            assessments = q.all()

            result = []
            for a in assessments:
                total_q = db.query(AssessmentQuestion).filter(AssessmentQuestion.assessment_id == a.id).count()
                assignments = db.query(Assignment).filter(Assignment.assessment_id == a.id).all()
                b_names = []
                for asgn in assignments:
                    batch = db.query(Batch).filter(Batch.id == asgn.batch_id).first()
                    if batch:
                        b_names.append(batch.name)
                result.append(AssessmentListItem(
                    id=a.id,
                    title=a.title,
                    description=a.description,
                    duration=a.duration,
                    negative_marking=a.negative_marking,
                    is_archived=getattr(a, "is_archived", False),
                    total_questions=total_q,
                    batch_names=b_names,
                    start_time=_to_utc_iso(a.start_time),
                    end_time=_to_utc_iso(a.end_time),
                    created_at=a.created_at.isoformat(),
                ))

            return AssessmentListResponse(items=result, total=total, page=(page if limit and limit > 0 else 1), limit=(limit if limit and limit > 0 else total))
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.get("/{assessment_id}", response_model=AssessmentOut)
async def get_assessment(
    assessment_id: UUID,
    _admin: User = Depends(require_admin),
):
    """Get assessment details.

    Offload sync DB work to a threadpool via `run_db_sync` so async workers
    can call this endpoint without blocking the event loop.
    """
    

    def _sync_work():
        db = SessionLocal()
        try:
            assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
            if not assessment:
                raise HTTPException(status_code=404, detail="Assessment not found")

            topic_configs = db.query(AssessmentTopic).filter(AssessmentTopic.assessment_id == assessment_id).all()
            total_q = db.query(AssessmentQuestion).filter(AssessmentQuestion.assessment_id == assessment_id).count()

            topic_results = []
            for tc in topic_configs:
                topic = db.query(Topic).filter(Topic.id == tc.topic_id).first()
                # Count actually selected questions for this config
                selected = (
                    db.query(AssessmentQuestion)
                    .join(Question, AssessmentQuestion.question_id == Question.id)
                    .filter(
                        AssessmentQuestion.assessment_id == assessment_id,
                        Question.topic_id == tc.topic_id,
                        Question.type == tc.question_type,
                        Question.difficulty == tc.difficulty,
                    )
                    .count()
                )
                topic_results.append(AssessmentTopicOut(
                    topic_name=topic.name if topic else "Unknown",
                    question_type=tc.question_type.value,
                    difficulty=tc.difficulty.value,
                    question_count=tc.question_count,
                    selected_count=selected,
                    section_name="General",
                ))

            # Get batch names
            assignments = db.query(Assignment).filter(Assignment.assessment_id == assessment_id).all()
            b_names = []
            for asgn in assignments:
                batch = db.query(Batch).filter(Batch.id == asgn.batch_id).first()
                if batch:
                    b_names.append(batch.name)

            return AssessmentOut(
                id=assessment.id,
                title=assessment.title,
                description=assessment.description,
                duration=assessment.duration,
                negative_marking=assessment.negative_marking,
                is_archived=getattr(assessment, "is_archived", False),
                total_questions=total_q,
                topics=topic_results,
                batch_names=b_names,
                start_time=_to_utc_iso(assessment.start_time),
                end_time=_to_utc_iso(assessment.end_time),
                created_at=assessment.created_at.isoformat(),
            )
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.delete("/{assessment_id}")
async def delete_assessment(
    assessment_id: UUID,
    _admin: User = Depends(require_admin),
):
    """Delete an assessment (soft-archive). Runs DB work in threadpool."""
    def _sync_work():
        db = SessionLocal()
        try:
            assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
            if not assessment:
                raise HTTPException(status_code=404, detail="Assessment not found")
            # Soft-archive only
            assessment.is_archived = True
            db.commit()
            return {"message": f"Assessment '{assessment.title}' archived"}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.post("/{assessment_id}/recover")
async def recover_assessment(
    assessment_id: UUID,
    _admin: User = Depends(require_admin),
):
    """Recover (un-archive) an assessment so it becomes visible/usable again."""
    def _sync_work():
        db = SessionLocal()
        try:
            assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
            if not assessment:
                raise HTTPException(status_code=404, detail="Assessment not found")

            if not getattr(assessment, "is_archived", False):
                return {"message": f"Assessment '{assessment.title}' is not archived"}

            assessment.is_archived = False
            db.commit()
            return {"message": f"Assessment '{assessment.title}' restored"}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


# ---------- Edit Assessment ---------- #


class EditAssessmentRequest(BaseModel):
    start_time: str | None = None
    end_time: str | None = None


@router.patch("/{assessment_id}")
async def edit_assessment(
    assessment_id: UUID,
    body: EditAssessmentRequest,
    _admin: User = Depends(require_admin),
):
    """Edit assessment start/end time. Validates and offloads DB updates to threadpool."""
    start_provided = body.start_time is not None
    end_provided = body.end_time is not None

    start_dt = None
    end_dt = None

    if start_provided:
        if body.start_time == "":
            start_dt = None
        else:
            try:
                start_dt = _parse_to_utc_naive(body.start_time)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_time format")

    if end_provided:
        if body.end_time == "":
            end_dt = None
        else:
            try:
                end_dt = _parse_to_utc_naive(body.end_time)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end_time format")

    def _sync_work():
        db = SessionLocal()
        try:
            assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
            if not assessment:
                raise HTTPException(status_code=404, detail="Assessment not found")

            if start_provided:
                assessment.start_time = start_dt
            if end_provided:
                assessment.end_time = end_dt

            if assessment.start_time and assessment.end_time and assessment.end_time <= assessment.start_time:
                raise HTTPException(status_code=400, detail="end_time must be after start_time")

            db.commit()
            return {"message": f"Assessment '{assessment.title}' updated"}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


# ---------- Results Endpoints ---------- #


def _classify_eval_error(error_message: str | None) -> str:
    """Classify evaluation error into a human-readable category."""
    if not error_message:
        return "unknown"
    msg = error_message.lower()
    if "401" in msg or "permission" in msg or "invalid subscription key" in msg or "unauthorized" in msg:
        return "auth_error"
    if "content_filter" in msg or "content management policy" in msg or "responsibleaipolicyviolation" in msg:
        return "content_filtered"
    if "429" in msg or "rate limit" in msg or "throttl" in msg:
        return "rate_limit"
    if "timeout" in msg or "timed out" in msg:
        return "timeout"
    if "connect" in msg or "network" in msg or "dns" in msg:
        return "network_error"
    return "unknown"


_ERROR_LABELS = {
    "auth_error": "Invalid API key or endpoint",
    "content_filtered": "Content policy violation (possible prompt injection)",
    "rate_limit": "API rate limit exceeded",
    "timeout": "Request timed out",
    "network_error": "Network / connectivity error",
    "unknown": "Unexpected error",
}


class UserAttemptResult(BaseModel):
    attempt_id: UUID | None = None
    user_id: UUID
    user_name: str
    username: str
    score: float | None
    status: str
    started_at: str | None
    submitted_at: str | None
    total_answered: int
    evaluation_status: str | None = None
    evaluation_job_id: UUID | None = None
    evaluation_error: str | None = None
    evaluation_error_category: str | None = None


class TopicPerformance(BaseModel):
    topic_name: str
    total_questions: int
    correct: float
    percentage: float


class AssessmentResultsOut(BaseModel):
    assessment_id: UUID
    assessment_title: str
    total_participants: int
    completed_count: int
    average_score: float | None
    topic_performance: List[TopicPerformance]
    user_results: List[UserAttemptResult]
    total_user_results: int  # total count before pagination (after filtering)


@router.get("/{assessment_id}/results", response_model=AssessmentResultsOut)
async def get_assessment_results(
    assessment_id: UUID,
    page: int = 1,
    page_size: int = 50,
    batch_id: UUID | None = None,
    status_filter: str | None = None,
    _admin: User = Depends(require_admin),
):
    """Get detailed results for an assessment including per-user and per-topic breakdown.

    Runs the original sync logic in a threadpool via `run_db_sync` to avoid
    blocking the async event loop.
    """
    

    def _sync_work():
        db = SessionLocal()
        try:
            assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
            if not assessment:
                raise HTTPException(status_code=404, detail="Assessment not found")

            scoped_user_ids: set[UUID] | None = None
            if batch_id:
                assigned_to_batch = (
                    db.query(Assignment)
                    .filter(Assignment.assessment_id == assessment_id, Assignment.batch_id == batch_id)
                    .first()
                )
                if not assigned_to_batch:
                    raise HTTPException(status_code=404, detail="Assessment is not assigned to this batch")

                scoped_user_ids = {
                    row.user_id for row in db.query(BatchUser).filter(BatchUser.batch_id == batch_id).all()
                }

            # Get all attempts for this assessment
            attempt_query = db.query(Attempt).filter(Attempt.assessment_id == assessment_id)
            if scoped_user_ids is not None:
                if scoped_user_ids:
                    attempt_query = attempt_query.filter(Attempt.user_id.in_(scoped_user_ids))
                else:
                    attempt_query = attempt_query.filter(False)
            attempts = attempt_query.all()

            # Deduplicate: keep only the latest attempt per user
            latest_attempts: dict[UUID, Attempt] = {}
            for attempt in attempts:
                existing = latest_attempts.get(attempt.user_id)
                if existing is None or (attempt.started_at and (not existing.started_at or attempt.started_at > existing.started_at)):
                    latest_attempts[attempt.user_id] = attempt
            attempts = list(latest_attempts.values())

            user_results: List[UserAttemptResult] = []
            total_scores: List[float] = []

            for attempt in attempts:
                user = db.query(User).filter(User.id == attempt.user_id).first()
                answer_count = db.query(Answer).filter(Answer.attempt_id == attempt.id).count()

                # Calculate score based on MCQ auto-evaluation
                score = _calculate_attempt_score(db, attempt)

                if score is not None:
                    total_scores.append(score)

                # Get evaluation job status for this attempt
                eval_job = db.query(EvaluationJob).filter(EvaluationJob.attempt_id == attempt.id).first()

                # Classify error for admin display
                error_cat = _classify_eval_error(eval_job.error_message) if eval_job and eval_job.error_message else None

                user_results.append(UserAttemptResult(
                    attempt_id=attempt.id,
                    user_id=attempt.user_id,
                    user_name=user.name if user else "Unknown",
                    username=user.username if user else "unknown",
                    score=score,
                    status=("evaluating" if attempt.status == AttemptStatus.completed and score is None else (attempt.status.value if attempt.status else "unknown")),
                    started_at=attempt.started_at.isoformat() if attempt.started_at else None,
                    submitted_at=attempt.submitted_at.isoformat() if attempt.submitted_at else None,
                    total_answered=answer_count,
                    evaluation_status=eval_job.status.value if eval_job else None,
                    evaluation_job_id=eval_job.id if eval_job else None,
                    evaluation_error=_ERROR_LABELS.get(error_cat, None) if error_cat else None,
                    evaluation_error_category=error_cat,
                ))

            # Topic performance
            topic_performance = _calculate_topic_performance(db, assessment_id, attempts)

            completed_count = len([a for a in attempts if a.status == AttemptStatus.completed])
            avg_score = round(sum(total_scores) / len(total_scores), 1) if total_scores else None

            # Find assigned users who haven't started yet
            # Get all batch_ids assigned to this assessment
            if batch_id:
                assignment_batch_ids = [batch_id]
            else:
                assignment_batch_ids = [
                    a.batch_id for a in db.query(Assignment).filter(Assignment.assessment_id == assessment_id).all()
                    if a.batch_id
                ]
            if assignment_batch_ids:
                # Get all users in those batches
                assigned_user_ids = set(
                    row.user_id for row in
                    db.query(BatchUser).filter(BatchUser.batch_id.in_(assignment_batch_ids)).all()
                )
                if scoped_user_ids is not None:
                    assigned_user_ids &= scoped_user_ids
                # Remove users who already have an attempt
                users_with_attempts = set(latest_attempts.keys())
                pending_user_ids = assigned_user_ids - users_with_attempts

                for uid in pending_user_ids:
                    user = db.query(User).filter(User.id == uid).first()
                    if user:
                        user_results.append(UserAttemptResult(
                            attempt_id=None,
                            user_id=uid,
                            user_name=user.name or user.username,
                            username=user.username,
                            score=None,
                            status="pending",
                            started_at=None,
                            submitted_at=None,
                            total_answered=0,
                            evaluation_status=None,
                            evaluation_job_id=None,
                            evaluation_error=None,
                            evaluation_error_category=None,
                        ))

            total_participants = len(user_results)

            # Apply status filter if provided
            filtered_results = user_results
            if status_filter:
                filtered_results = [ur for ur in user_results if ur.status == status_filter]

            total_user_results = len(filtered_results)

            # Apply pagination
            start = (page - 1) * page_size
            end = start + page_size
            paged_results = filtered_results[start:end]

            return AssessmentResultsOut(
                assessment_id=assessment_id,
                assessment_title=assessment.title,
                total_participants=total_participants,
                completed_count=completed_count,
                average_score=avg_score,
                topic_performance=topic_performance,
                user_results=paged_results,
                total_user_results=total_user_results,
            )
        finally:
            db.close()

    return await run_db_sync(_sync_work)


def _safe_filename_part(value: str) -> str:
    sanitized = re.sub(r'[^A-Za-z0-9._-]+', '_', value.strip())
    return sanitized.strip('_') or 'value'


def _safe_sheet_title(value: str, used: set[str]) -> str:
    cleaned = re.sub(r'[\[\]\:\*\?\/\\]+', '_', value.strip()) or "Sheet"
    base = cleaned[:31]
    title = base
    counter = 2
    while title in used:
        suffix = f" {counter}"
        title = f"{base[:31 - len(suffix)]}{suffix}"
        counter += 1
    used.add(title)
    return title


def _append_attempt_tables(sheet, username: str, user_name: str, results: dict) -> None:
    sheet.append(["Username", username])
    sheet.append(["Name", user_name])
    sheet.append(["Assessment", results.get("assessment_title")])
    sheet.append(["Started At", results.get("started_at") or ""])
    sheet.append(["Submitted At", results.get("submitted_at") or ""])
    sheet.append(["Status", results.get("status")])
    sheet.append(["Score", results.get("score") if results.get("score") is not None else "Pending"])
    sheet.append(["Answered", f"{results.get('answered')}/{results.get('total_questions')}"])
    sheet.append([])
    sheet.append(["Topic", "Earned", "Total", "Percentage"])
    for topic_score in results.get("topic_scores", []):
        sheet.append([
            topic_score.get("topic_name"),
            topic_score.get("correct"),
            topic_score.get("total"),
            topic_score.get("percentage"),
        ])
    sheet.append([])
    sheet.append(["Question No", "Topic", "Type", "Question", "Your Answer", "Correct Answer", "Score", "Suggestion"])
    for index, answer in enumerate(results.get("answers", []), start=1):
        sheet.append([
            index,
            answer.get("topic_name"),
            answer.get("question_type"),
            answer.get("question_text"),
            answer.get("your_answer"),
            answer.get("correct_answer"),
            answer.get("score") if answer.get("score") is not None else "Pending",
            answer.get("suggestion") or "",
        ])


@router.get("/{assessment_id}/results/export")
async def export_assessment_results(
    assessment_id: UUID,
    batch_id: UUID | None = None,
    status_filter: str | None = None,
    _admin: User = Depends(require_admin),
):
    """Export all users in the selected assessment/batch filter to Excel."""

    def _sync_work():
        db = SessionLocal()
        try:
            try:
                from .results_helpers import build_attempt_results
            except Exception:
                raise HTTPException(status_code=500, detail="Failed to load results helper")

            assessment = db.query(Assessment).filter(Assessment.id == assessment_id).first()
            if not assessment:
                raise HTTPException(status_code=404, detail="Assessment not found")

            batch = db.query(Batch).filter(Batch.id == batch_id).first() if batch_id else None
            if batch_id and not batch:
                raise HTTPException(status_code=404, detail="Batch not found")

            scoped_user_ids: set[UUID] | None = None
            if batch_id:
                assigned_to_batch = (
                    db.query(Assignment)
                    .filter(Assignment.assessment_id == assessment_id, Assignment.batch_id == batch_id)
                    .first()
                )
                if not assigned_to_batch:
                    raise HTTPException(status_code=404, detail="Assessment is not assigned to this batch")
                scoped_user_ids = {
                    row.user_id for row in db.query(BatchUser).filter(BatchUser.batch_id == batch_id).all()
                }

            attempt_query = db.query(Attempt).filter(Attempt.assessment_id == assessment_id)
            if scoped_user_ids is not None:
                if scoped_user_ids:
                    attempt_query = attempt_query.filter(Attempt.user_id.in_(scoped_user_ids))
                else:
                    attempt_query = attempt_query.filter(False)
            raw_attempts = attempt_query.all()

            latest_attempts: dict[UUID, Attempt] = {}
            for attempt in raw_attempts:
                existing = latest_attempts.get(attempt.user_id)
                if existing is None or (attempt.started_at and (not existing.started_at or attempt.started_at > existing.started_at)):
                    latest_attempts[attempt.user_id] = attempt
            attempts = list(latest_attempts.values())

            rows: list[dict] = []
            total_scores: list[float] = []
            for attempt in attempts:
                user = db.query(User).filter(User.id == attempt.user_id).first()
                answer_count = db.query(Answer).filter(Answer.attempt_id == attempt.id).count()
                score = _calculate_attempt_score(db, attempt)
                if score is not None:
                    total_scores.append(score)
                eval_job = db.query(EvaluationJob).filter(EvaluationJob.attempt_id == attempt.id).first()
                status = "evaluating" if attempt.status == AttemptStatus.completed and score is None else (attempt.status.value if attempt.status else "unknown")
                rows.append({
                    "attempt": attempt,
                    "user": user,
                    "attempt_id": attempt.id,
                    "user_id": attempt.user_id,
                    "user_name": user.name if user else "Unknown",
                    "username": user.username if user else "unknown",
                    "score": score,
                    "status": status,
                    "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
                    "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
                    "total_answered": answer_count,
                    "evaluation_status": eval_job.status.value if eval_job else None,
                })

            assignment_batch_ids = [batch_id] if batch_id else [
                a.batch_id for a in db.query(Assignment).filter(Assignment.assessment_id == assessment_id).all()
                if a.batch_id
            ]
            if assignment_batch_ids:
                assigned_user_ids = {
                    row.user_id for row in db.query(BatchUser).filter(BatchUser.batch_id.in_(assignment_batch_ids)).all()
                }
                if scoped_user_ids is not None:
                    assigned_user_ids &= scoped_user_ids
                pending_user_ids = assigned_user_ids - set(latest_attempts.keys())
                for uid in pending_user_ids:
                    user = db.query(User).filter(User.id == uid).first()
                    if user:
                        rows.append({
                            "attempt": None,
                            "user": user,
                            "attempt_id": None,
                            "user_id": uid,
                            "user_name": user.name or user.username,
                            "username": user.username,
                            "score": None,
                            "status": "pending",
                            "started_at": None,
                            "submitted_at": None,
                            "total_answered": 0,
                            "evaluation_status": None,
                        })

            total_participants = len(rows)
            completed_count = sum(1 for attempt in attempts if attempt.status == AttemptStatus.completed)
            avg_score = round(sum(total_scores) / len(total_scores), 1) if total_scores else None
            topic_performance = _calculate_topic_performance(db, assessment_id, attempts)

            filtered_rows = rows
            if status_filter:
                filtered_rows = [row for row in rows if row["status"] == status_filter]

            workbook = Workbook()
            overall_sheet = workbook.active
            overall_sheet.title = "Overall"
            overall_sheet.append(["Assessment", assessment.title])
            overall_sheet.append(["Batch", batch.name if batch else "All Batches"])
            overall_sheet.append(["Status Filter", status_filter or "All Statuses"])
            overall_sheet.append(["Average Score", avg_score if avg_score is not None else "N/A"])
            overall_sheet.append(["Completion Rate", f"{round((completed_count / total_participants) * 100)}%" if total_participants else "0%"])
            overall_sheet.append(["Completed / Participants", f"{completed_count}/{total_participants}"])
            overall_sheet.append(["Exported Users", len(filtered_rows)])
            overall_sheet.append([])
            overall_sheet.append(["Topic", "Correct", "Total Questions", "Percentage"])
            for topic in topic_performance:
                overall_sheet.append([topic.topic_name, topic.correct, topic.total_questions, topic.percentage])
            overall_sheet.append([])
            overall_sheet.append(["Name", "Username", "Status", "Score", "Answered", "Started At", "Submitted At", "Evaluation Status"])
            for row in filtered_rows:
                overall_sheet.append([
                    row["user_name"],
                    row["username"],
                    row["status"],
                    row["score"] if row["score"] is not None else "",
                    row["total_answered"],
                    row["started_at"] or "",
                    row["submitted_at"] or "",
                    row["evaluation_status"] or "",
                ])

            used_sheet_titles = {"Overall"}
            for row in filtered_rows:
                attempt = row["attempt"]
                if not attempt:
                    continue
                try:
                    attempt_results = build_attempt_results(db, attempt)
                except ValueError:
                    continue
                sheet_title = _safe_sheet_title(f"{row['username']}", used_sheet_titles)
                sheet = workbook.create_sheet(sheet_title)
                _append_attempt_tables(sheet, row["username"], row["user_name"], attempt_results)

            buffer = BytesIO()
            workbook.save(buffer)
            buffer.seek(0)

            filename = (
                f"{_safe_filename_part(assessment.title)}_"
                f"{_safe_filename_part(batch.name if batch else 'all_batches')}_"
                f"results_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.xlsx"
            )
            return {"buffer": buffer, "filename": filename}
        finally:
            db.close()

    payload = await run_db_sync(_sync_work)
    return StreamingResponse(
        payload["buffer"],
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{payload["filename"]}"'},
    )


def _calculate_attempt_score(db: Session, attempt: Attempt) -> float | None:
    """Calculate score for an attempt based on persisted per-answer scores."""
    if attempt.score is not None:
        return round(attempt.score, 1)

    answers = db.query(Answer).filter(Answer.attempt_id == attempt.id).all()
    if not answers:
        return None

    total = 0
    earned = 0.0

    for ans in answers:
        # Support answers that reference either global Question or per-assessment AssessmentQuestionItem
        q = None
        item = None
        if getattr(ans, "question_id", None):
            q = db.query(Question).filter(Question.id == ans.question_id).first()
        elif getattr(ans, "assessment_item_id", None):
            item = db.query(AssessmentQuestionItem).filter(AssessmentQuestionItem.id == ans.assessment_item_id).first()

        # Skip answers that do not map to a question/item (shouldn't happen)
        if not q and not item:
            continue

        total += 1
        if ans.score is None:
            return None
        earned += float(ans.score)

    return round((earned / total) * 100, 1) if total > 0 else None


def _calculate_topic_performance(
    db: Session, assessment_id: UUID, attempts: list
) -> List[TopicPerformance]:
    """Calculate per-topic performance across all attempts."""
    # Get assessment questions grouped by topic
    aq_links = db.query(AssessmentQuestion).filter(AssessmentQuestion.assessment_id == assessment_id).all()

    topic_stats: dict = {}  # topic_name -> {total, correct}

    for aq in aq_links:
        # Support per-assessment items as well as global questions
        if getattr(aq, "assessment_item_id", None):
            item = db.query(AssessmentQuestionItem).filter(AssessmentQuestionItem.id == aq.assessment_item_id).first()
            if not item:
                continue
            topic_name = item.topic or "Unknown"

            if topic_name not in topic_stats:
                topic_stats[topic_name] = {"total": 0, "correct": 0}

            for attempt in attempts:
                ans = (
                    db.query(Answer)
                    .filter(Answer.attempt_id == attempt.id, Answer.assessment_item_id == item.id)
                    .first()
                )
                if not ans:
                    continue
                topic_stats[topic_name]["total"] += 1
                if ans.score is not None:
                    topic_stats[topic_name]["correct"] += float(ans.score)
        else:
            question = db.query(Question).filter(Question.id == aq.question_id).first()
            if not question:
                continue
            topic = db.query(Topic).filter(Topic.id == question.topic_id).first()
            topic_name = topic.name if topic else "Unknown"

            if topic_name not in topic_stats:
                topic_stats[topic_name] = {"total": 0, "correct": 0}

            # Count correct answers across all attempts for this question
            for attempt in attempts:
                ans = (
                    db.query(Answer)
                    .filter(Answer.attempt_id == attempt.id, Answer.question_id == question.id)
                    .first()
                )
                if not ans:
                    continue
                topic_stats[topic_name]["total"] += 1
                if ans.score is not None:
                    topic_stats[topic_name]["correct"] += float(ans.score)

    result = []
    for name, stats in topic_stats.items():
        pct = round((stats["correct"] / stats["total"]) * 100, 1) if stats["total"] > 0 else 0
        result.append(TopicPerformance(
            topic_name=name,
            total_questions=stats["total"],
            correct=stats["correct"],
            percentage=pct,
        ))
    return result
