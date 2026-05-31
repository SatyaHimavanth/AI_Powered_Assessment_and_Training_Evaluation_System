"""
pgvector helpers for question embedding storage and similarity search.
"""

import logging
import os
from typing import List, Tuple
from uuid import UUID

from sqlalchemy import text

from db.database import SessionLocal

logger = logging.getLogger(__name__)

# Azure text-embedding-3-small default dimension.
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))


def _vector_literal(embedding: List[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in embedding) + "]"


def ensure_pgvector_ready() -> None:
    """Ensure pgvector exists and the embedding column uses vector(N)."""
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


def search_question_embeddings(
    query_embedding: List[float],
    top_k: int = 5,
) -> List[Tuple[UUID, float]]:
    """Search active question embeddings by cosine similarity."""
    db = SessionLocal()
    try:
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
