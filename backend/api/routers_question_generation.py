"""
API router for AI question generation.
"""

import asyncio
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core.auth import require_admin
from core.question_generation import (
    approve_staged_question,
    process_generation_batch,
    reject_staged_question,
)
from db.async_helpers import run_db_sync
from db.database import SessionLocal
from db.models import (
    Difficulty,
    GenerationBatchStatus,
    QuestionGenerationBatch,
    QuestionType,
    StagedQuestion,
    StagedQuestionStatus,
    User,
)

from sqlalchemy import func, select

router = APIRouter(prefix="/admin/questions/generation", tags=["question-generation"])


# ─── Request / Response schemas ───────────────────────────────────────────────


class GenerateBatchRequest(BaseModel):
    source_text: str
    topic_id: Optional[UUID] = None
    question_type: Optional[str] = "text"
    difficulty: Optional[str] = "medium"
    count: int = 10
    auto_approve_unique: bool = False


class BatchResponse(BaseModel):
    id: UUID
    status: str
    filename: Optional[str] = None
    total_generated: int
    total_approved: int
    total_rejected: int
    requested_count: int
    created_at: str
    completed_at: Optional[str] = None

    class Config:
        from_attributes = True


class StagedQuestionResponse(BaseModel):
    id: UUID
    question_type: str
    question_text: str
    reference_answer: Optional[str] = None
    options: Optional[list] = None
    difficulty: Optional[str] = None
    similarity_score: Optional[float] = None
    matched_question_id: Optional[UUID] = None
    match_band: Optional[str] = None
    status: str
    created_at: str

    class Config:
        from_attributes = True


class StagedQuestionListResponse(BaseModel):
    items: list[StagedQuestionResponse]
    total: int
    page: int
    page_size: int


class BatchListResponse(BaseModel):
    items: list[BatchResponse]
    total: int


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/generate", response_model=BatchResponse)
async def start_generation(
    req: GenerateBatchRequest,
    admin: User = Depends(require_admin),
):
    """Start a new question generation batch."""
    import uuid as uuid_mod

    # Validate enums
    q_type = None
    for qt in QuestionType:
        if qt.value == req.question_type:
            q_type = qt
            break
    if not q_type:
        raise HTTPException(400, f"Invalid question_type: {req.question_type}")

    diff = None
    for d in Difficulty:
        if d.value == req.difficulty:
            diff = d
            break
    if not diff:
        raise HTTPException(400, f"Invalid difficulty: {req.difficulty}")

    if req.count < 1 or req.count > 50:
        raise HTTPException(400, "Count must be between 1 and 50")

    if not req.topic_id:
        raise HTTPException(400, "Topic is required")

    def _create_batch():
        db = SessionLocal()
        try:
            batch = QuestionGenerationBatch(
                id=uuid_mod.uuid4(),
                admin_id=admin.id,
                source_text=req.source_text,
                topic_id=req.topic_id,
                question_type=q_type,
                difficulty=diff,
                requested_count=req.count,
                auto_approve_unique=req.auto_approve_unique,
                status=GenerationBatchStatus.pending,
            )
            db.add(batch)
            db.commit()
            db.refresh(batch)
            return {
                "id": batch.id,
                "status": batch.status.value,
                "filename": batch.filename,
                "total_generated": batch.total_generated,
                "total_approved": batch.total_approved,
                "total_rejected": batch.total_rejected,
                "requested_count": batch.requested_count,
                "created_at": batch.created_at.isoformat(),
                "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
            }
        finally:
            db.close()

    result = await run_db_sync(_create_batch)

    # Process in background
    asyncio.get_event_loop().run_in_executor(
        None, process_generation_batch, result["id"]
    )

    return result


@router.get("/batches", response_model=BatchListResponse)
async def list_batches(
    admin: User = Depends(require_admin),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List all generation batches for current admin."""

    def _query():
        db = SessionLocal()
        try:
            base = select(QuestionGenerationBatch).where(
                QuestionGenerationBatch.admin_id == admin.id
            )
            total = db.execute(
                select(func.count()).select_from(base.subquery())
            ).scalar() or 0

            rows = db.execute(
                base.order_by(QuestionGenerationBatch.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).scalars().all()

            items = []
            for b in rows:
                items.append({
                    "id": b.id,
                    "status": b.status.value,
                    "filename": b.filename,
                    "total_generated": b.total_generated,
                    "total_approved": b.total_approved,
                    "total_rejected": b.total_rejected,
                    "requested_count": b.requested_count,
                    "created_at": b.created_at.isoformat(),
                    "completed_at": b.completed_at.isoformat() if b.completed_at else None,
                })
            return {"items": items, "total": total}
        finally:
            db.close()

    return await run_db_sync(_query)


@router.get("/batches/{batch_id}", response_model=BatchResponse)
async def get_batch(
    batch_id: UUID,
    admin: User = Depends(require_admin),
):
    """Get a single batch's details."""

    def _query():
        db = SessionLocal()
        try:
            batch = db.execute(
                select(QuestionGenerationBatch).where(
                    QuestionGenerationBatch.id == batch_id,
                    QuestionGenerationBatch.admin_id == admin.id,
                )
            ).scalar_one_or_none()
            if not batch:
                return None
            return {
                "id": batch.id,
                "status": batch.status.value,
                "filename": batch.filename,
                "total_generated": batch.total_generated,
                "total_approved": batch.total_approved,
                "total_rejected": batch.total_rejected,
                "requested_count": batch.requested_count,
                "created_at": batch.created_at.isoformat(),
                "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
            }
        finally:
            db.close()

    result = await run_db_sync(_query)
    if not result:
        raise HTTPException(404, "Batch not found")
    return result


@router.get("/batches/{batch_id}/staged", response_model=StagedQuestionListResponse)
async def list_staged_questions(
    batch_id: UUID,
    admin: User = Depends(require_admin),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = None,
    band: Optional[str] = None,
):
    """List staged questions for a batch with optional filtering."""

    def _query():
        db = SessionLocal()
        try:
            # Verify batch ownership
            batch = db.execute(
                select(QuestionGenerationBatch).where(
                    QuestionGenerationBatch.id == batch_id,
                    QuestionGenerationBatch.admin_id == admin.id,
                )
            ).scalar_one_or_none()
            if not batch:
                return None

            base = select(StagedQuestion).where(StagedQuestion.batch_id == batch_id)

            if status:
                for s in StagedQuestionStatus:
                    if s.value == status:
                        base = base.where(StagedQuestion.status == s)
                        break

            if band:
                from db.models import MatchBand
                for mb in MatchBand:
                    if mb.value == band:
                        base = base.where(StagedQuestion.match_band == mb)
                        break

            total = db.execute(
                select(func.count()).select_from(base.subquery())
            ).scalar() or 0

            rows = db.execute(
                base.order_by(StagedQuestion.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).scalars().all()

            items = []
            for sq in rows:
                items.append({
                    "id": sq.id,
                    "question_type": sq.question_type.value if sq.question_type else None,
                    "question_text": sq.question_text,
                    "reference_answer": sq.reference_answer,
                    "options": sq.options,
                    "difficulty": sq.difficulty.value if sq.difficulty else None,
                    "similarity_score": sq.similarity_score,
                    "matched_question_id": str(sq.matched_question_id) if sq.matched_question_id else None,
                    "match_band": sq.match_band.value if sq.match_band else None,
                    "status": sq.status.value,
                    "created_at": sq.created_at.isoformat(),
                })
            return {"items": items, "total": total, "page": page, "page_size": page_size}
        finally:
            db.close()

    result = await run_db_sync(_query)
    if result is None:
        raise HTTPException(404, "Batch not found")
    return result


@router.post("/staged/{staged_id}/approve")
async def approve_question(
    staged_id: UUID,
    admin: User = Depends(require_admin),
):
    """Approve a staged question — creates it in the question bank."""
    new_id = await run_db_sync(approve_staged_question, staged_id, admin.id)
    if not new_id:
        raise HTTPException(400, "Cannot approve this question (not found or not pending)")
    return {"question_id": new_id, "status": "approved"}


@router.post("/staged/{staged_id}/reject")
async def reject_question(
    staged_id: UUID,
    admin: User = Depends(require_admin),
):
    """Reject a staged question."""
    success = await run_db_sync(reject_staged_question, staged_id, admin.id)
    if not success:
        raise HTTPException(400, "Cannot reject this question (not found or not pending)")
    return {"status": "rejected"}


@router.get("/questions/{question_id}")
async def get_question_for_comparison(
    question_id: UUID,
    admin: User = Depends(require_admin),
):
    """Get an existing question's details for comparison with a staged question."""
    from db.models import Question, QuestionOption

    def _query():
        db = SessionLocal()
        try:
            q = db.execute(select(Question).where(Question.id == question_id)).scalar_one_or_none()
            if not q:
                return None
            opts = db.execute(
                select(QuestionOption).where(QuestionOption.question_id == q.id)
            ).scalars().all()
            return {
                "id": str(q.id),
                "question_text": q.question,
                "question_type": q.type.value if q.type else None,
                "difficulty": q.difficulty.value if q.difficulty else None,
                "reference_answer": q.reference_answer,
                "options": [{"option_text": o.option_text, "is_correct": o.is_correct} for o in opts] if opts else None,
            }
        finally:
            db.close()

    result = await run_db_sync(_query)
    if not result:
        raise HTTPException(404, "Question not found")
    return result
