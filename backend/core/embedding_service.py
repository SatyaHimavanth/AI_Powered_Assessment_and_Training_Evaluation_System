"""
Embedding service for question similarity checking.

Computes embeddings for questions and manages similarity searches
using the vector store abstraction layer.
"""

import logging
import os
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select

from app.llms import get_embeddings_model
from core.vector_store import get_vector_store, EMBEDDING_DIM
from db.database import SessionLocal
from db.models import QuestionEmbedding, Question

logger = logging.getLogger(__name__)

# Similarity thresholds (cosine similarity 0.0 - 1.0)
THRESHOLD_HIGH_DUP = float(os.getenv("SIMILARITY_THRESHOLD_HIGH_DUP", "0.10"))
THRESHOLD_REVIEW = float(os.getenv("SIMILARITY_THRESHOLD_REVIEW", "0.10"))


def get_match_band(score: float) -> str:
    """Classify similarity score into a match band."""
    if score >= THRESHOLD_HIGH_DUP:
        return "high_dup"
    elif score >= THRESHOLD_REVIEW:
        return "review"
    return "unique"


def build_embedding_text(
    question_text: str,
    question_type: str = "text",
    options: Optional[list] = None,
    reference_answer: Optional[str] = None,
) -> str:
    """
    Build composite text for embedding that includes question context.

    - MCQs: question + options
    - Text Q&A: question + reference answer
    - Coding: question only
    """
    parts = [f"Q: {question_text}"]

    if question_type in ("single_mcq", "multi_mcq") and options:
        opt_parts = []
        for i, opt in enumerate(options):
            opt_text = opt.get("option_text", opt.get("text", "")) if isinstance(opt, dict) else str(opt)
            opt_parts.append(f"{chr(65 + i)}. {opt_text}")
        if opt_parts:
            parts.append("Options: " + " ".join(opt_parts))
    elif question_type == "text" and reference_answer:
        parts.append(f"Answer: {reference_answer}")

    return "\n".join(parts)


def compute_embeddings(texts: List[str]) -> List[List[float]]:
    """Compute embeddings for a list of texts using the Azure embeddings model."""
    model = get_embeddings_model()
    embeddings = model.embed_documents(texts)
    return embeddings


def compute_single_embedding(text: str) -> List[float]:
    """Compute embedding for a single text."""
    model = get_embeddings_model()
    return model.embed_query(text)


def store_question_embedding(
    question_id: UUID | None,
    staged_question_id: UUID | None,
    text: str,
    embedding: List[float],
) -> UUID:
    """Store an embedding in the database and vector store."""
    import uuid as uuid_mod

    db = SessionLocal()
    try:
        emb_record = QuestionEmbedding(
            id=uuid_mod.uuid4(),
            question_id=question_id,
            staged_question_id=staged_question_id,
            embedding_text=text,
            embedding=embedding,
        )
        db.add(emb_record)
        db.commit()
        db.refresh(emb_record)

        # Add to vector store index
        store = get_vector_store()
        store.add_embeddings([emb_record.id], [embedding])

        return emb_record.id
    finally:
        db.close()


def find_similar_questions(
    text: str, top_k: int = 5
) -> List[Tuple[UUID, float, str]]:
    """
    Find questions similar to the given text.
    Returns list of (question_id, similarity_score, match_band).
    """
    embedding = compute_single_embedding(text)
    store = get_vector_store()
    results = store.search(embedding, top_k=top_k)

    # Map embedding IDs back to question IDs
    if not results:
        return []

    db = SessionLocal()
    try:
        output = []
        for emb_id, score in results:
            row = db.execute(
                select(QuestionEmbedding.question_id).where(QuestionEmbedding.id == emb_id)
            ).scalar_one_or_none()
            if row:
                output.append((row, score, get_match_band(score)))
        return output
    finally:
        db.close()


def check_similarity(text: str) -> Tuple[float, UUID | None, str]:
    """
    Check similarity of a question text against the existing question bank.
    Returns (max_similarity_score, matched_question_id, match_band).
    """
    results = find_similar_questions(text, top_k=1)
    if not results:
        return (0.0, None, "unique")
    q_id, score, band = results[0]
    return (score, q_id, band)


def rebuild_vector_index():
    """
    Rebuild the vector store index from all stored embeddings.
    Useful after switching from FAISS to pgvector or vice versa.
    """
    db = SessionLocal()
    try:
        embeddings = db.execute(
            select(QuestionEmbedding.id, QuestionEmbedding.embedding)
            .where(QuestionEmbedding.question_id.isnot(None))
        ).fetchall()

        if not embeddings:
            logger.info("No embeddings to rebuild index from")
            return

        store = get_vector_store()
        ids = [row[0] for row in embeddings]
        vectors = [row[1] for row in embeddings]
        store.add_embeddings(ids, vectors)
        logger.info(f"Rebuilt vector index with {len(ids)} embeddings")
    finally:
        db.close()
