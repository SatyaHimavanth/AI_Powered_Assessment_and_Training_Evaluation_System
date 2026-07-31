"""Embedding storage setup and similarity search."""

import json
import logging
import math
import os
from typing import List, Tuple
from uuid import UUID

from sqlalchemy import text

from db.database import SessionLocal

logger = logging.getLogger(__name__)

# Azure text-embedding-3-small default dimension.
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))
EMBEDDING_STORAGE_BACKEND = os.getenv(
    "EMBEDDING_STORAGE_BACKEND", "pgvector"
).strip().lower()
if EMBEDDING_STORAGE_BACKEND not in {"pgvector", "json"}:
    raise ValueError("EMBEDDING_STORAGE_BACKEND must be 'pgvector' or 'json'")


def _vector_literal(embedding: List[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in embedding) + "]"


def ensure_pgvector_ready() -> None:
    """Prepare the configured embedding storage backend."""
    if EMBEDDING_STORAGE_BACKEND == "json":
        logger.info("JSON embedding storage enabled; pgvector setup skipped")
        return

    db = SessionLocal()
    try:
        db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        db.execute(text(f"""
            ALTER TABLE IF EXISTS question_embeddings
            ALTER COLUMN embedding TYPE vector({EMBEDDING_DIM})
            USING embedding::text::vector({EMBEDDING_DIM})
        """))
        db.commit()
        logger.info("pgvector is ready for question embeddings")
    except Exception:
        db.rollback()
        logger.exception("pgvector setup failed")
        raise
    finally:
        db.close()


def _coerce_embedding(value) -> List[float]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list):
        raise ValueError("Stored embedding is not a JSON array")
    return [float(item) for item in value]


def _cosine_similarity(left: List[float], right: List[float]) -> float:
    if len(left) != len(right):
        raise ValueError("Embedding dimensions do not match")
    left_norm = math.sqrt(math.fsum(value * value for value in left))
    right_norm = math.sqrt(math.fsum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    dot_product = math.fsum(a * b for a, b in zip(left, right))
    return max(-1.0, min(1.0, dot_product / (left_norm * right_norm)))


def search_question_embeddings(
    query_embedding: List[float],
    top_k: int = 5,
) -> List[Tuple[UUID, float]]:
    """Search active question embeddings by cosine similarity."""
    if len(query_embedding) != EMBEDDING_DIM:
        raise ValueError(
            f"Expected embedding dimension {EMBEDDING_DIM}, got {len(query_embedding)}"
        )

    db = SessionLocal()
    try:
        if EMBEDDING_STORAGE_BACKEND == "json":
            from db.models import Question, QuestionEmbedding

            rows = (
                db.query(QuestionEmbedding.question_id, QuestionEmbedding.embedding)
                .join(Question, Question.id == QuestionEmbedding.question_id)
                .filter(
                    QuestionEmbedding.question_id.isnot(None),
                    Question.is_archived.is_not(True),
                )
                .all()
            )
            scored = [
                (
                    UUID(str(question_id)),
                    _cosine_similarity(query_embedding, _coerce_embedding(embedding)),
                )
                for question_id, embedding in rows
            ]
            scored.sort(key=lambda item: item[1], reverse=True)
            return scored[:top_k]

        rows = db.execute(
            text("""
                SELECT qe.question_id,
                       1 - (qe.embedding <=> CAST(:embedding AS vector)) AS similarity
                FROM question_embeddings qe
                JOIN questions q ON q.id = qe.question_id
                WHERE qe.question_id IS NOT NULL
                  AND q.is_archived IS NOT TRUE
                ORDER BY qe.embedding <=> CAST(:embedding AS vector)
                LIMIT :top_k
            """),
            {"embedding": _vector_literal(query_embedding), "top_k": top_k},
        ).fetchall()
        return [(UUID(str(row[0])), float(row[1])) for row in rows]
    finally:
        db.close()
