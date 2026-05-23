"""
Backfill embeddings for questions that were uploaded before the embedding system was added.
Runs on startup as a background thread.
"""

import logging
from sqlalchemy import select, func

from db.database import SessionLocal
from db.models import Question, QuestionEmbedding, QuestionOption

logger = logging.getLogger(__name__)

BATCH_SIZE = 20  # Process in batches to avoid overwhelming the embedding API


def backfill_missing_embeddings() -> None:
    """Find questions without embeddings and generate them."""
    from core.embedding_service import build_embedding_text, compute_embeddings, store_question_embedding

    db = SessionLocal()
    try:
        # Find question IDs that don't have an embedding yet
        subq = select(QuestionEmbedding.question_id).where(
            QuestionEmbedding.question_id.isnot(None)
        ).correlate(None)

        missing = db.execute(
            select(Question.id)
            .where(
                Question.is_archived == False,
                Question.id.notin_(subq),
            )
        ).scalars().all()

        if not missing:
            logger.info("[Embedding Backfill] All questions already have embeddings")
            return

        logger.info(f"[Embedding Backfill] Found {len(missing)} questions without embeddings, processing...")

        total_processed = 0

        for i in range(0, len(missing), BATCH_SIZE):
            batch_ids = missing[i:i + BATCH_SIZE]

            # Load full question data for this batch
            questions_data = []
            for qid in batch_ids:
                q = db.execute(select(Question).where(Question.id == qid)).scalar_one_or_none()
                if not q:
                    continue

                # Load options for MCQ questions
                options = None
                if q.type and q.type.value in ("single_mcq", "multi_mcq"):
                    opts = db.execute(
                        select(QuestionOption).where(QuestionOption.question_id == q.id)
                    ).scalars().all()
                    options = [{"option_text": o.option_text, "is_correct": o.is_correct} for o in opts]

                questions_data.append({
                    "id": q.id,
                    "question_text": q.question,
                    "question_type": q.type.value if q.type else "text",
                    "options": options,
                    "reference_answer": q.reference_answer,
                })

            if not questions_data:
                continue

            # Build composite texts
            texts = [
                build_embedding_text(
                    question_text=qd["question_text"],
                    question_type=qd["question_type"],
                    options=qd.get("options"),
                    reference_answer=qd.get("reference_answer"),
                )
                for qd in questions_data
            ]

            # Compute embeddings in batch
            try:
                embeddings = compute_embeddings(texts)
            except Exception as e:
                logger.error(f"[Embedding Backfill] Failed to compute batch {i//BATCH_SIZE + 1}: {e}")
                continue

            # Store each embedding
            for qd, text, embedding in zip(questions_data, texts, embeddings):
                try:
                    store_question_embedding(
                        question_id=qd["id"],
                        staged_question_id=None,
                        text=text,
                        embedding=embedding,
                    )
                except Exception as e:
                    logger.error(f"[Embedding Backfill] Failed to store embedding for {qd['id']}: {e}")

            total_processed += len(questions_data)
            logger.info(f"[Embedding Backfill] Processed {total_processed}/{len(missing)} questions")

        logger.info(f"[Embedding Backfill] Complete — {total_processed} embeddings generated")

    except Exception as e:
        logger.error(f"[Embedding Backfill] Unexpected error: {e}")
    finally:
        db.close()
