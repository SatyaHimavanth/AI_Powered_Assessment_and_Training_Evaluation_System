from datetime import datetime, timezone, timedelta
from io import BytesIO
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from core.auth import get_password_hash, require_admin
from db.database import SessionLocal
from db.async_helpers import run_db_sync
from db.models import (
    Batch,
    BatchUser,
    PracticeAccessRequest,
    PracticeAccessStatus,
    RegistrationRequest,
    RegistrationStatus,
    User,
    UserRole,
    EvaluationJob,
    EvaluationJobStatus,
    Attempt,
    ImportedAssessment,
    ImportedQuestion,
    ImportStatus,
    Topic,
    Question,
    QuestionOption,
    Assessment,
    AssessmentQuestion,
    AssessmentQuestionSection,
    AssessmentQuestionItem,
    AssessmentTopic,
    Assignment,
    Difficulty,
    QuestionType,
    TopicScore,
    Answer,
    AttemptStatus,
    InterviewAccessRequest,
    InterviewAccessStatus,
    InterviewSession,
    InterviewSessionStatus,
)

import re
import os

router = APIRouter(prefix="/admin", tags=["admin"])


class MessageResponse(BaseModel):
    message: str


class AdminDashboardCountersOut(BaseModel):
    pending_interview_requests: int
    in_progress_interviews: int
    pending_assessments: int
    in_progress_assessments: int
    total_users: int
    pending_registrations: int
    total_topics: int
    total_batches: int


@router.get("/dashboard/counters", response_model=AdminDashboardCountersOut)
async def get_admin_dashboard_counters(
    _admin: User = Depends(require_admin),
):
    """Return dashboard counters for approvals/workload cards."""

    def _sync_work():
        db = SessionLocal()
        try:
            pending_interview_requests = (
                db.query(InterviewAccessRequest)
                .filter(InterviewAccessRequest.status == InterviewAccessStatus.pending)
                .count()
            )
            in_progress_interviews = (
                db.query(InterviewSession)
                .filter(
                    InterviewSession.status.in_(
                        [InterviewSessionStatus.in_progress, InterviewSessionStatus.paused]
                    )
                )
                .count()
            )
            pending_assessments = (
                db.query(Assignment)
                .join(Assessment, Assignment.assessment_id == Assessment.id)
                .filter(Assessment.is_archived.is_(False))
                .count()
            )
            in_progress_assessments = (
                db.query(Attempt)
                .filter(Attempt.status == AttemptStatus.in_progress)
                .count()
            )

            total_users = (
                db.query(User)
                .filter(User.role == UserRole.user)
                .count()
            )
            pending_registrations = (
                db.query(RegistrationRequest)
                .filter(RegistrationRequest.status == RegistrationStatus.pending)
                .count()
            )
            total_topics = db.query(Topic).count()
            total_batches = db.query(Batch).count()

            return {
                "pending_interview_requests": pending_interview_requests,
                "in_progress_interviews": in_progress_interviews,
                "pending_assessments": pending_assessments,
                "in_progress_assessments": in_progress_assessments,
                "total_users": total_users,
                "pending_registrations": pending_registrations,
                "total_topics": total_topics,
                "total_batches": total_batches,
            }
        finally:
            db.close()

    return await run_db_sync(_sync_work)




@router.post("/users/{user_id}/toggle-active", response_model=MessageResponse)
async def toggle_user_active(
    user_id: UUID,
    _admin: User = Depends(require_admin),
):
    """Toggle a user's active status (activate/deactivate)."""
    def _sync_work():
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            user.is_active = not user.is_active
            db.commit()
            status = "activated" if user.is_active else "deactivated"
            return {"message": f"User '{user.username}' has been {status}."}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


class UserUpdateIn(BaseModel):
    name: str | None = None
    username: str | None = None
    email: str | None = None
    contact_email: str | None = None
    account: str | None = None
    is_active: bool | None = None


@router.patch("/users/{user_id}", response_model=MessageResponse)
async def update_user(
    user_id: UUID,
    payload: UserUpdateIn,
    _admin: User = Depends(require_admin),
):
    """Update user account field."""
    def _sync_work():
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            # Update fields if provided
            if payload.account is not None:
                user.account = payload.account
            if payload.name is not None:
                user.name = payload.name
            if payload.username is not None:
                # Ensure username uniqueness
                existing = db.query(User).filter(User.username == payload.username).first()
                if existing and existing.id != user.id:
                    raise HTTPException(status_code=400, detail="Username already in use")
                user.username = payload.username
            if payload.email is not None:
                # Ensure email uniqueness
                existing_email = db.query(User).filter(User.email == payload.email).first()
                if existing_email and existing_email.id != user.id:
                    raise HTTPException(status_code=400, detail="Email already in use")
                user.email = payload.email
            if payload.contact_email is not None:
                # Ensure email uniqueness
                existing_email = db.query(User).filter(User.contact_email == payload.contact_email).first()
                if existing_email and existing_email.id != user.id:
                    raise HTTPException(status_code=400, detail="Email already in use")
                user.contact_email = payload.contact_email
            if payload.is_active is not None:
                user.is_active = payload.is_active
            db.commit()
            return {"message": f"User '{user.username}' updated successfully."}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


class PasswordUpdateIn(BaseModel):
    password: str


@router.patch("/users/{user_id}/password", response_model=MessageResponse)
async def update_user_password(
    user_id: UUID,
    payload: PasswordUpdateIn,
    _admin: User = Depends(require_admin),
):
    """Update a user's password (admin only)."""
    # Basic validation
    if not payload.password or len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    def _sync_work():
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            user.hashed_password = get_password_hash(payload.password)
            db.commit()
            return {"message": f"Password updated for user '{user.username}'."}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


class UserBatchesOut(BaseModel):
    batch_ids: List[UUID]


@router.get("/users/{user_id}/batches", response_model=UserBatchesOut)
async def get_user_batches(
    user_id: UUID,
    _admin: User = Depends(require_admin),
):
    """Get all batch IDs a user belongs to."""
    def _sync_work():
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            batch_ids = [bu.batch_id for bu in db.query(BatchUser).filter(BatchUser.user_id == user_id).all()]
            return {"batch_ids": batch_ids}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


class UserBatchesUpdateIn(BaseModel):
    batch_ids: List[UUID]


@router.put("/users/{user_id}/batches", response_model=MessageResponse)
async def update_user_batches(
    user_id: UUID,
    payload: UserBatchesUpdateIn,
    _admin: User = Depends(require_admin),
):
    """Replace user's batch memberships."""
    def _sync_work():
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            # Remove existing batch memberships
            db.query(BatchUser).filter(BatchUser.user_id == user_id).delete()

            # Add new memberships
            for batch_id in payload.batch_ids:
                batch = db.query(Batch).filter(Batch.id == batch_id).first()
                if batch:
                    db.add(BatchUser(batch_id=batch_id, user_id=user_id))

            db.commit()
            return {"message": f"Batches updated for user '{user.username}'."}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.post("/reset-attempt/{attempt_id}", response_model=MessageResponse)
async def reset_user_attempt(
    attempt_id: UUID,
    _admin: User = Depends(require_admin),
):
    """Admin endpoint to reset a user's attempt, allowing them to retake the assessment."""
    def _sync_work():
        from db.models import Attempt, Answer, TopicScore, EvaluationJob
        db = SessionLocal()
        try:
            attempt = db.query(Attempt).filter(Attempt.id == attempt_id).first()
            if not attempt:
                raise HTTPException(status_code=404, detail="Attempt not found")

            # Delete all related records first (to respect foreign key constraints)
            db.query(EvaluationJob).filter(EvaluationJob.attempt_id == attempt_id).delete()
            db.query(TopicScore).filter(TopicScore.attempt_id == attempt_id).delete()
            db.query(Answer).filter(Answer.attempt_id == attempt_id).delete()
            
            # Now delete the attempt
            db.delete(attempt)
            db.commit()

            return {"message": "Attempt reset successfully. User can now retake the assessment."}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


class TopicScoreDetail(BaseModel):
    topic_name: str
    total: int
    correct: float
    percentage: float


class UserAttemptDetail(BaseModel):
    assessment_title: str
    score: float | None
    status: str
    topic_scores: List[TopicScoreDetail]


@router.get("/attempt/{attempt_id}/topics", response_model=UserAttemptDetail)
async def get_attempt_topic_scores(
    attempt_id: UUID,
    _admin: User = Depends(require_admin),
):
    """Get topic-wise scores for a specific user's attempt (runs DB work in threadpool)."""
    def _sync_work():
        db = SessionLocal()
        try:
            from db.models import Attempt, Assessment, Answer, Question, AssessmentQuestionItem

            attempt = db.query(Attempt).filter(Attempt.id == attempt_id).first()
            if not attempt:
                raise HTTPException(status_code=404, detail="Attempt not found")

            assessment = db.query(Assessment).filter(Assessment.id == attempt.assessment_id).first()
            if not assessment:
                raise HTTPException(status_code=404, detail="Assessment not found")

            answers = db.query(Answer).filter(Answer.attempt_id == attempt_id).all()

            topic_stats: dict[str, dict] = {}
            for answer in answers:
                q = None
                item = None
                if getattr(answer, "question_id", None):
                    q = db.query(Question).filter(Question.id == answer.question_id).first()
                elif getattr(answer, "assessment_item_id", None):
                    item = db.query(AssessmentQuestionItem).filter(AssessmentQuestionItem.id == answer.assessment_item_id).first()

                if q:
                    topic_name = q.topic.name if q.topic else "General"
                elif item:
                    topic_name = item.topic or "General"
                else:
                    continue

                if topic_name not in topic_stats:
                    topic_stats[topic_name] = {"total": 0, "correct": 0.0}

                topic_stats[topic_name]["total"] += 1
                earned_score = float(answer.score or 0) if answer.score is not None else 0.0
                topic_stats[topic_name]["correct"] += earned_score

            topic_scores: List[dict] = []
            for name, stats in topic_stats.items():
                pct = round((stats["correct"] / stats["total"]) * 100, 1) if stats["total"] > 0 else 0
                topic_scores.append({"topic_name": name, "total": stats["total"], "correct": stats["correct"], "percentage": pct})

            return {
                "assessment_title": assessment.title,
                "score": attempt.score,
                "status": attempt.status.value if attempt.status else "unknown",
                "topic_scores": topic_scores,
            }
        finally:
            db.close()

    return await run_db_sync(_sync_work)


class AttemptAnswerReviewItem(BaseModel):
    question_id: UUID
    question_text: str
    question_type: str
    topic_name: str
    your_answer: str
    correct_answer: str
    is_correct: bool
    score: float | None
    suggestion: str | None


class AttemptTopicScoreItem(BaseModel):
    topic_name: str
    total: int
    correct: float
    percentage: float


class AttemptResultsOut(BaseModel):
    assessment_title: str
    status: str
    score: float | None
    evaluation_pending: bool
    total_questions: int
    answered: int
    correct_count: int
    started_at: str | None
    submitted_at: str | None
    topic_scores: List[AttemptTopicScoreItem]
    answers: List[AttemptAnswerReviewItem]


@router.get("/attempt/{attempt_id}/results", response_model=AttemptResultsOut)
async def get_attempt_results(
    attempt_id: UUID,
    _admin: User = Depends(require_admin),
):
    """Admin: get full results for a specific attempt (question review + topic scores). Runs DB work in threadpool."""

    def _sync_work():
        db = SessionLocal()
        try:
            from db.models import (
                Attempt,
                Assessment,
                Answer,
                Question,
                QuestionOption,
                QuestionType,
                AssessmentQuestion,
                AssessmentQuestionItem,
                Topic,
                AttemptStatus,
            )

            attempt = db.query(Attempt).filter(Attempt.id == attempt_id).first()
            if not attempt:
                raise HTTPException(status_code=404, detail="Attempt not found")

            assessment = db.query(Assessment).filter(Assessment.id == attempt.assessment_id).first()
            if not assessment:
                raise HTTPException(status_code=404, detail="Assessment not found")

            aq_links = (
                db.query(AssessmentQuestion)
                .filter(AssessmentQuestion.assessment_id == assessment.id)
                .all()
            )

            item_ids = [aq.assessment_item_id for aq in aq_links if getattr(aq, "assessment_item_id", None)]
            question_ids = [aq.question_id for aq in aq_links if getattr(aq, "question_id", None)]

            items = db.query(AssessmentQuestionItem).filter(AssessmentQuestionItem.id.in_(item_ids)).all() if item_ids else []
            questions = db.query(Question).filter(Question.id.in_(question_ids)).all() if question_ids else []

            items_map = {str(i.id): i for i in items}
            q_map = {str(q.id): q for q in questions}

            user_answers = db.query(Answer).filter(Answer.attempt_id == attempt.id).all()
            answer_map = {str(a.assessment_item_id or a.question_id): a for a in user_answers}

            answers_out: List[dict] = []
            topic_stats: dict = {}
            correct_count = 0
            pending_answers = db.query(Answer).filter(Answer.attempt_id == attempt.id, Answer.score.is_(None)).count()
            evaluation_pending = pending_answers > 0 or attempt.score is None

            for aq in aq_links:
                user_ans = None
                topic_name = "Unknown"
                question_text = ""
                question_type = "text"
                correct_answer_text = ""
                user_answer_text = ""
                is_correct = False
                score_val = None

                if getattr(aq, "assessment_item_id", None):
                    item = items_map.get(str(aq.assessment_item_id))
                    if not item:
                        continue
                    question_text = item.question_text
                    question_type = item.question_type or "text"
                    topic_name = item.topic or "Unknown"

                    if item.options:
                        correct_opts = [o for o in item.options if o.get("is_correct")]
                        correct_answer_text = ", ".join(o.get("option_text") for o in correct_opts) if correct_opts else (item.reference_answer or "")
                    else:
                        correct_answer_text = item.reference_answer or ""

                    user_ans = answer_map.get(str(item.id))
                    if user_ans and user_ans.answer:
                        if question_type in ("single_mcq", "multi_mcq") and item.options:
                            selected_ids = user_ans.answer.split(",")
                            selected_texts = [next((o.get("option_text") for o in item.options if str(o.get("id")) == s), "") for s in selected_ids]
                            user_answer_text = ", ".join([t for t in selected_texts if t])
                            is_correct = (user_ans.score or 0) >= 0.999 if user_ans.score is not None else False
                        else:
                            user_answer_text = user_ans.answer
                            is_correct = (user_ans.score or 0) >= 0.999 if user_ans.score is not None else False

                    earned_score = float(user_ans.score or 0) if user_ans and user_ans.score is not None else 0.0
                    topic_stats.setdefault(topic_name, {"total": 0, "correct": 0})
                    topic_stats[topic_name]["total"] += 1
                    topic_stats[topic_name]["correct"] += earned_score
                    if is_correct:
                        correct_count += 1

                    score_val = (round(float(user_ans.score), 2) if user_ans and user_ans.score is not None else None)
                    answers_out.append({
                        "question_id": item.id,
                        "question_text": question_text,
                        "question_type": question_type,
                        "topic_name": topic_name,
                        "your_answer": user_answer_text,
                        "correct_answer": correct_answer_text,
                        "is_correct": is_correct,
                        "score": score_val,
                        "suggestion": (user_ans.feedback if user_ans and user_ans.feedback else None),
                    })
                else:
                    q = q_map.get(str(aq.question_id))
                    if not q:
                        continue
                    question_text = q.question
                    question_type = q.type.value
                    topic = db.query(Topic).filter(Topic.id == q.topic_id).first()
                    topic_name = topic.name if topic else "Unknown"

                    correct_opts = (
                        db.query(QuestionOption)
                        .filter(QuestionOption.question_id == q.id, QuestionOption.is_correct == True)
                        .all()
                    )
                    correct_answer_text = ", ".join(o.option_text for o in correct_opts) if correct_opts else (q.reference_answer or "")

                    user_ans = answer_map.get(str(q.id))
                    user_answer_text = ""
                    is_correct = False
                    if user_ans and user_ans.answer:
                        if q.type in (QuestionType.single_mcq, QuestionType.multi_mcq):
                            selected_ids = user_ans.answer.split(",")
                            selected_opts = (
                                db.query(QuestionOption)
                                .filter(QuestionOption.id.in_(selected_ids))
                                .all()
                            )
                            user_answer_text = ", ".join(o.option_text for o in selected_opts)
                            is_correct = (user_ans.score or 0) >= 0.999 if user_ans.score is not None else False
                        else:
                            user_answer_text = user_ans.answer
                            is_correct = (user_ans.score or 0) >= 0.999 if user_ans.score is not None else False

                    earned_score = float(user_ans.score or 0) if user_ans and user_ans.score is not None else 0.0
                    topic_stats.setdefault(topic_name, {"total": 0, "correct": 0})
                    topic_stats[topic_name]["total"] += 1
                    topic_stats[topic_name]["correct"] += earned_score
                    if is_correct:
                        correct_count += 1

                    score_val = (round(float(user_ans.score), 2) if user_ans and user_ans.score is not None else None)
                    answers_out.append({
                        "question_id": q.id,
                        "question_text": question_text,
                        "question_type": question_type,
                        "topic_name": topic_name,
                        "your_answer": user_answer_text,
                        "correct_answer": correct_answer_text,
                        "is_correct": is_correct,
                        "score": score_val,
                        "suggestion": (user_ans.feedback if user_ans and user_ans.feedback else None),
                    })

            total_questions = len(questions) + len(items)
            answered = len(user_answers)
            score = attempt.score

            topic_scores: List[dict] = []
            for name, stats in topic_stats.items():
                pct = round((stats["correct"] / stats["total"]) * 100, 1) if stats["total"] > 0 else 0
                topic_scores.append({"topic_name": name, "total": stats["total"], "correct": stats["correct"], "percentage": pct})

            return {
                "assessment_title": assessment.title,
                "status": ("evaluating" if evaluation_pending and attempt.status == AttemptStatus.completed else (attempt.status.value if attempt.status else "unknown")),
                "score": score,
                "evaluation_pending": evaluation_pending,
                "total_questions": total_questions,
                "answered": answered,
                "correct_count": correct_count,
                "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
                "submitted_at": attempt.submitted_at.isoformat() if attempt.submitted_at else None,
                "topic_scores": topic_scores,
                "answers": answers_out,
            }
        finally:
            db.close()

    return await run_db_sync(_sync_work)


def _safe_filename_part(value: str) -> str:
    sanitized = re.sub(r'[^A-Za-z0-9._-]+', '_', value.strip())
    return sanitized.strip('_') or 'value'


@router.get("/attempt/{attempt_id}/export")
async def export_attempt_results(
    attempt_id: UUID,
    _admin: User = Depends(require_admin),
):
    """Admin: export a specific user's attempt results using the user export format."""

    def _sync_work():
        db = SessionLocal()
        try:
            try:
                from .results_helpers import build_attempt_results
            except Exception:
                raise HTTPException(status_code=500, detail="Failed to load results helper")

            attempt = db.query(Attempt).filter(Attempt.id == attempt_id).first()
            if not attempt:
                raise HTTPException(status_code=404, detail="Attempt not found")

            user = db.query(User).filter(User.id == attempt.user_id).first()
            assessment = db.query(Assessment).filter(Assessment.id == attempt.assessment_id).first()
            if not assessment:
                raise HTTPException(status_code=404, detail="Assessment not found")

            try:
                results = build_attempt_results(db, attempt)
            except ValueError as e:
                raise HTTPException(status_code=404, detail=str(e))

            username = user.username if user else "unknown"
            user_name = user.name if user else "Unknown"

            workbook = Workbook()
            summary_sheet = workbook.active
            summary_sheet.title = "Summary"
            summary_sheet.append(["Username", username])
            summary_sheet.append(["Name", user_name])
            summary_sheet.append(["Assessment", assessment.title])
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

            started_at = attempt.started_at or datetime.now(timezone.utc)
            filename = (
                f"{_safe_filename_part(username)}_"
                f"{_safe_filename_part(assessment.title)}_"
                f"{started_at.strftime('%Y%m%d_%H%M%S')}.xlsx"
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


class UserTopicPerformance(BaseModel):
    topic_name: str
    average_percentage: float
    assessment_count: int


class UserPerformanceReport(BaseModel):
    user_id: UUID
    user_name: str
    username: str
    email: str
    total_assessments: int
    completed_assessments: int
    average_score: float | None
    topic_performance: List[UserTopicPerformance]
    improvement_areas: List[str]


@router.get("/user/{user_id}/performance", response_model=UserPerformanceReport)
async def get_user_performance(
    user_id: UUID,
    _admin: User = Depends(require_admin),
):
    """Get detailed performance report for a user across all assessments (runs DB work in threadpool)."""

    def _sync_work():
        db = SessionLocal()
        try:
            from db.models import Attempt, Answer, Question, AttemptStatus, AssessmentQuestionItem

            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            attempts = db.query(Attempt).filter(Attempt.user_id == user_id).all()
            total_assessments = len(attempts)
            completed_assessments = len([a for a in attempts if a.status == AttemptStatus.completed])

            completed_scores = [a.score for a in attempts if a.score is not None]
            average_score = round(sum(completed_scores) / len(completed_scores), 1) if completed_scores else None

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

                    if answer.score is None:
                        continue

                    per_attempt_topic_scores.setdefault(topic_name, []).append(float(answer.score or 0.0))

                for topic_name, scores in per_attempt_topic_scores.items():
                    if not scores:
                        continue
                    attempt_pct = (sum(scores) / len(scores)) * 100
                    if topic_name not in topic_stats:
                        topic_stats[topic_name] = {"scores": [], "attempts": 0}
                    topic_stats[topic_name]["scores"].append(attempt_pct)
                    topic_stats[topic_name]["attempts"] += 1

            topic_performance: List[dict] = []
            for topic_name, stats in topic_stats.items():
                if stats["scores"]:
                    avg_pct = round(sum(stats["scores"]) / len(stats["scores"]), 1)
                    topic_performance.append({"topic_name": topic_name, "average_percentage": avg_pct, "assessment_count": stats["attempts"]})

            improvement_areas: List[str] = []
            low_topics = [tp for tp in topic_performance if tp["average_percentage"] < 50]
            if low_topics:
                for lt in sorted(low_topics, key=lambda x: x["average_percentage"])[:3]:
                    improvement_areas.append(f"Focus on {lt['topic_name']} (Current: {lt['average_percentage']}%)")

            if not improvement_areas and topic_performance:
                for tp in sorted(topic_performance, key=lambda x: x["average_percentage"])[:2]:
                    improvement_areas.append(f"Strengthen {tp['topic_name']} (Current: {tp['average_percentage']}%)")

            return {
                "user_id": user_id,
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

    return await run_db_sync(_sync_work)


# ---------- Evaluation Management ---------- #


class StalledEvaluationOut(BaseModel):
    attempt_id: UUID
    job_id: UUID
    user_name: str
    assessment_title: str
    submitted_at: datetime | None
    time_elapsed_minutes: int
    status: str

    class Config:
        from_attributes = True


class EvaluationJobOut(BaseModel):
    id: UUID
    attempt_id: UUID
    status: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    retry_count: int
    error_message: str | None

    class Config:
        from_attributes = True



@router.get("/evaluations/stalled", response_model=List[StalledEvaluationOut])
async def get_stalled_evaluations(
    _: User = Depends(require_admin),
):
    """Get evaluations that are pending/in_progress for >10 minutes. Runs DB work in threadpool."""

    def _sync_work():
        db = SessionLocal()
        try:
            threshold_time = datetime.now(timezone.utc) - timedelta(minutes=10)

            stalled_jobs = (
                db.query(EvaluationJob, Attempt, User)
                .join(Attempt, EvaluationJob.attempt_id == Attempt.id)
                .join(User, Attempt.user_id == User.id)
                .filter(
                    EvaluationJob.status.in_(
                        [EvaluationJobStatus.pending, EvaluationJobStatus.in_progress]
                    ),
                    EvaluationJob.created_at < threshold_time,
                )
                .all()
            )

            from db.models import Assessment

            result = []
            for job, attempt, user in stalled_jobs:
                assessment = db.query(Assessment).filter(Assessment.id == attempt.assessment_id).first()
                time_elapsed = int(
                    (datetime.now(timezone.utc) - job.created_at).total_seconds()
                    / 60
                )

                result.append({
                    "attempt_id": attempt.id,
                    "job_id": job.id,
                    "user_name": user.name,
                    "assessment_title": assessment.title if assessment else "Unknown",
                    "submitted_at": attempt.submitted_at,
                    "time_elapsed_minutes": time_elapsed,
                    "status": job.status.value,
                })

            return result
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.post("/evaluations/{job_id}/retry", response_model=MessageResponse)
async def retry_evaluation(
    job_id: UUID,
    _: User = Depends(require_admin),
):
    """Retry a failed evaluation job."""
    def _sync_work():
        db = SessionLocal()
        try:
            job = db.query(EvaluationJob).filter(EvaluationJob.id == job_id).first()
            if not job:
                raise HTTPException(status_code=404, detail="Evaluation job not found")

            if job.status == EvaluationJobStatus.failed:
                job.status = EvaluationJobStatus.pending
                job.retry_count = 0
                job.error_message = None
                db.commit()
                return {"message": "Evaluation job queued for retry"}

            return {"message": f"Job is in {job.status.value} state, cannot retry"}
        finally:
            db.close()

    res = await run_db_sync(_sync_work)
    return MessageResponse(**res)


@router.get("/evaluations/pending", response_model=List[EvaluationJobOut])
async def get_pending_evaluations(
    _: User = Depends(require_admin),
):
    """Get all pending and in-progress evaluation jobs. Runs DB work in threadpool."""

    def _sync_work():
        db = SessionLocal()
        try:
            jobs = (
                db.query(EvaluationJob)
                .filter(
                    EvaluationJob.status.in_(
                        [EvaluationJobStatus.pending, EvaluationJobStatus.in_progress]
                    )
                )
                .order_by(EvaluationJob.created_at.asc())
                .all()
            )

            result = []
            for j in jobs:
                result.append({
                    "id": j.id,
                    "attempt_id": j.attempt_id,
                    "status": j.status.value,
                    "created_at": j.created_at,
                    "started_at": j.started_at,
                    "completed_at": j.completed_at,
                    "retry_count": j.retry_count,
                    "error_message": j.error_message,
                })
            return result
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.get("/evaluations/failed", response_model=List[EvaluationJobOut])
async def get_failed_evaluations(
    _: User = Depends(require_admin),
):
    """Get all failed evaluation jobs. Runs DB work in threadpool."""

    def _sync_work():
        db = SessionLocal()
        try:
            jobs = (
                db.query(EvaluationJob)
                .filter(EvaluationJob.status == EvaluationJobStatus.failed)
                .order_by(EvaluationJob.completed_at.desc())
                .all()
            )

            result = []
            for j in jobs:
                result.append({
                    "id": j.id,
                    "attempt_id": j.attempt_id,
                    "status": j.status.value,
                    "created_at": j.created_at,
                    "started_at": j.started_at,
                    "completed_at": j.completed_at,
                    "retry_count": j.retry_count,
                    "error_message": j.error_message,
                })
            return result
        finally:
            db.close()

    return await run_db_sync(_sync_work)


# ---------- Practice Access Management ---------- #


class PracticeAccessRequestOut(BaseModel):
    id: UUID
    user_id: UUID
    user_name: str
    username: str
    reason: str | None = None
    requested_days: int | None = None
    requested_tests_per_day: int | None = None
    status: str
    requested_at: datetime
    approved_at: datetime | None
    expires_at: datetime | None
    days_granted: int | None
    tests_per_day_granted: int | None

    class Config:
        from_attributes = True


class ApprovePracticeAccessIn(BaseModel):
    days: int = 14  # default 2 weeks
    tests_per_day: int | None = None


@router.get("/practice-access-requests", response_model=List[PracticeAccessRequestOut])
async def get_practice_access_requests(
    _admin: User = Depends(require_admin),
):
    """Get all pending practice access requests."""
    def _sync_work():
        db = SessionLocal()
        try:
            requests = (
                db.query(PracticeAccessRequest, User)
                .join(User, PracticeAccessRequest.user_id == User.id)
                .filter(PracticeAccessRequest.status == PracticeAccessStatus.pending)
                .order_by(PracticeAccessRequest.requested_at.desc())
                .all()
            )
            out = []
            for req, user in requests:
                out.append({
                    "id": req.id,
                    "user_id": req.user_id,
                    "user_name": user.name,
                    "username": user.username,
                    "reason": req.reason,
                    "requested_days": req.requested_days,
                    "requested_tests_per_day": (req.requested_tests_per_day if getattr(req, "requested_tests_per_day", None) else None),
                    "status": req.status.value,
                    "requested_at": req.requested_at,
                    "approved_at": req.approved_at,
                    "expires_at": req.expires_at,
                    "days_granted": req.days_granted,
                    "tests_per_day_granted": (req.tests_per_day_granted if getattr(req, "tests_per_day_granted", None) else None),
                })
            return out
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.post("/practice-access-requests/{request_id}/approve", response_model=MessageResponse)
async def approve_practice_access(
    request_id: UUID,
    payload: ApprovePracticeAccessIn,
    _admin: User = Depends(require_admin),
):
    """Approve a practice access request with configurable duration (max 30 days)."""
    def _sync_work():
        db = SessionLocal()
        try:
            req = db.query(PracticeAccessRequest).filter(PracticeAccessRequest.id == request_id).first()
            if not req:
                raise HTTPException(status_code=404, detail="Request not found")
            if req.status != PracticeAccessStatus.pending:
                raise HTTPException(status_code=400, detail="Request already processed")

            days = min(max(payload.days, 1), 30)  # Clamp between 1 and 30
            # Clamp tests per day between 1 and system max (default 3)
            try:
                system_max = int(os.getenv("PRACTICE_TESTS_MAX_PER_DAY", "3"))
            except Exception:
                system_max = 3
            tests_per_day = None
            if getattr(payload, "tests_per_day", None) is not None:
                try:
                    tests_per_day = max(1, min(int(payload.tests_per_day), system_max))
                except Exception:
                    tests_per_day = 1
            now = datetime.now(timezone.utc)

            req.status = PracticeAccessStatus.approved
            req.approved_at = now
            req.expires_at = now + timedelta(days=days)
            req.days_granted = days
            if tests_per_day is not None:
                req.tests_per_day_granted = tests_per_day
            db.commit()

            user = db.query(User).filter(User.id == req.user_id).first()
            return {"message": f"Practice access granted to '{user.username}' for {days} days."}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.post("/practice-access-requests/{request_id}/reject", response_model=MessageResponse)
async def reject_practice_access(
    request_id: UUID,
    _admin: User = Depends(require_admin),
):
    """Reject a practice access request."""
    def _sync_work():
        db = SessionLocal()
        try:
            req = db.query(PracticeAccessRequest).filter(PracticeAccessRequest.id == request_id).first()
            if not req:
                raise HTTPException(status_code=404, detail="Request not found")
            if req.status != PracticeAccessStatus.pending:
                raise HTTPException(status_code=400, detail="Request already processed")

            req.status = PracticeAccessStatus.rejected
            db.commit()

            user = db.query(User).filter(User.id == req.user_id).first()
            return {"message": f"Practice access request from '{user.username}' rejected."}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


# ---------- User Registrations / Admin User List ---------- #


class PendingRegistrationOut(BaseModel):
    id: UUID
    username: str
    email: str
    contact_email: str
    name: str
    account: str | None = None
    status: str
    requested_at: datetime

    class Config:
        from_attributes = True


class AdminUserOut(BaseModel):
    id: UUID
    username: str
    email: str
    contact_email: str
    name: str
    account: str | None = None
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class AdminUsersPaginatedOut(BaseModel):
    items: List[AdminUserOut]
    total_count: int


class AdminCreateUserIn(BaseModel):
    username: str
    email: str
    contact_email: str
    name: str
    account: str | None = None
    password: str
    role: str = "user"


@router.post("/users", response_model=AdminUserOut)
async def create_user_by_admin(
    payload: AdminCreateUserIn,
    _admin: User = Depends(require_admin),
):
    """Create an active user/admin account directly from the admin area."""
    if not payload.password or len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    try:
        role = UserRole(payload.role)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid role")

    def _sync_work():
        db = SessionLocal()
        try:
            username = payload.username.strip()
            email = payload.email.strip()
            contact_email = payload.contact_email.strip()
            name = payload.name.strip()
            account = (payload.account or "").strip() or None

            if not username or not email or not contact_email or not name:
                raise HTTPException(status_code=400, detail="Name, username, email, and contact email are required")

            existing_user = (
                db.query(User)
                .filter(
                    (User.username == username)
                    | (User.email == email)
                    | (User.contact_email == contact_email)
                )
                .first()
            )
            if existing_user:
                raise HTTPException(status_code=400, detail="A user with same username/email/contact already exists")

            pending_request = (
                db.query(RegistrationRequest)
                .filter(
                    or_(
                        RegistrationRequest.username == username,
                        RegistrationRequest.email == email,
                        RegistrationRequest.contact_email == contact_email,
                    ),
                    RegistrationRequest.status == RegistrationStatus.pending,
                )
                .first()
            )
            if pending_request:
                raise HTTPException(status_code=400, detail="A pending registration already exists for this username/email/contact")

            user = User(
                username=username,
                email=email,
                contact_email=contact_email,
                name=name,
                account=account,
                hashed_password=get_password_hash(payload.password),
                role=role,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "contact_email": user.contact_email,
                "name": user.name,
                "account": user.account,
                "role": user.role.value,
                "is_active": user.is_active,
                "created_at": user.created_at,
            }
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.get("/pending-registrations", response_model=List[PendingRegistrationOut])
async def get_pending_registrations(
    _admin: User = Depends(require_admin),
):
    """Return all pending user registration requests."""
    def _sync_work():
        db = SessionLocal()
        try:
            regs = (
                db.query(RegistrationRequest)
                .filter(RegistrationRequest.status == RegistrationStatus.pending)
                .order_by(RegistrationRequest.requested_at.desc())
                .all()
            )
            out = []
            for r in regs:
                out.append({
                    "id": r.id,
                    "username": r.username,
                    "email": r.email,
                    "contact_email": r.contact_email,
                    "name": r.name,
                    "account": r.account,
                    "status": r.status.value,
                    "requested_at": r.requested_at,
                })
            return out
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.post("/approve/{request_id}", response_model=MessageResponse)
async def approve_registration(
    request_id: UUID,
    _admin: User = Depends(require_admin),
):
    """Approve a pending registration and create the user account."""
    def _sync_work():
        db = SessionLocal()
        try:
            req = db.query(RegistrationRequest).filter(RegistrationRequest.id == request_id).first()
            if not req:
                raise HTTPException(status_code=404, detail="Registration request not found")
            if req.status != RegistrationStatus.pending:
                raise HTTPException(status_code=400, detail="Request already processed")

            # Prevent duplicates by username/email/contact_email
            existing = (
                db.query(User)
                .filter(
                    (User.username == req.username) | (User.email == req.email) | (User.contact_email == req.contact_email)
                )
                .first()
            )
            if existing:
                raise HTTPException(status_code=400, detail="A user with same username/email/contact already exists")

            user = User(
                username=req.username,
                email=req.email,
                contact_email=req.contact_email,
                name=req.name,
                account=req.account,
                hashed_password=req.hashed_password,
                role=UserRole.user,
                is_active=True,
            )
            db.add(user)

            req.status = RegistrationStatus.approved
            req.resolved_at = datetime.now(timezone.utc)
            db.commit()

            return {"message": f"User '{user.username}' created and registration approved."}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.post("/reject/{request_id}", response_model=MessageResponse)
async def reject_registration(
    request_id: UUID,
    _admin: User = Depends(require_admin),
):
    """Reject a pending registration request."""
    def _sync_work():
        db = SessionLocal()
        try:
            req = db.query(RegistrationRequest).filter(RegistrationRequest.id == request_id).first()
            if not req:
                raise HTTPException(status_code=404, detail="Registration request not found")
            if req.status != RegistrationStatus.pending:
                raise HTTPException(status_code=400, detail="Request already processed")

            req.status = RegistrationStatus.rejected
            req.resolved_at = datetime.now(timezone.utc)
            db.commit()

            return {"message": "Registration request rejected."}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@router.get("/users", response_model=AdminUsersPaginatedOut)
async def list_users(
    page: int = 1,
    page_size: int = 50,
    search: str | None = None,
    _admin: User = Depends(require_admin),
):
    """List all user accounts for admin with server-side pagination and search."""

    def _sync_work():
        db = SessionLocal()
        try:
            q = db.query(User)

            if search:
                search_term = f"%{search}%"
                q = q.filter(
                    or_(
                        User.name.ilike(search_term),
                        User.username.ilike(search_term),
                        User.email.ilike(search_term),
                    )
                )

            total_count = q.count()
            users = (
                q.order_by(User.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            items = []
            for u in users:
                items.append({
                    "id": u.id,
                    "username": u.username,
                    "email": u.email,
                    "contact_email": u.contact_email,
                    "name": u.name,
                    "account": u.account,
                    "role": u.role.value if getattr(u, 'role', None) else None,
                    "is_active": u.is_active,
                    "created_at": u.created_at,
                })
            return {"items": items, "total_count": total_count}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


# ---------- Excel Import Endpoints ---------- #


@router.post("/assessments/import")
async def import_assessment_excel(
    file: UploadFile = File(...),
    _admin: User = Depends(require_admin),
):
    """Upload an Excel file (.xlsx/.xls), parse and validate rows, and store an import preview.

    Returns: { import_id, preview, errors }
    """
    # Basic filename/type checks
    filename = file.filename or "upload.xlsx"
    if not filename.lower().endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Only .xlsx/.xls files are accepted")

    try:
        data = await file.read()
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to read uploaded file")

    from db.async_helpers import run_db_sync

    def _sync_work(data_bytes: bytes, filename_local: str, uploader_id: UUID):
        from io import BytesIO as _BytesIO
        try:
            from openpyxl import load_workbook as _load_workbook
        except Exception:
            raise HTTPException(status_code=500, detail="openpyxl is required on the server")

        try:
            wb = _load_workbook(_BytesIO(data_bytes), data_only=True)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to parse Excel file: {e}")

        db = SessionLocal()
        try:
            # Create import record
            imp = ImportedAssessment(title=filename_local, uploader_id=uploader_id, status=ImportStatus.uploaded)
            db.add(imp)
            db.flush()

            sections = []
            total_q = 0

            for ws in wb.worksheets:
                rows = list(ws.iter_rows(values_only=True))
                if not rows:
                    continue

                header_raw = [str(h).strip() if h is not None else "" for h in rows[0]]

                def _norm(h: str) -> str:
                    s = h.strip().lower()
                    s = re.sub(r"[^a-z0-9_\s-]", "", s)
                    s = re.sub(r"[\s-]+", "_", s)
                    return s

                header_norm = [_norm(h) for h in header_raw]
                header_map = {name: i for i, name in enumerate(header_norm) if name}

                def find_col(keys: list[str]):
                    for k in keys:
                        kn = _norm(k)
                        if kn in header_map:
                            return header_map[kn]
                    return None

                type_idx = find_col(["type", "question_type", "question type", "qtype"])
                question_idx = find_col(["question", "question_text", "question text", "qtext"])
                topic_idx = find_col(["topic"]) 
                difficulty_idx = find_col(["difficulty", "level"])
                correct_idx = find_col(["correct_options", "correct options", "correct answer", "correct", "answer"])
                reference_idx = find_col(["reference_answer", "reference answer", "reference"])

                # detect option columns mapped to letters a-d
                option_map: dict[str, int] = {}
                for i, hn in enumerate(header_norm):
                    if not hn:
                        continue
                    m = re.match(r'^(?:option|choice)[_\s-]*([abcd])$', hn)
                    if m:
                        option_map[m.group(1)] = i
                        continue
                    if hn in ("a", "b", "c", "d"):
                        option_map[hn] = i
                        continue
                    m2 = re.match(r'^opt[_\s-]*([1-4])$', hn)
                    if m2:
                        idx = int(m2.group(1))
                        option_map["abcd"[idx - 1]] = i

                section_count = 0
                for rnum, row in enumerate(rows[1:], start=2):
                    def _get(idx):
                        return row[idx] if (idx is not None and idx < len(row)) else None

                    qtype_raw = _get(type_idx)
                    qtext = _get(question_idx)
                    topic = _get(topic_idx)
                    diff = _get(difficulty_idx)
                    correct = _get(correct_idx)
                    reference = _get(reference_idx)

                    opts: list[str] = []
                    for letter in ["a", "b", "c", "d"]:
                        if letter in option_map:
                            oi = option_map[letter]
                            if oi < len(row) and row[oi] is not None and str(row[oi]).strip() != "":
                                opts.append(str(row[oi]))

                    if not qtext or str(qtext).strip() == "":
                        continue

                    qtype_val = None
                    if qtype_raw is not None:
                        qt = str(qtype_raw).strip().lower()
                        if qt in ("single_mcq", "single mcq", "single", "mcq"):
                            qtype_val = "single_mcq"
                        elif qt in ("multi_mcq", "multi mcq", "multi", "multiple", "multiple choice"):
                            qtype_val = "multi_mcq"
                        elif qt in ("text", "short", "descriptive"):
                            qtype_val = "text"
                        elif qt in ("coding", "code"):
                            qtype_val = "coding"
                        else:
                            qtype_val = str(qtype_raw)
                    else:
                        qtype_val = None

                    correct_list = None
                    if correct is not None and str(correct).strip() != "":
                        raw = str(correct).strip()
                        parts = [p for p in re.split(r"[|,;\\s]+", raw) if p]
                        parsed: list[str] = []
                        for p in parts:
                            pstr = p.strip()
                            if len(pstr) == 1 and pstr.isalpha():
                                parsed.append(pstr.upper())
                            else:
                                parsed.append(pstr)
                        correct_list = parsed

                    iq = ImportedQuestion(
                        imported_assessment_id=imp.id,
                        section_name=ws.title,
                        question_type=qtype_val,
                        question_text=str(qtext) if qtext is not None else "",
                        reference_answer=(str(reference) if reference is not None and str(reference).strip() != "" else None),
                        options=opts or None,
                        correct_answers=(correct_list if correct_list is not None else None),
                        topic=str(topic) if topic is not None else None,
                        difficulty=str(diff) if diff is not None else None,
                        row_index=rnum,
                        validated=True,
                        errors=None,
                    )
                    db.add(iq)
                    section_count += 1
                    total_q += 1

                sections.append({"name": ws.title, "count": section_count})

            preview = {"sections": sections, "total_questions": total_q}
            imp.preview = preview
            imp.meta = {"errors_count": 0}
            imp.status = ImportStatus.uploaded
            db.commit()

            return {"import_id": str(imp.id), "preview": preview, "errors": []}
        finally:
            db.close()

    result = await run_db_sync(_sync_work, data, filename, _admin.id)
    return result


class CreateFromImportIn(BaseModel):
    import_id: UUID
    title: str
    description: str | None = ""
    duration: int = 60
    negative_marking: bool = False
    batch_ids: list[UUID] = []
    start_time: str | None = None
    end_time: str | None = None


@router.post("/assessments/create-from-import")
async def create_assessment_from_import(
    body: CreateFromImportIn,
    _admin: User = Depends(require_admin),
):
    """Create an assessment from a previously uploaded import (by id).

    The import must contain at least one validated question. Invalid rows are skipped.
    """

    def _sync_work():
        db = SessionLocal()
        try:
            imp = db.query(ImportedAssessment).filter(ImportedAssessment.id == body.import_id).first()
            if not imp:
                raise HTTPException(status_code=404, detail="Import not found")

            imported_qs = db.query(ImportedQuestion).filter(ImportedQuestion.imported_assessment_id == imp.id).all()
            validated = [q for q in imported_qs if q.validated]
            if not validated:
                raise HTTPException(status_code=400, detail="No valid questions in import to create assessment")

            # parse optional start/end times and create assessment
            from datetime import datetime, timezone

            def _parse_to_utc_naive(value: str) -> datetime:
                raw = value.strip()
                if raw.endswith("Z"):
                    raw = raw[:-1] + "+00:00"
                dt = datetime.fromisoformat(raw)
                if dt.tzinfo is None:
                    return dt
                return dt.astimezone(timezone.utc).replace(tzinfo=None)

            start_dt = None
            end_dt = None
            if body.start_time:
                try:
                    start_dt = _parse_to_utc_naive(body.start_time)
                except Exception:
                    raise HTTPException(status_code=400, detail="Invalid start_time format (use ISO format)")
            if body.end_time:
                try:
                    end_dt = _parse_to_utc_naive(body.end_time)
                except Exception:
                    raise HTTPException(status_code=400, detail="Invalid end_time format (use ISO format)")
            if start_dt and end_dt and end_dt <= start_dt:
                raise HTTPException(status_code=400, detail="end_time must be after start_time")

            assessment = Assessment(
                title=body.title.strip(),
                description=(body.description.strip() if body.description else None),
                duration=body.duration,
                negative_marking=body.negative_marking,
                start_time=start_dt,
                end_time=end_dt,
                created_by=_admin.id,
            )
            db.add(assessment)
            db.flush()

            created_question_ids = []
            topic_agg: dict[tuple[str, str, str], int] = {}

            for iq in validated:
                # map or create topic by name
                topic_obj = None
                if iq.topic:
                    topic_name = iq.topic.strip()
                    if topic_name:
                        # if a matching global Topic exists, link to it; do NOT create new global topics for imports
                        topic_obj = db.query(Topic).filter(func.lower(Topic.name) == topic_name.lower()).first()

                q_type = None
                try:
                    q_type = QuestionType(iq.question_type) if iq.question_type else QuestionType.text
                except Exception:
                    q_type = QuestionType.text

                diff = None
                try:
                    diff = Difficulty(iq.difficulty) if iq.difficulty else Difficulty.medium
                except Exception:
                    diff = Difficulty.medium

                # create a per-assessment question item (do NOT write to global Question/QuestionOption)
                item_options = None
                if iq.options:
                    correct_list = iq.correct_answers or []
                    letter_set = {str(c).strip().upper() for c in correct_list if isinstance(c, str) and len(str(c).strip()) == 1 and str(c).strip().isalpha()}
                    text_set = {str(c).strip().lower() for c in correct_list if not (isinstance(c, str) and len(str(c).strip()) == 1 and str(c).strip().isalpha())}
                    item_options = []
                    from uuid import uuid4
                    for idx, opt_text in enumerate(iq.options):
                        letter = chr(ord('A') + idx)
                        is_correct = False
                        if letter_set:
                            is_correct = (letter in letter_set)
                        elif text_set:
                            is_correct = (str(opt_text).strip().lower() in text_set)
                        item_options.append({"id": str(uuid4()), "option_text": str(opt_text), "is_correct": bool(is_correct)})

                item = AssessmentQuestionItem(
                    assessment_id=assessment.id,
                    question_type=(q_type.value if q_type else None),
                    question_text=iq.question_text,
                    reference_answer=(iq.reference_answer if getattr(iq, "reference_answer", None) else None),
                    options=(item_options if item_options is not None else None),
                    correct_answers=(iq.correct_answers if getattr(iq, "correct_answers", None) else None),
                    topic=(topic_obj.name if topic_obj else (iq.topic.strip() if iq.topic else None)),
                    difficulty=(diff.value if diff else None),
                    default_code=None,
                    test_cases=None,
                )
                db.add(item)
                db.flush()

                # link the assessment to this new per-assessment item
                db.add(AssessmentQuestion(assessment_id=assessment.id, assessment_item_id=item.id))
                db.add(AssessmentQuestionSection(assessment_id=assessment.id, assessment_item_id=item.id, section_name=(iq.section_name or "Imported")))

                created_question_ids.append(item.id)

                # aggregate for AssessmentTopic
                key = (str(topic_obj.id) if topic_obj else "", q_type.value if q_type else "text", diff.value if diff else "medium")
                topic_agg[key] = topic_agg.get(key, 0) + 1

            # questions have already been linked with their sections during creation

            # create AssessmentTopic records
            for k, cnt in topic_agg.items():
                topic_id_str, qtype_str, diff_str = k
                if topic_id_str:
                    try:
                        tid = UUID(topic_id_str)
                    except Exception:
                        tid = None
                else:
                    tid = None
                at = AssessmentTopic(
                    assessment_id=assessment.id,
                    topic_id=tid,
                    question_type=QuestionType(qtype_str),
                    difficulty=Difficulty(diff_str),
                    question_count=cnt,
                )
                db.add(at)

            # create assignments
            batch_names: list[str] = []
            if body.batch_ids:
                for bid in body.batch_ids:
                    b = db.query(Batch).filter(Batch.id == bid).first()
                    if b:
                        db.add(Assignment(assessment_id=assessment.id, batch_id=bid))
                        batch_names.append(b.name)

            # finalize
            imp.status = ImportStatus.used
            db.commit()

            return {
                "id": assessment.id,
                "title": assessment.title,
                "description": assessment.description,
                "duration": assessment.duration,
                "negative_marking": assessment.negative_marking,
                "total_questions": len(created_question_ids),
                "topics": [],
                "batch_names": batch_names,
                "start_time": None,
                "end_time": None,
                "created_at": assessment.created_at.isoformat(),
            }
        finally:
            db.close()

    res = await run_db_sync(_sync_work)
    return res
