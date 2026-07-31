import pytest
from sqlalchemy import JSON

from core.vector_store import (
    EMBEDDING_STORAGE_BACKEND,
    _coerce_embedding,
    _cosine_similarity,
)
from db.models import QuestionEmbedding


def test_json_mode_uses_json_database_column():
    if EMBEDDING_STORAGE_BACKEND != "json":
        pytest.skip("JSON embedding backend is not enabled")
    assert isinstance(QuestionEmbedding.__table__.c.embedding.type, JSON)


def test_cosine_similarity_orders_equivalent_and_opposite_vectors():
    assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert _cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_json_embedding_coercion_and_zero_vector():
    assert _coerce_embedding("[1, 2.5]") == [1.0, 2.5]
    assert _cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


def test_cosine_similarity_rejects_mismatched_dimensions():
    with pytest.raises(ValueError, match="dimensions"):
        _cosine_similarity([1.0], [1.0, 2.0])
