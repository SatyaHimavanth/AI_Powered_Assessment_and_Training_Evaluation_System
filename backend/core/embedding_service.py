"""
Embedding service for question similarity checking.

Computes embeddings for questions and manages similarity searches using the
configured pgvector or JSON storage backend.
"""

import os
from typing import List, Optional, Tuple
from uuid import UUID

from app.llms import get_embeddings_model
from core.vector_store import EMBEDDING_DIM, search_question_embeddings
from db.database import SessionLocal
from db.models import QuestionEmbedding

# Similarity thresholds (cosine similarity 0.0 - 1.0)
THRESHOLD_HIGH_DUP = float(os.getenv("SIMILARITY_THRESHOLD_HIGH_DUP", "0.85"))
THRESHOLD_REVIEW = float(os.getenv("SIMILARITY_THRESHOLD_REVIEW", "0.70"))


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
    """Store an embedding using the configured database column type."""
    import uuid as uuid_mod

    if len(embedding) != EMBEDDING_DIM:
        raise ValueError(f"Expected embedding dimension {EMBEDDING_DIM}, got {len(embedding)}")

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
    return [
        (question_id, score, get_match_band(score))
        for question_id, score in search_question_embeddings(embedding, top_k=top_k)
    ]


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
