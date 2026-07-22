import os
from datetime import datetime, timedelta, timezone
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core.auth import get_current_user, require_admin
from core.interview_agent import generate_opening_question, evaluate_and_generate_followup
from db.async_helpers import run_db_sync
from db.database import SessionLocal
from db.models import (
    BatchUser,
    InterviewAccessRequest,
    InterviewAccessStatus,
    InterviewAssignment,
    InterviewAssignmentStatus,
    InterviewRequestType,
    InterviewResponseEvaluation,
    InterviewSession,
    InterviewSessionStatus,
    InterviewTemplate,
    User,
)
from api.timezone_helper import as_utc_aware, to_utc_iso

user_router = APIRouter(prefix="/interviews", tags=["interviews"])
admin_router = APIRouter(prefix="/admin/interviews", tags=["admin-interviews"])

INTERVIEW_REQUEST_EXPIRY_DAYS = int(os.getenv("INTERVIEW_REQUEST_EXPIRY_DAYS", "2"))


class MessageResponse(BaseModel):
    message: str


class InterviewTemplateIn(BaseModel):
    title: str
    description: str | None = None
    role: str
    experience_level: str = "mid"
    difficulty: str = "intermediate"
    focus_areas: list[str] = []
    duration_minutes: int = 60
    question_count: int = 5
    default_questions_or_topics: list[str] = []
    system_prompt: str | None = None
    evaluation_rubric: dict | None = None
    max_pauses_allowed: int = 3


class InterviewTemplateUpdateIn(BaseModel):
    title: str | None = None
    description: str | None = None
    role: str | None = None
    experience_level: str | None = None
    difficulty: str | None = None
    focus_areas: list[str] | None = None
    duration_minutes: int | None = None
    question_count: int | None = None
    default_questions_or_topics: list[str] | None = None
    system_prompt: str | None = None
    evaluation_rubric: dict | None = None
    max_pauses_allowed: int | None = None
    is_active: bool | None = None


class InterviewTemplateOut(BaseModel):
    id: UUID
    title: str
    description: str | None
    role: str
    experience_level: str
    difficulty: str
    focus_areas: list[str]
    duration_minutes: int
    question_count: int
    default_questions_or_topics: list[str]
    is_active: bool
    is_archived: bool
    max_pauses_allowed: int
    created_at: datetime


class InterviewAccessRequestIn(BaseModel):
    template_id: UUID
    reason: str | None = None


class InterviewAccessRequestOut(BaseModel):
    id: UUID
    user_id: UUID
    template_id: UUID
    template_title: str
    user_name: str
    username: str
    status: str
    request_type: str
    reason: str | None
    requested_at: datetime
    reviewed_at: datetime | None
    expires_at: datetime | None


class ApproveInterviewAccessIn(BaseModel):
    days: int = 14


class AssignUsersIn(BaseModel):
    template_id: UUID
    user_ids: list[UUID]
    days: int = 14


class AssignBatchIn(BaseModel):
    template_id: UUID
    batch_id: UUID
    days: int = 14


class InterviewStartIn(BaseModel):
    template_id: UUID


class InterviewSessionOut(BaseModel):
    id: UUID
    template_id: UUID
    template_title: str
    status: str
    attempt_number: int
    pause_count: int
    max_pauses_allowed: int
    started_at: datetime | None
    completed_at: datetime | None
    total_score: float | None


class InterviewMessageIn(BaseModel):
    response_text: str


class InterviewMessageOut(BaseModel):
    session_id: UUID
    ai_message: str
    score: float | None
    feedback: str | None
    pause_count: int
    max_pauses_allowed: int


class InterviewInterruptOut(BaseModel):
    message: str
    status: str
    pause_count: int
    disconnect_count: int
    max_pauses_allowed: int


class EvaluationItemOut(BaseModel):
    turn_index: int
    user_response: str | None
    score: float | None
    focus_area: str | None
    strengths: list[str]
    improvements: list[str]
    feedback: str | None


class TopicScoreOut(BaseModel):
    topic: str
    avg_score: float
    turns: int


class InterviewSessionResultOut(BaseModel):
    id: UUID
    template_id: UUID
    template_title: str
    status: str
    attempt_number: int
    started_at: datetime | None
    completed_at: datetime | None
    pause_count: int
    disconnect_count: int
    total_score: float | None
    summary: str | None
    transcript: list | None
    feedback: dict | None
    evaluations: list[EvaluationItemOut]
    topic_scores: list[TopicScoreOut]


class DashboardCountsOut(BaseModel):
    interviews_to_attend: int
    interviews_in_progress: int


def _active_statuses() -> list[InterviewSessionStatus]:
    return [
        InterviewSessionStatus.started,
        InterviewSessionStatus.in_progress,
        InterviewSessionStatus.paused,
    ]


# ---------- Admin APIs ---------- #


@admin_router.post("/templates", response_model=InterviewTemplateOut)
async def create_template(
    payload: InterviewTemplateIn,
    admin: User = Depends(require_admin),
):
    def _sync_work():
        db = SessionLocal()
        try:
            template = InterviewTemplate(
                admin_id=admin.id,
                title=payload.title.strip(),
                description=(payload.description.strip() if payload.description else None),
                role=payload.role.strip(),
                experience_level=payload.experience_level,
                difficulty=payload.difficulty,
                focus_areas=payload.focus_areas or [],
                duration_minutes=max(10, min(180, int(payload.duration_minutes))),
                question_count=max(1, min(20, int(payload.question_count))),
                default_questions_or_topics=payload.default_questions_or_topics or [],
                system_prompt=payload.system_prompt,
                evaluation_rubric=payload.evaluation_rubric or {},
                max_pauses_allowed=max(0, min(10, int(payload.max_pauses_allowed))),
                is_active=True,
            )
            db.add(template)
            db.commit()
            db.refresh(template)
            return template
        finally:
            db.close()

    t = await run_db_sync(_sync_work)
    return InterviewTemplateOut(
        id=t.id,
        title=t.title,
        description=t.description,
        role=t.role,
        experience_level=t.experience_level,
        difficulty=t.difficulty,
        focus_areas=t.focus_areas or [],
        duration_minutes=t.duration_minutes,
        question_count=t.question_count,
        default_questions_or_topics=t.default_questions_or_topics or [],
        is_active=t.is_active,
        is_archived=t.is_archived,
        max_pauses_allowed=t.max_pauses_allowed,
        created_at=t.created_at,
    )


@admin_router.get("/templates", response_model=List[InterviewTemplateOut])
async def list_templates(
    _admin: User = Depends(require_admin),
):
    def _sync_work():
        db = SessionLocal()
        try:
            rows = db.query(InterviewTemplate).order_by(InterviewTemplate.created_at.desc()).all()
            out = []
            for t in rows:
                out.append(
                    {
                        "id": t.id,
                        "title": t.title,
                        "description": t.description,
                        "role": t.role,
                        "experience_level": t.experience_level,
                        "difficulty": t.difficulty,
                        "focus_areas": t.focus_areas or [],
                        "duration_minutes": t.duration_minutes,
                        "question_count": t.question_count,
                        "default_questions_or_topics": t.default_questions_or_topics or [],
                        "is_active": t.is_active,
                        "is_archived": t.is_archived,
                        "max_pauses_allowed": t.max_pauses_allowed,
                        "created_at": t.created_at,
                    }
                )
            return out
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@admin_router.patch("/templates/{template_id}", response_model=MessageResponse)
async def update_template(
    template_id: UUID,
    payload: InterviewTemplateUpdateIn,
    _admin: User = Depends(require_admin),
):
    def _sync_work():
        db = SessionLocal()
        try:
            t = db.query(InterviewTemplate).filter(InterviewTemplate.id == template_id).first()
            if not t:
                raise HTTPException(status_code=404, detail="Template not found")

            data = payload.model_dump(exclude_unset=True)
            for key, value in data.items():
                if key == "max_pauses_allowed" and value is not None:
                    value = max(0, min(10, int(value)))
                if key == "duration_minutes" and value is not None:
                    value = max(10, min(180, int(value)))
                if key == "question_count" and value is not None:
                    value = max(1, min(20, int(value)))
                setattr(t, key, value)
            t.updated_at = datetime.now(timezone.utc)
            db.commit()
            return {"message": "Template updated successfully"}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@admin_router.post("/templates/{template_id}/archive", response_model=MessageResponse)
async def archive_template(
    template_id: UUID,
    _admin: User = Depends(require_admin),
):
    def _sync_work():
        db = SessionLocal()
        try:
            t = db.query(InterviewTemplate).filter(InterviewTemplate.id == template_id).first()
            if not t:
                raise HTTPException(status_code=404, detail="Template not found")
            t.is_archived = True
            t.is_active = False
            t.archived_at = datetime.now(timezone.utc)
            t.updated_at = datetime.now(timezone.utc)
            db.commit()
            return {"message": "Template archived"}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@admin_router.post("/templates/{template_id}/unarchive", response_model=MessageResponse)
async def unarchive_template(
    template_id: UUID,
    _admin: User = Depends(require_admin),
):
    def _sync_work():
        db = SessionLocal()
        try:
            t = db.query(InterviewTemplate).filter(InterviewTemplate.id == template_id).first()
            if not t:
                raise HTTPException(status_code=404, detail="Template not found")
            t.is_archived = False
            t.is_active = True
            t.updated_at = datetime.now(timezone.utc)
            db.commit()
            return {"message": "Template unarchived"}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@admin_router.get("/access-requests", response_model=List[InterviewAccessRequestOut])
async def get_access_requests(
    status: str = Query("pending"),
    _admin: User = Depends(require_admin),
):
    def _sync_work():
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            # Auto-expire pending requests older than the configured window.
            stale_pending = (
                db.query(InterviewAccessRequest)
                .filter(
                    InterviewAccessRequest.status == InterviewAccessStatus.pending,
                    InterviewAccessRequest.requested_at < now - timedelta(days=INTERVIEW_REQUEST_EXPIRY_DAYS),
                )
                .all()
            )
            for req in stale_pending:
                req.status = InterviewAccessStatus.expired
            if stale_pending:
                db.commit()

            # Auto-expire approved requests past their expires_at
            stale_approved = (
                db.query(InterviewAccessRequest)
                .filter(
                    InterviewAccessRequest.status == InterviewAccessStatus.approved,
                    InterviewAccessRequest.expires_at < now,
                )
                .all()
            )
            for req in stale_approved:
                req.status = InterviewAccessStatus.expired
            if stale_approved:
                db.commit()

            q = (
                db.query(InterviewAccessRequest, User, InterviewTemplate)
                .join(User, InterviewAccessRequest.user_id == User.id)
                .join(InterviewTemplate, InterviewAccessRequest.template_id == InterviewTemplate.id)
            )
            if status != "all":
                try:
                    s = InterviewAccessStatus(status)
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid status filter")
                q = q.filter(InterviewAccessRequest.status == s)
            rows = q.order_by(InterviewAccessRequest.requested_at.desc()).all()
            out = []
            for req, user, template in rows:
                out.append(
                    {
                        "id": req.id,
                        "user_id": req.user_id,
                        "template_id": req.template_id,
                        "template_title": template.title,
                        "user_name": user.name,
                        "username": user.username,
                        "status": req.status.value,
                        "request_type": req.request_type.value,
                        "reason": req.reason,
                        "requested_at": req.requested_at,
                        "reviewed_at": req.reviewed_at,
                        "expires_at": req.expires_at,
                    }
                )
            return out
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@admin_router.post("/access-requests/{request_id}/approve", response_model=MessageResponse)
async def approve_access_request(
    request_id: UUID,
    payload: ApproveInterviewAccessIn,
    admin: User = Depends(require_admin),
):
    def _sync_work():
        db = SessionLocal()
        try:
            req = db.query(InterviewAccessRequest).filter(InterviewAccessRequest.id == request_id).first()
            if not req:
                raise HTTPException(status_code=404, detail="Request not found")
            if req.status != InterviewAccessStatus.pending:
                raise HTTPException(status_code=400, detail="Request already processed")

            days = max(1, min(30, int(payload.days)))
            now = datetime.now(timezone.utc)
            req.status = InterviewAccessStatus.approved
            req.admin_id = admin.id
            req.reviewed_at = now
            req.approved_at = now
            req.expires_at = now + timedelta(days=days)
            db.commit()
            return {"message": "Interview access approved"}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@admin_router.post("/access-requests/{request_id}/reject", response_model=MessageResponse)
async def reject_access_request(
    request_id: UUID,
    admin: User = Depends(require_admin),
):
    def _sync_work():
        db = SessionLocal()
        try:
            req = db.query(InterviewAccessRequest).filter(InterviewAccessRequest.id == request_id).first()
            if not req:
                raise HTTPException(status_code=404, detail="Request not found")
            if req.status != InterviewAccessStatus.pending:
                raise HTTPException(status_code=400, detail="Request already processed")
            req.status = InterviewAccessStatus.rejected
            req.admin_id = admin.id
            req.reviewed_at = datetime.now(timezone.utc)
            db.commit()
            return {"message": "Interview access rejected"}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@admin_router.post("/assignments/users", response_model=MessageResponse)
async def assign_to_users(
    payload: AssignUsersIn,
    admin: User = Depends(require_admin),
):
    def _sync_work():
        db = SessionLocal()
        try:
            template = db.query(InterviewTemplate).filter(InterviewTemplate.id == payload.template_id).first()
            if not template:
                raise HTTPException(status_code=404, detail="Template not found")
            if not payload.user_ids:
                raise HTTPException(status_code=400, detail="No users selected")

            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(days=max(1, min(30, int(payload.days))))
            assigned = 0
            skipped = 0
            for user_id in payload.user_ids:
                # Check if user already has an active (non-expired) approved access
                existing_approved = (
                    db.query(InterviewAccessRequest)
                    .filter(
                        InterviewAccessRequest.user_id == user_id,
                        InterviewAccessRequest.template_id == payload.template_id,
                        InterviewAccessRequest.status == InterviewAccessStatus.approved,
                        InterviewAccessRequest.expires_at > now,
                    )
                    .first()
                )
                if existing_approved:
                    # User already has a valid approved access — check if they can still attempt
                    active_or_completed = (
                        db.query(InterviewSession)
                        .filter(
                            InterviewSession.user_id == user_id,
                            InterviewSession.template_id == payload.template_id,
                            InterviewSession.status.in_([
                                InterviewSessionStatus.started,
                                InterviewSessionStatus.in_progress,
                                InterviewSessionStatus.paused,
                            ]),
                        )
                        .first()
                    )
                    if active_or_completed:
                        # User has an active session, skip
                        skipped += 1
                        continue
                    # Check if they completed but still have valid access (no need for new grant)
                    skipped += 1
                    continue

                # Check pending request — skip
                existing_pending = (
                    db.query(InterviewAccessRequest)
                    .filter(
                        InterviewAccessRequest.user_id == user_id,
                        InterviewAccessRequest.template_id == payload.template_id,
                        InterviewAccessRequest.status == InterviewAccessStatus.pending,
                    )
                    .first()
                )
                if existing_pending:
                    # Approve the pending request instead
                    existing_pending.status = InterviewAccessStatus.approved
                    existing_pending.admin_id = admin.id
                    existing_pending.reviewed_at = now
                    existing_pending.approved_at = now
                    existing_pending.expires_at = expires_at
                    assigned += 1
                    continue

                # User has no active access — grant new access (works for first-timers and retries)
                req = InterviewAccessRequest(
                    user_id=user_id,
                    template_id=payload.template_id,
                    request_type=InterviewRequestType.initial,
                    status=InterviewAccessStatus.approved,
                    requested_at=now,
                    reviewed_at=now,
                    approved_at=now,
                    admin_id=admin.id,
                    expires_at=expires_at,
                )
                db.add(req)
                db.add(
                    InterviewAssignment(
                        template_id=payload.template_id,
                        assigned_by_admin_id=admin.id,
                        assigned_to_user_id=user_id,
                        status=InterviewAssignmentStatus.active,
                        deadline_at=expires_at,
                    )
                )
                assigned += 1
            db.commit()
            return {"message": f"Assigned template to {assigned} user(s). {skipped} skipped (already have access)."}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@admin_router.post("/assignments/batches", response_model=MessageResponse)
async def assign_to_batch(
    payload: AssignBatchIn,
    admin: User = Depends(require_admin),
):
    def _sync_work():
        db = SessionLocal()
        try:
            user_ids = [row.user_id for row in db.query(BatchUser).filter(BatchUser.batch_id == payload.batch_id).all()]
            if not user_ids:
                raise HTTPException(status_code=404, detail="No users found in selected batch")
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(days=max(1, min(30, int(payload.days))))
            assigned = 0
            skipped = 0
            for user_id in user_ids:
                # Check if user already has an active (non-expired) approved access
                existing_approved = (
                    db.query(InterviewAccessRequest)
                    .filter(
                        InterviewAccessRequest.user_id == user_id,
                        InterviewAccessRequest.template_id == payload.template_id,
                        InterviewAccessRequest.status == InterviewAccessStatus.approved,
                        InterviewAccessRequest.expires_at > now,
                    )
                    .first()
                )
                if existing_approved:
                    # User already has valid approved access — check if they have an active session
                    active_session = (
                        db.query(InterviewSession)
                        .filter(
                            InterviewSession.user_id == user_id,
                            InterviewSession.template_id == payload.template_id,
                            InterviewSession.status.in_([
                                InterviewSessionStatus.started,
                                InterviewSessionStatus.in_progress,
                                InterviewSessionStatus.paused,
                            ]),
                        )
                        .first()
                    )
                    if active_session:
                        skipped += 1
                        continue
                    # Has valid access but no active session — still has an attempt available, skip
                    skipped += 1
                    continue

                # Check pending request — approve it
                existing_pending = (
                    db.query(InterviewAccessRequest)
                    .filter(
                        InterviewAccessRequest.user_id == user_id,
                        InterviewAccessRequest.template_id == payload.template_id,
                        InterviewAccessRequest.status == InterviewAccessStatus.pending,
                    )
                    .first()
                )
                if existing_pending:
                    existing_pending.status = InterviewAccessStatus.approved
                    existing_pending.admin_id = admin.id
                    existing_pending.reviewed_at = now
                    existing_pending.approved_at = now
                    existing_pending.expires_at = expires_at
                    assigned += 1
                    continue

                # User has no active access — grant new access (works for first-timers and retries)
                req = InterviewAccessRequest(
                    user_id=user_id,
                    template_id=payload.template_id,
                    request_type=InterviewRequestType.initial,
                    status=InterviewAccessStatus.approved,
                    requested_at=now,
                    reviewed_at=now,
                    approved_at=now,
                    admin_id=admin.id,
                    expires_at=expires_at,
                )
                db.add(req)
                assigned += 1

            db.add(
                InterviewAssignment(
                    template_id=payload.template_id,
                    assigned_by_admin_id=admin.id,
                    assigned_to_batch_id=payload.batch_id,
                    status=InterviewAssignmentStatus.active,
                    deadline_at=expires_at,
                )
            )
            db.commit()
            return {"message": f"Assigned template to batch ({assigned} access grants, {skipped} skipped)."}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@admin_router.post("/results/{session_id}/reenable", response_model=MessageResponse)
async def reenable_missed_session(
    session_id: UUID,
    _admin: User = Depends(require_admin),
):
    """Re-enable a missed interview session so the user can attempt again."""
    def _sync_work():
        db = SessionLocal()
        try:
            session = db.query(InterviewSession).filter(InterviewSession.id == session_id).first()
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            if session.status != InterviewSessionStatus.missed:
                raise HTTPException(status_code=400, detail="Only missed sessions can be re-enabled")
            # Delete the missed session so user can start fresh
            db.delete(session)
            db.commit()
            return {"message": "Session removed. User can now start a new interview for this template."}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


class InterviewResultListOut(BaseModel):
    id: UUID
    template_id: UUID
    template_title: str
    user_id: UUID
    user_name: str
    username: str
    status: str
    attempt_number: int
    pause_count: int
    max_pauses_allowed: int
    started_at: datetime | None
    completed_at: datetime | None
    total_score: float | None


class InterviewResultsPaginatedOut(BaseModel):
    items: List[InterviewResultListOut]
    total_count: int


@admin_router.get("/results", response_model=InterviewResultsPaginatedOut)
async def get_results(
    template_id: UUID | None = None,
    user_id: UUID | None = None,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    page_size: int = 50,
    _admin: User = Depends(require_admin),
):
    def _sync_work():
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)

            # Special case: "assigned" status shows users with approved access but no session
            if status == "assigned":
                q = (
                    db.query(InterviewAccessRequest, InterviewTemplate, User)
                    .join(InterviewTemplate, InterviewAccessRequest.template_id == InterviewTemplate.id)
                    .join(User, InterviewAccessRequest.user_id == User.id)
                    .filter(
                        InterviewAccessRequest.status == InterviewAccessStatus.approved,
                        InterviewAccessRequest.expires_at > now,
                    )
                )
                if template_id:
                    q = q.filter(InterviewAccessRequest.template_id == template_id)
                if user_id:
                    q = q.filter(InterviewAccessRequest.user_id == user_id)
                if date_from:
                    try:
                        dt_from = as_utc_aware(datetime.fromisoformat(date_from))
                        q = q.filter(InterviewAccessRequest.approved_at >= dt_from)
                    except ValueError:
                        pass
                if date_to:
                    try:
                        dt_to = as_utc_aware(datetime.fromisoformat(date_to))
                        dt_to = dt_to.replace(hour=23, minute=59, second=59)
                        q = q.filter(InterviewAccessRequest.approved_at <= dt_to)
                    except ValueError:
                        pass
                rows = q.order_by(InterviewAccessRequest.approved_at.desc()).all()
                out = []
                for req, t, u in rows:
                    # Check if user has any session for this template
                    has_session = (
                        db.query(InterviewSession)
                        .filter(
                            InterviewSession.user_id == u.id,
                            InterviewSession.template_id == t.id,
                            InterviewSession.status.in_([
                                InterviewSessionStatus.started,
                                InterviewSessionStatus.in_progress,
                                InterviewSessionStatus.paused,
                                InterviewSessionStatus.completed,
                            ]),
                        )
                        .first()
                    )
                    if not has_session:
                        out.append(
                            {
                                "id": req.id,
                                "template_id": t.id,
                                "template_title": t.title,
                                "user_id": u.id,
                                "user_name": u.name or u.username,
                                "username": u.username,
                                "status": "assigned",
                                "attempt_number": 0,
                                "pause_count": 0,
                                "max_pauses_allowed": t.max_pauses_allowed,
                                "started_at": None,
                                "completed_at": None,
                                "total_score": None,
                            }
                        )
                total_count = len(out)
                start = (page - 1) * page_size
                end = start + page_size
                return InterviewResultsPaginatedOut(items=out[start:end], total_count=total_count)

            q = (
                db.query(InterviewSession, InterviewTemplate, User)
                .join(InterviewTemplate, InterviewSession.template_id == InterviewTemplate.id)
                .join(User, InterviewSession.user_id == User.id)
            )
            if template_id:
                q = q.filter(InterviewSession.template_id == template_id)
            if user_id:
                q = q.filter(InterviewSession.user_id == user_id)
            if status:
                try:
                    s = InterviewSessionStatus(status)
                    q = q.filter(InterviewSession.status == s)
                except ValueError:
                    pass
            if date_from:
                try:
                    dt_from = as_utc_aware(datetime.fromisoformat(date_from))
                    q = q.filter(InterviewSession.created_at >= dt_from)
                except ValueError:
                    pass
            if date_to:
                try:
                    dt_to = as_utc_aware(datetime.fromisoformat(date_to))
                    dt_to = dt_to.replace(hour=23, minute=59, second=59)
                    q = q.filter(InterviewSession.created_at <= dt_to)
                except ValueError:
                    pass
            rows = q.order_by(InterviewSession.created_at.desc()).all()
            out = []
            for s, t, u in rows:
                out.append(
                    {
                        "id": s.id,
                        "template_id": s.template_id,
                        "template_title": t.title,
                        "user_id": u.id,
                        "user_name": u.name or u.username,
                        "username": u.username,
                        "status": s.status.value,
                        "attempt_number": s.attempt_number,
                        "pause_count": s.pause_count,
                        "max_pauses_allowed": s.max_pauses_allowed_snapshot,
                        "started_at": s.started_at,
                        "completed_at": s.completed_at,
                        "total_score": s.total_score,
                    }
                )

            # If no status filter (showing all), also include assigned users
            if not status:
                aq = (
                    db.query(InterviewAccessRequest, InterviewTemplate, User)
                    .join(InterviewTemplate, InterviewAccessRequest.template_id == InterviewTemplate.id)
                    .join(User, InterviewAccessRequest.user_id == User.id)
                    .filter(
                        InterviewAccessRequest.status == InterviewAccessStatus.approved,
                        InterviewAccessRequest.expires_at > now,
                    )
                )
                if template_id:
                    aq = aq.filter(InterviewAccessRequest.template_id == template_id)
                if user_id:
                    aq = aq.filter(InterviewAccessRequest.user_id == user_id)
                assigned_rows = aq.all()
                for req, t, u in assigned_rows:
                    has_session = (
                        db.query(InterviewSession)
                        .filter(
                            InterviewSession.user_id == u.id,
                            InterviewSession.template_id == t.id,
                            InterviewSession.status.in_([
                                InterviewSessionStatus.started,
                                InterviewSessionStatus.in_progress,
                                InterviewSessionStatus.paused,
                                InterviewSessionStatus.completed,
                            ]),
                        )
                        .first()
                    )
                    if not has_session:
                        out.append(
                            {
                                "id": req.id,
                                "template_id": t.id,
                                "template_title": t.title,
                                "user_id": u.id,
                                "user_name": u.name or u.username,
                                "username": u.username,
                                "status": "assigned",
                                "attempt_number": 0,
                                "pause_count": 0,
                                "max_pauses_allowed": t.max_pauses_allowed,
                                "started_at": None,
                                "completed_at": None,
                                "total_score": None,
                            }
                        )

            total_count = len(out)
            start = (page - 1) * page_size
            end = start + page_size
            return InterviewResultsPaginatedOut(items=out[start:end], total_count=total_count)
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@admin_router.get("/results/{session_id}", response_model=InterviewSessionResultOut)
async def get_result_detail(
    session_id: UUID,
    _admin: User = Depends(require_admin),
):
    def _sync_work():
        db = SessionLocal()
        try:
            row = (
                db.query(InterviewSession, InterviewTemplate)
                .join(InterviewTemplate, InterviewSession.template_id == InterviewTemplate.id)
                .filter(InterviewSession.id == session_id)
                .first()
            )
            if not row:
                raise HTTPException(status_code=404, detail="Session not found")
            s, t = row

            # Fetch per-turn evaluations
            evals = (
                db.query(InterviewResponseEvaluation)
                .filter(InterviewResponseEvaluation.session_id == s.id)
                .order_by(InterviewResponseEvaluation.turn_index)
                .all()
            )

            evaluations_out = []
            topic_map: dict[str, list[float]] = {}
            for ev in evals:
                ai_eval = ev.ai_evaluation or {}
                evaluations_out.append({
                    "turn_index": ev.turn_index,
                    "user_response": ev.user_response,
                    "score": ev.score,
                    "focus_area": ev.focus_area,
                    "strengths": ai_eval.get("strengths", []),
                    "improvements": ai_eval.get("improvements", []),
                    "feedback": ai_eval.get("feedback", ""),
                })
                topic = ev.focus_area or "general"
                if ev.score is not None:
                    topic_map.setdefault(topic, []).append(ev.score)

            topic_scores_out = [
                {"topic": topic, "avg_score": round(sum(scores) / len(scores), 1), "turns": len(scores)}
                for topic, scores in topic_map.items()
            ]

            return {
                "id": s.id,
                "template_id": s.template_id,
                "template_title": t.title,
                "status": s.status.value,
                "attempt_number": s.attempt_number,
                "started_at": s.started_at,
                "completed_at": s.completed_at,
                "pause_count": s.pause_count,
                "disconnect_count": s.disconnect_count,
                "total_score": s.total_score,
                "summary": s.summary,
                "transcript": s.transcript or [],
                "feedback": s.feedback or {},
                "evaluations": evaluations_out,
                "topic_scores": topic_scores_out,
            }
        finally:
            db.close()

    return await run_db_sync(_sync_work)


# ---------- User APIs ---------- #


@user_router.get("/templates", response_model=List[InterviewTemplateOut])
async def available_templates(
    _user: User = Depends(get_current_user),
):
    def _sync_work():
        db = SessionLocal()
        try:
            rows = (
                db.query(InterviewTemplate)
                .filter(InterviewTemplate.is_active.is_(True), InterviewTemplate.is_archived.is_(False))
                .order_by(InterviewTemplate.created_at.desc())
                .all()
            )
            out = []
            for t in rows:
                out.append(
                    {
                        "id": t.id,
                        "title": t.title,
                        "description": t.description,
                        "role": t.role,
                        "experience_level": t.experience_level,
                        "difficulty": t.difficulty,
                        "focus_areas": t.focus_areas or [],
                        "duration_minutes": t.duration_minutes,
                        "question_count": t.question_count,
                        "default_questions_or_topics": t.default_questions_or_topics or [],
                        "is_active": t.is_active,
                        "is_archived": t.is_archived,
                        "max_pauses_allowed": t.max_pauses_allowed,
                        "created_at": t.created_at,
                    }
                )
            return out
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@user_router.post("/request-access", response_model=MessageResponse)
async def request_access(
    payload: InterviewAccessRequestIn,
    current_user: User = Depends(get_current_user),
):
    def _sync_work():
        db = SessionLocal()
        try:
            template = db.query(InterviewTemplate).filter(InterviewTemplate.id == payload.template_id).first()
            if not template or template.is_archived:
                raise HTTPException(status_code=404, detail="Template not available")

            existing = (
                db.query(InterviewAccessRequest)
                .filter(
                    InterviewAccessRequest.user_id == current_user.id,
                    InterviewAccessRequest.template_id == payload.template_id,
                    InterviewAccessRequest.status.in_([
                        InterviewAccessStatus.pending,
                        InterviewAccessStatus.approved,
                    ]),
                )
                .first()
            )
            if existing:
                raise HTTPException(status_code=400, detail="You already have a pending/approved request for this template")

            req = InterviewAccessRequest(
                user_id=current_user.id,
                template_id=payload.template_id,
                reason=(payload.reason.strip() if payload.reason else None),
                status=InterviewAccessStatus.pending,
                request_type=InterviewRequestType.initial,
            )
            db.add(req)
            db.commit()
            return {"message": "Interview access request submitted"}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@user_router.post("/request-retry", response_model=MessageResponse)
async def request_retry(
    payload: InterviewAccessRequestIn,
    current_user: User = Depends(get_current_user),
):
    def _sync_work():
        db = SessionLocal()
        try:
            completed_exists = (
                db.query(InterviewSession)
                .filter(
                    InterviewSession.user_id == current_user.id,
                    InterviewSession.template_id == payload.template_id,
                    InterviewSession.status == InterviewSessionStatus.completed,
                )
                .first()
            )
            if not completed_exists:
                raise HTTPException(status_code=400, detail="Retry is allowed only after a completed attempt")

            existing_pending_retry = (
                db.query(InterviewAccessRequest)
                .filter(
                    InterviewAccessRequest.user_id == current_user.id,
                    InterviewAccessRequest.template_id == payload.template_id,
                    InterviewAccessRequest.status == InterviewAccessStatus.pending,
                    InterviewAccessRequest.request_type == InterviewRequestType.retry,
                )
                .first()
            )
            if existing_pending_retry:
                raise HTTPException(status_code=400, detail="You already have a pending retry request")

            req = InterviewAccessRequest(
                user_id=current_user.id,
                template_id=payload.template_id,
                reason=(payload.reason.strip() if payload.reason else None),
                status=InterviewAccessStatus.pending,
                request_type=InterviewRequestType.retry,
            )
            db.add(req)
            db.commit()
            return {"message": "Retry request submitted for admin approval"}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@user_router.get("/my-requests", response_model=List[InterviewAccessRequestOut])
async def my_requests(
    current_user: User = Depends(get_current_user),
):
    def _sync_work():
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            # Auto-expire user's own pending requests older than the configured window.
            stale = (
                db.query(InterviewAccessRequest)
                .filter(
                    InterviewAccessRequest.user_id == current_user.id,
                    InterviewAccessRequest.status == InterviewAccessStatus.pending,
                    InterviewAccessRequest.requested_at < now - timedelta(days=INTERVIEW_REQUEST_EXPIRY_DAYS),
                )
                .all()
            )
            for req in stale:
                req.status = InterviewAccessStatus.expired
            # Auto-expire approved requests past their deadline
            stale_approved = (
                db.query(InterviewAccessRequest)
                .filter(
                    InterviewAccessRequest.user_id == current_user.id,
                    InterviewAccessRequest.status == InterviewAccessStatus.approved,
                    InterviewAccessRequest.expires_at < now,
                )
                .all()
            )
            for req in stale_approved:
                req.status = InterviewAccessStatus.expired
            if stale or stale_approved:
                db.commit()

            rows = (
                db.query(InterviewAccessRequest, User, InterviewTemplate)
                .join(User, InterviewAccessRequest.user_id == User.id)
                .join(InterviewTemplate, InterviewAccessRequest.template_id == InterviewTemplate.id)
                .filter(InterviewAccessRequest.user_id == current_user.id)
                .order_by(InterviewAccessRequest.requested_at.desc())
                .all()
            )
            out = []
            for req, user, template in rows:
                out.append(
                    {
                        "id": req.id,
                        "user_id": req.user_id,
                        "template_id": req.template_id,
                        "template_title": template.title,
                        "user_name": user.name,
                        "username": user.username,
                        "status": req.status.value,
                        "request_type": req.request_type.value,
                        "reason": req.reason,
                        "requested_at": req.requested_at,
                        "reviewed_at": req.reviewed_at,
                        "expires_at": req.expires_at,
                    }
                )
            return out
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@user_router.get("/my-sessions", response_model=List[InterviewSessionOut])
async def my_sessions(
    current_user: User = Depends(get_current_user),
):
    def _sync_work():
        db = SessionLocal()
        try:
            rows = (
                db.query(InterviewSession, InterviewTemplate)
                .join(InterviewTemplate, InterviewSession.template_id == InterviewTemplate.id)
                .filter(InterviewSession.user_id == current_user.id)
                .order_by(InterviewSession.created_at.desc())
                .all()
            )
            out = []
            for s, t in rows:
                out.append(
                    {
                        "id": s.id,
                        "template_id": s.template_id,
                        "template_title": t.title,
                        "status": s.status.value,
                        "attempt_number": s.attempt_number,
                        "pause_count": s.pause_count,
                        "max_pauses_allowed": s.max_pauses_allowed_snapshot,
                        "started_at": s.started_at,
                        "completed_at": s.completed_at,
                        "total_score": s.total_score,
                    }
                )
            return out
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@user_router.post("/start", response_model=InterviewSessionOut)
async def start_interview(
    payload: InterviewStartIn,
    current_user: User = Depends(get_current_user),
):
    def _sync_work():
        db = SessionLocal()
        try:
            template = db.query(InterviewTemplate).filter(InterviewTemplate.id == payload.template_id).first()
            if not template:
                raise HTTPException(status_code=404, detail="Template not found")
            if template.is_archived:
                raise HTTPException(status_code=400, detail="Template is archived")

            active_session = (
                db.query(InterviewSession)
                .filter(
                    InterviewSession.user_id == current_user.id,
                    InterviewSession.template_id == payload.template_id,
                    InterviewSession.status.in_(_active_statuses()),
                )
                .first()
            )
            if active_session:
                if active_session.status == InterviewSessionStatus.paused:
                    raise HTTPException(status_code=400, detail="You have a paused interview. Resume it instead.")
                raise HTTPException(status_code=400, detail="You already have an active interview for this template")

            # Check if user has any missed interviews for this template
            missed_session = (
                db.query(InterviewSession)
                .filter(
                    InterviewSession.user_id == current_user.id,
                    InterviewSession.template_id == payload.template_id,
                    InterviewSession.status == InterviewSessionStatus.missed,
                )
                .first()
            )
            if missed_session:
                raise HTTPException(
                    status_code=403,
                    detail="You have a missed interview for this template. Please request a retry or contact admin."
                )

            # Check if user has already completed an interview for this template
            completed_session = (
                db.query(InterviewSession)
                .filter(
                    InterviewSession.user_id == current_user.id,
                    InterviewSession.template_id == payload.template_id,
                    InterviewSession.status == InterviewSessionStatus.completed,
                )
                .first()
            )
            if completed_session:
                raise HTTPException(
                    status_code=403,
                    detail="You have already completed this interview. Request a retry if you need another attempt."
                )

            approved = (
                db.query(InterviewAccessRequest)
                .filter(
                    InterviewAccessRequest.user_id == current_user.id,
                    InterviewAccessRequest.template_id == payload.template_id,
                    InterviewAccessRequest.status == InterviewAccessStatus.approved,
                )
                .order_by(InterviewAccessRequest.requested_at.desc())
                .first()
            )
            if not approved:
                raise HTTPException(status_code=403, detail="Interview access not approved")
            if approved.expires_at and as_utc_aware(approved.expires_at) < datetime.now(timezone.utc):
                approved.status = InterviewAccessStatus.expired
                db.commit()
                raise HTTPException(status_code=403, detail="Approved access expired. Please request again")

            attempt_number = (
                db.query(InterviewSession)
                .filter(
                    InterviewSession.user_id == current_user.id,
                    InterviewSession.template_id == payload.template_id,
                )
                .count()
                + 1
            )

            session = InterviewSession(
                user_id=current_user.id,
                template_id=payload.template_id,
                access_request_id=approved.id,
                attempt_number=attempt_number,
                status=InterviewSessionStatus.in_progress,
                started_at=datetime.now(timezone.utc),
                pause_count=0,
                disconnect_count=0,
                max_pauses_allowed_snapshot=template.max_pauses_allowed,
                transcript=[],
                feedback={},
            )
            db.add(session)
            db.flush()
            db.refresh(session)

            opening = generate_opening_question(
                str(session.id),
                template.role,
                template.experience_level,
                template.difficulty,
                template.focus_areas or [],
                template.default_questions_or_topics or [],
            )
            session.transcript = [
                {
                    "role": "assistant",
                    "content": opening,
                    "timestamp": to_utc_iso(datetime.now(timezone.utc)),
                }
            ]
            db.commit()

            return {
                "id": session.id,
                "template_id": session.template_id,
                "template_title": template.title,
                "status": session.status.value,
                "attempt_number": session.attempt_number,
                "pause_count": session.pause_count,
                "max_pauses_allowed": session.max_pauses_allowed_snapshot,
                "started_at": session.started_at,
                "completed_at": session.completed_at,
                "total_score": session.total_score,
            }
        finally:
            db.close()

    data = await run_db_sync(_sync_work)
    return InterviewSessionOut(**data)


@user_router.post("/{session_id}/message", response_model=InterviewMessageOut)
async def interview_message(
    session_id: UUID,
    payload: InterviewMessageIn,
    current_user: User = Depends(get_current_user),
):
    response_text = (payload.response_text or "").strip()
    if not response_text:
        raise HTTPException(status_code=400, detail="Response cannot be empty")

    def _sync_work():
        db = SessionLocal()
        try:
            row = (
                db.query(InterviewSession, InterviewTemplate)
                .join(InterviewTemplate, InterviewSession.template_id == InterviewTemplate.id)
                .filter(InterviewSession.id == session_id, InterviewSession.user_id == current_user.id)
                .first()
            )
            if not row:
                raise HTTPException(status_code=404, detail="Session not found")

            session, template = row
            if session.status != InterviewSessionStatus.in_progress:
                raise HTTPException(status_code=400, detail="Session is not in progress")

            transcript = list(session.transcript or [])
            transcript.append(
                {
                    "role": "user",
                    "content": response_text,
                    "timestamp": to_utc_iso(datetime.now(timezone.utc)),
                }
            )

            # Calculate current_topic_turns for drill-down limit
            focus_list = template.focus_areas or ["general"]
            feedback_obj = session.feedback if isinstance(session.feedback, dict) else {}
            turn_count = len(feedback_obj.get("turns", []))
            current_focus_idx = turn_count % len(focus_list)
            current_focus = focus_list[current_focus_idx]
            # Count consecutive turns on same topic
            existing_evals = (
                db.query(InterviewResponseEvaluation)
                .filter(
                    InterviewResponseEvaluation.session_id == session.id,
                    InterviewResponseEvaluation.focus_area == current_focus,
                )
                .count()
            )

            max_followup = getattr(template, "max_followup_depth", 2) or 2

            # Determine which default question to use next (turn_count is 0-based after this response)
            # The opening question used default_questions[0], so next turns use [1], [2], etc.
            default_questions = template.default_questions_or_topics or []
            next_default_idx = turn_count + 1  # +1 because opening already used index 0

            eval_result = evaluate_and_generate_followup(
                str(session.id),
                template.role,
                template.experience_level,
                template.difficulty,
                template.focus_areas or [],
                response_text,
                max_followup_depth=max_followup,
                current_topic_turns=existing_evals,
                default_questions=default_questions,
                current_turn=next_default_idx,
            )

            ai_message = eval_result.get("next_question") or "Please continue with your explanation."
            transcript.append(
                {
                    "role": "assistant",
                    "content": ai_message,
                    "timestamp": to_utc_iso(datetime.now(timezone.utc)),
                }
            )
            session.transcript = transcript

            feedback_obj = session.feedback if isinstance(session.feedback, dict) else {}
            feedback_obj = dict(feedback_obj)
            turn_feedback = list(feedback_obj.get("turns", []))
            turn_feedback.append(
                {
                    "turn": len(turn_feedback) + 1,
                    "score": eval_result.get("score"),
                    "strengths": eval_result.get("strengths", []),
                    "improvements": eval_result.get("improvements", []),
                    "feedback": eval_result.get("feedback", ""),
                }
            )
            feedback_obj["turns"] = turn_feedback
            session.feedback = feedback_obj

            eval_row = InterviewResponseEvaluation(
                session_id=session.id,
                turn_index=len(turn_feedback),
                user_response=response_text,
                score=eval_result.get("score"),
                ai_evaluation={
                    "score": eval_result.get("score"),
                    "strengths": eval_result.get("strengths", []),
                    "improvements": eval_result.get("improvements", []),
                    "feedback": eval_result.get("feedback", ""),
                    "next_question": ai_message,
                    "raw": eval_result.get("raw", ""),
                },
                focus_area=current_focus,
            )
            db.add(eval_row)
            db.flush()

            numeric_scores: list[float] = []
            for item in turn_feedback:
                value = item.get("score")
                if isinstance(value, (int, float)):
                    numeric_scores.append(float(value))
            if numeric_scores:
                session.total_score = round((sum(numeric_scores) / len(numeric_scores)) * 10.0, 2)

            db.commit()

            return {
                "session_id": session.id,
                "ai_message": ai_message,
                "score": eval_result.get("score"),
                "feedback": eval_result.get("feedback", ""),
                "pause_count": int(session.pause_count or 0),
                "max_pauses_allowed": int(session.max_pauses_allowed_snapshot or 3),
            }
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@user_router.post("/{session_id}/pause", response_model=MessageResponse)
async def pause_interview(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
):
    def _sync_work():
        db = SessionLocal()
        try:
            session = (
                db.query(InterviewSession)
                .filter(InterviewSession.id == session_id, InterviewSession.user_id == current_user.id)
                .first()
            )
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            if session.status not in [InterviewSessionStatus.in_progress, InterviewSessionStatus.started]:
                raise HTTPException(status_code=400, detail="Session cannot be paused in current state")

            session.pause_count = int(session.pause_count or 0) + 1
            session.paused_at = datetime.now(timezone.utc)
            if session.pause_count > int(session.max_pauses_allowed_snapshot or 3):
                session.status = InterviewSessionStatus.missed
                session.completed_at = datetime.now(timezone.utc)
                db.commit()
                return {"message": "Pause limit exceeded. Interview marked as missed."}

            session.status = InterviewSessionStatus.paused
            db.commit()
            return {"message": "Interview paused"}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@user_router.post("/{session_id}/interrupt", response_model=InterviewInterruptOut)
async def record_interrupt(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
):
    """Record a forced interruption (network drop/tab close) and enforce pause limit."""

    def _sync_work():
        db = SessionLocal()
        try:
            session = (
                db.query(InterviewSession)
                .filter(InterviewSession.id == session_id, InterviewSession.user_id == current_user.id)
                .first()
            )
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            if session.status in [InterviewSessionStatus.completed, InterviewSessionStatus.abandoned, InterviewSessionStatus.missed]:
                raise HTTPException(status_code=400, detail="Session already closed")

            session.disconnect_count = int(session.disconnect_count or 0) + 1
            session.pause_count = int(session.pause_count or 0) + 1
            session.paused_at = datetime.now(timezone.utc)

            max_allowed = int(session.max_pauses_allowed_snapshot or 3)
            if session.pause_count > max_allowed:
                session.status = InterviewSessionStatus.missed
                session.completed_at = datetime.now(timezone.utc)
                db.commit()
                return {
                    "message": "Interruption limit exceeded. Interview marked as missed.",
                    "status": session.status.value,
                    "pause_count": int(session.pause_count or 0),
                    "disconnect_count": int(session.disconnect_count or 0),
                    "max_pauses_allowed": max_allowed,
                }

            session.status = InterviewSessionStatus.paused
            db.commit()
            return {
                "message": "Interruption recorded. Interview paused.",
                "status": session.status.value,
                "pause_count": int(session.pause_count or 0),
                "disconnect_count": int(session.disconnect_count or 0),
                "max_pauses_allowed": max_allowed,
            }
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@user_router.post("/{session_id}/resume", response_model=MessageResponse)
async def resume_interview(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
):
    def _sync_work():
        db = SessionLocal()
        try:
            row = (
                db.query(InterviewSession, InterviewTemplate)
                .join(InterviewTemplate, InterviewSession.template_id == InterviewTemplate.id)
                .filter(InterviewSession.id == session_id, InterviewSession.user_id == current_user.id)
                .first()
            )
            if not row:
                raise HTTPException(status_code=404, detail="Session not found")
            session, template = row
            if session.status != InterviewSessionStatus.paused:
                raise HTTPException(status_code=400, detail="Only paused sessions can be resumed")
            if session.pause_count > int(session.max_pauses_allowed_snapshot or 3):
                session.status = InterviewSessionStatus.missed
                session.completed_at = datetime.now(timezone.utc)
                db.commit()
                raise HTTPException(status_code=400, detail="Pause limit exceeded. Interview marked as missed")
            if template.is_archived and not session.started_at:
                raise HTTPException(status_code=400, detail="Template archived and session cannot be resumed")
            session.status = InterviewSessionStatus.in_progress
            session.resumed_at = datetime.now(timezone.utc)
            db.commit()
            return {"message": "Interview resumed"}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@user_router.post("/{session_id}/end", response_model=MessageResponse)
async def end_interview(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
):
    def _sync_work():
        db = SessionLocal()
        try:
            session = (
                db.query(InterviewSession)
                .filter(InterviewSession.id == session_id, InterviewSession.user_id == current_user.id)
                .first()
            )
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            if session.status in [InterviewSessionStatus.completed, InterviewSessionStatus.missed, InterviewSessionStatus.abandoned]:
                raise HTTPException(status_code=400, detail="Session already closed")

            session.status = InterviewSessionStatus.completed
            session.completed_at = datetime.now(timezone.utc)
            if not session.summary:
                session.summary = "Interview completed. Detailed AI feedback will appear here after evaluator integration."
            db.commit()
            return {"message": "Interview completed"}
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@user_router.get("/{session_id}/results", response_model=InterviewSessionResultOut)
async def get_my_result(
    session_id: UUID,
    current_user: User = Depends(get_current_user),
):
    def _sync_work():
        db = SessionLocal()
        try:
            row = (
                db.query(InterviewSession, InterviewTemplate)
                .join(InterviewTemplate, InterviewSession.template_id == InterviewTemplate.id)
                .filter(InterviewSession.id == session_id, InterviewSession.user_id == current_user.id)
                .first()
            )
            if not row:
                raise HTTPException(status_code=404, detail="Session not found")
            session, template = row

            # Fetch per-turn evaluations
            evals = (
                db.query(InterviewResponseEvaluation)
                .filter(InterviewResponseEvaluation.session_id == session.id)
                .order_by(InterviewResponseEvaluation.turn_index)
                .all()
            )

            evaluations_out = []
            topic_map: dict[str, list[float]] = {}
            for ev in evals:
                ai_eval = ev.ai_evaluation or {}
                evaluations_out.append({
                    "turn_index": ev.turn_index,
                    "user_response": ev.user_response,
                    "score": ev.score,
                    "focus_area": ev.focus_area,
                    "strengths": ai_eval.get("strengths", []),
                    "improvements": ai_eval.get("improvements", []),
                    "feedback": ai_eval.get("feedback", ""),
                })
                topic = ev.focus_area or "general"
                if ev.score is not None:
                    topic_map.setdefault(topic, []).append(ev.score)

            topic_scores_out = [
                {"topic": topic, "avg_score": round(sum(scores) / len(scores), 1), "turns": len(scores)}
                for topic, scores in topic_map.items()
            ]

            return {
                "id": session.id,
                "template_id": session.template_id,
                "template_title": template.title,
                "status": session.status.value,
                "attempt_number": session.attempt_number,
                "started_at": session.started_at,
                "completed_at": session.completed_at,
                "pause_count": session.pause_count,
                "disconnect_count": session.disconnect_count,
                "total_score": session.total_score,
                "summary": session.summary,
                "transcript": session.transcript or [],
                "feedback": session.feedback or {},
                "evaluations": evaluations_out,
                "topic_scores": topic_scores_out,
            }
        finally:
            db.close()

    return await run_db_sync(_sync_work)


@user_router.get("/dashboard-counts", response_model=DashboardCountsOut)
async def interview_dashboard_counts(
    current_user: User = Depends(get_current_user),
):
    def _sync_work():
        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            # Count approved requests where user has NOT already started/completed/missed
            approved_requests = (
                db.query(InterviewAccessRequest)
                .join(InterviewTemplate, InterviewAccessRequest.template_id == InterviewTemplate.id)
                .filter(
                    InterviewAccessRequest.user_id == current_user.id,
                    InterviewAccessRequest.status == InterviewAccessStatus.approved,
                    InterviewTemplate.is_archived.is_(False),
                    (InterviewAccessRequest.expires_at.is_(None) | (InterviewAccessRequest.expires_at >= now)),
                )
                .all()
            )
            # Exclude templates that already have a session
            templates_with_sessions = set(
                t_id for (t_id,) in db.query(InterviewSession.template_id)
                .filter(InterviewSession.user_id == current_user.id)
                .distinct()
                .all()
            )
            to_attend = sum(
                1 for r in approved_requests
                if r.template_id not in templates_with_sessions
            )
            in_progress = (
                db.query(InterviewSession)
                .filter(
                    InterviewSession.user_id == current_user.id,
                    InterviewSession.status.in_([
                        InterviewSessionStatus.in_progress,
                        InterviewSessionStatus.paused,
                    ]),
                )
                .count()
            )
            return {
                "interviews_to_attend": to_attend,
                "interviews_in_progress": in_progress,
            }
        finally:
            db.close()

    return await run_db_sync(_sync_work)
