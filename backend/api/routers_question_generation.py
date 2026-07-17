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
    Question,
    QuestionEmbedding,
    QuestionGenerationBatch,
    QuestionOption,
    QuestionType,
    StagedQuestion,
    StagedQuestionStatus,
    User,
)
from api.timezone_helper import to_utc_iso

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
    active_saved_count: int = 0
    archived_saved_count: int = 0
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


class ArchiveGeneratedQuestionsResponse(BaseModel):
    message: str
    approved_count: int
    archived_count: int
    skipped_count: int
    question_ids: list[UUID]


class RestoreArchivedQuestionsResponse(BaseModel):
    message: str
    restored_count: int
    skipped_count: int
    question_ids: list[UUID]


def _normalize(value: Optional[str]) -> str:
    return (value or "").strip()


def _staged_options(staged: StagedQuestion) -> list[tuple[str, bool]]:
    return [
        (_normalize(opt.get("option_text") or opt.get("text")), bool(opt.get("is_correct")))
        for opt in (staged.options or [])
        if isinstance(opt, dict)
    ]


def _question_options(db, question_id: UUID) -> list[tuple[str, bool]]:
    options = db.execute(
        select(QuestionOption).where(QuestionOption.question_id == question_id)
    ).scalars().all()
    return [(_normalize(o.option_text), bool(o.is_correct)) for o in options]


def _question_matches_staged(db, question: Question, staged: StagedQuestion) -> bool:
    if _normalize(question.question) != _normalize(staged.question_text):
        return False
    if question.topic_id != staged.topic_id:
        return False
    if question.type != staged.question_type:
        return False
    if question.difficulty != staged.difficulty:
        return False
    if _normalize(question.reference_answer) != _normalize(staged.reference_answer):
        return False
    if staged.question_type in (QuestionType.single_mcq, QuestionType.multi_mcq):
        return _question_options(db, question.id) == _staged_options(staged)
    return True


def _find_saved_question_for_staged(
    db,
    batch: QuestionGenerationBatch,
    staged: StagedQuestion,
    archived: bool,
    seen_question_ids: set[UUID],
) -> Question | None:
    embedding = db.execute(
        select(QuestionEmbedding).where(
            QuestionEmbedding.staged_question_id == staged.id,
            QuestionEmbedding.question_id.is_not(None),
        )
    ).scalars().first()
    if embedding and embedding.question_id and embedding.question_id not in seen_question_ids:
        question = db.execute(
            select(Question).where(Question.id == embedding.question_id)
        ).scalar_one_or_none()
        if question and bool(question.is_archived) == archived:
            return question

    candidates = db.execute(
        select(Question).where(
            Question.topic_id == staged.topic_id,
            Question.type == staged.question_type,
            Question.difficulty == staged.difficulty,
            Question.question == staged.question_text,
            Question.created_at >= batch.created_at,
            Question.is_archived == archived,
        ).order_by(Question.created_at.asc())
    ).scalars().all()
    return next(
        (
            candidate
            for candidate in candidates
            if candidate.id not in seen_question_ids
            and _question_matches_staged(db, candidate, staged)
        ),
        None,
    )


def _saved_question_counts(db, batch: QuestionGenerationBatch) -> tuple[int, int]:
    staged_rows = db.execute(
        select(StagedQuestion).where(
            StagedQuestion.batch_id == batch.id,
            StagedQuestion.status == StagedQuestionStatus.approved,
        )
    ).scalars().all()
    active_count = 0
    archived_count = 0
    seen_active: set[UUID] = set()
    seen_archived: set[UUID] = set()
    for staged in staged_rows:
        active_question = _find_saved_question_for_staged(db, batch, staged, False, seen_active)
        if active_question:
            active_count += 1
            seen_active.add(active_question.id)
            continue
        archived_question = _find_saved_question_for_staged(db, batch, staged, True, seen_archived)
        if archived_question:
            archived_count += 1
            seen_archived.add(archived_question.id)
    return active_count, archived_count


def _batch_response(db, batch: QuestionGenerationBatch) -> dict:
    active_saved_count, archived_saved_count = _saved_question_counts(db, batch)
    return {
        "id": batch.id,
        "status": batch.status.value,
        "filename": batch.filename,
        "total_generated": batch.total_generated,
        "total_approved": batch.total_approved,
        "total_rejected": batch.total_rejected,
        "requested_count": batch.requested_count,
        "active_saved_count": active_saved_count,
        "archived_saved_count": archived_saved_count,
        "created_at": to_utc_iso(batch.created_at),
        "completed_at": to_utc_iso(batch.completed_at),
    }


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
                "active_saved_count": 0,
                "archived_saved_count": 0,
                "created_at": to_utc_iso(batch.created_at),
                "completed_at": to_utc_iso(batch.completed_at),
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
                items.append(_batch_response(db, b))
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
            return _batch_response(db, batch)
        finally:
            db.close()

    result = await run_db_sync(_query)
    if not result:
        raise HTTPException(404, "Batch not found")
    return result


@router.post("/batches/{batch_id}/archive-questions", response_model=ArchiveGeneratedQuestionsResponse)
async def archive_batch_questions(
    batch_id: UUID,
    admin: User = Depends(require_admin),
):
    """Archive saved question-bank rows created from an AI generation batch."""

    def _sync_work():
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

            staged_rows = db.execute(
                select(StagedQuestion).where(
                    StagedQuestion.batch_id == batch_id,
                    StagedQuestion.status == StagedQuestionStatus.approved,
                )
            ).scalars().all()
            if not staged_rows:
                return {
                    "approved_count": 0,
                    "archived_count": 0,
                    "skipped_count": 0,
                    "question_ids": [],
                }

            archived_ids: list[UUID] = []
            seen_question_ids: set[UUID] = set()

            for staged in staged_rows:
                question = _find_saved_question_for_staged(db, batch, staged, False, seen_question_ids)
                if not question:
                    continue

                question.is_archived = True
                seen_question_ids.add(question.id)
                archived_ids.append(question.id)

            db.commit()
            return {
                "approved_count": len(staged_rows),
                "archived_count": len(archived_ids),
                "skipped_count": len(staged_rows) - len(archived_ids),
                "question_ids": archived_ids,
            }
        finally:
            db.close()

    result = await run_db_sync(_sync_work)
    if result is None:
        raise HTTPException(404, "Batch not found")

    if result["archived_count"]:
        result["message"] = f"Archived {result['archived_count']} saved question(s) from this batch."
    elif result["approved_count"]:
        result["message"] = "No active saved questions were found for this batch."
    else:
        result["message"] = "This batch has no approved saved questions to archive."
    return result


@router.post("/batches/{batch_id}/restore-archived-questions", response_model=RestoreArchivedQuestionsResponse)
async def restore_archived_batch_questions(
    batch_id: UUID,
    admin: User = Depends(require_admin),
):
    """Move archived generated questions back to pending staged review."""

    def _sync_work():
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

            approved_rows = db.execute(
                select(StagedQuestion).where(
                    StagedQuestion.batch_id == batch_id,
                    StagedQuestion.status == StagedQuestionStatus.approved,
                )
            ).scalars().all()
            rejected_rows = db.execute(
                select(StagedQuestion).where(
                    StagedQuestion.batch_id == batch_id,
                    StagedQuestion.status.in_([
                        StagedQuestionStatus.rejected,
                        StagedQuestionStatus.auto_rejected,
                    ]),
                )
            ).scalars().all()

            restored_question_ids: list[UUID] = []
            restored_rejected_count = 0
            seen_question_ids: set[UUID] = set()

            for staged in approved_rows:
                if _find_saved_question_for_staged(db, batch, staged, False, set()):
                    continue
                question = _find_saved_question_for_staged(db, batch, staged, True, seen_question_ids)
                if not question:
                    continue

                staged.status = StagedQuestionStatus.pending
                staged.reviewer_id = None
                staged.reviewed_at = None
                seen_question_ids.add(question.id)
                restored_question_ids.append(question.id)

            for staged in rejected_rows:
                staged.status = StagedQuestionStatus.pending
                staged.reviewer_id = None
                staged.reviewed_at = None
                restored_rejected_count += 1

            if restored_question_ids:
                batch.total_approved = max((batch.total_approved or 0) - len(restored_question_ids), 0)
            if restored_rejected_count:
                batch.total_rejected = max((batch.total_rejected or 0) - restored_rejected_count, 0)

            db.commit()
            restored_count = len(restored_question_ids) + restored_rejected_count
            candidate_count = len(approved_rows) + len(rejected_rows)
            return {
                "restored_count": restored_count,
                "skipped_count": candidate_count - restored_count,
                "question_ids": restored_question_ids,
            }
        finally:
            db.close()

    result = await run_db_sync(_sync_work)
    if result is None:
        raise HTTPException(404, "Batch not found")

    if result["restored_count"]:
        result["message"] = (
            f"Moved {result['restored_count']} generated question(s) back to pending review."
        )
    else:
        result["message"] = "No archived or rejected generated questions were found for this batch."
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
                    "created_at": to_utc_iso(sq.created_at),
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
