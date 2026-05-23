"""
Vector store abstraction layer.

Provides a unified interface for storing and querying question embeddings.
Uses pgvector extension when available, falls back to FAISS in-memory/file index.

Once pgvector is installed on the database server, remove the FAISS fallback by:
1. Delete the FaissVectorStore class
2. Remove faiss-cpu from pyproject.toml
3. Delete the FAISS_INDEX_DIR and any .faiss/.pkl files
"""

import os
import logging
import pickle
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Tuple
from uuid import UUID

import numpy as np
from sqlalchemy import text

from db.database import SessionLocal, engine

logger = logging.getLogger(__name__)

# Where to persist the FAISS index on disk
FAISS_INDEX_DIR = Path(os.getenv("FAISS_INDEX_DIR", "data/faiss_index"))

# Embedding dimension (Azure text-embedding-3-small = 1536)
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "1536"))


def _check_pgvector_available() -> bool:
    """Check if the pgvector extension is installed and usable."""
    try:
        db = SessionLocal()
        try:
            result = db.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
            row = result.fetchone()
            if row:
                return True
            # Try to create it (may fail due to permissions)
            db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            db.commit()
            return True
        except Exception:
            db.rollback()
            return False
        finally:
            db.close()
    except Exception:
        return False


class BaseVectorStore(ABC):
    """Abstract interface for vector similarity search."""

    @abstractmethod
    def add_embeddings(self, ids: List[UUID], embeddings: List[List[float]]) -> None:
        """Add embeddings with their associated question IDs."""
        ...

    @abstractmethod
    def remove_embeddings(self, ids: List[UUID]) -> None:
        """Remove embeddings by question IDs."""
        ...

    @abstractmethod
    def search(self, query_embedding: List[float], top_k: int = 5) -> List[Tuple[UUID, float]]:
        """
        Search for most similar embeddings.
        Returns list of (question_id, similarity_score) ordered by descending similarity.
        Score is cosine similarity (0.0 to 1.0).
        """
        ...

    @abstractmethod
    def count(self) -> int:
        """Return number of stored embeddings."""
        ...


class PgVectorStore(BaseVectorStore):
    """Vector store using PostgreSQL pgvector extension."""

    def __init__(self):
        # Ensure the question_embeddings table uses vector type
        db = SessionLocal()
        try:
            db.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            db.commit()
            # Ensure column type is vector
            db.execute(text(f"""
                ALTER TABLE question_embeddings
                ALTER COLUMN embedding TYPE vector({EMBEDDING_DIM})
                USING embedding::vector({EMBEDDING_DIM})
            """))
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    def add_embeddings(self, ids: List[UUID], embeddings: List[List[float]]) -> None:
        # Embeddings are stored via SQLAlchemy model insert — this is a no-op
        # since we store them directly in the question_embeddings table.
        pass

    def remove_embeddings(self, ids: List[UUID]) -> None:
        db = SessionLocal()
        try:
            for qid in ids:
                db.execute(
                    text("DELETE FROM question_embeddings WHERE question_id = :qid"),
                    {"qid": str(qid)},
                )
            db.commit()
        finally:
            db.close()

    def search(self, query_embedding: List[float], top_k: int = 5) -> List[Tuple[UUID, float]]:
        db = SessionLocal()
        try:
            vec_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
            # Use cosine distance operator (<=>), convert to similarity
            result = db.execute(
                text("""
                    SELECT question_id,
                           1 - (embedding <=> :vec::vector) AS similarity
                    FROM question_embeddings
                    WHERE question_id IS NOT NULL
                    ORDER BY embedding <=> :vec::vector
                    LIMIT :k
                """),
                {"vec": vec_str, "k": top_k},
            )
            rows = result.fetchall()
            return [(UUID(str(row[0])), float(row[1])) for row in rows]
        finally:
            db.close()

    def count(self) -> int:
        db = SessionLocal()
        try:
            result = db.execute(text("SELECT COUNT(*) FROM question_embeddings WHERE question_id IS NOT NULL"))
            return result.scalar() or 0
        finally:
            db.close()


class FaissVectorStore(BaseVectorStore):
    """
    FAISS-based fallback vector store.

    TEMPORARY: Remove this class once pgvector extension is available.
    To remove:
    1. Delete this class
    2. Remove `faiss-cpu` from pyproject.toml
    3. Delete FAISS_INDEX_DIR folder
    4. Update get_vector_store() to always return PgVectorStore
    """

    def __init__(self):
        import faiss

        self._index_path = FAISS_INDEX_DIR / "index.faiss"
        self._ids_path = FAISS_INDEX_DIR / "ids.pkl"
        FAISS_INDEX_DIR.mkdir(parents=True, exist_ok=True)

        if self._index_path.exists() and self._ids_path.exists():
            self._index = faiss.read_index(str(self._index_path))
            with open(self._ids_path, "rb") as f:
                self._ids: List[str] = pickle.load(f)
        else:
            self._index = faiss.IndexFlatIP(EMBEDDING_DIM)  # Inner product (cosine on normalized vecs)
            self._ids = []

    def _save(self):
        import faiss
        faiss.write_index(self._index, str(self._index_path))
        with open(self._ids_path, "wb") as f:
            pickle.dump(self._ids, f)

    def _normalize(self, vectors: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1
        return vectors / norms

    def add_embeddings(self, ids: List[UUID], embeddings: List[List[float]]) -> None:
        if not ids:
            return
        vectors = np.array(embeddings, dtype=np.float32)
        vectors = self._normalize(vectors)
        self._index.add(vectors)
        self._ids.extend([str(uid) for uid in ids])
        self._save()

    def remove_embeddings(self, ids: List[UUID]) -> None:
        if not ids:
            return
        import faiss

        ids_to_remove = {str(uid) for uid in ids}
        # Rebuild index without removed IDs
        keep_indices = [i for i, uid in enumerate(self._ids) if uid not in ids_to_remove]
        if len(keep_indices) == len(self._ids):
            return  # Nothing to remove

        if keep_indices:
            # Reconstruct vectors for kept items
            vectors = np.array([self._index.reconstruct(i) for i in keep_indices], dtype=np.float32)
            new_index = faiss.IndexFlatIP(EMBEDDING_DIM)
            new_index.add(vectors)
            self._index = new_index
            self._ids = [self._ids[i] for i in keep_indices]
        else:
            self._index = faiss.IndexFlatIP(EMBEDDING_DIM)
            self._ids = []
        self._save()

    def search(self, query_embedding: List[float], top_k: int = 5) -> List[Tuple[UUID, float]]:
        if self._index.ntotal == 0:
            return []
        query = np.array([query_embedding], dtype=np.float32)
        query = self._normalize(query)
        k = min(top_k, self._index.ntotal)
        scores, indices = self._index.search(query, k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._ids):
                continue
            results.append((UUID(self._ids[idx]), float(score)))
        return results

    def count(self) -> int:
        return self._index.ntotal


# Singleton
_vector_store_instance: BaseVectorStore | None = None
_pgvector_available: bool | None = None


def is_pgvector_available() -> bool:
    """Check and cache whether pgvector extension is available."""
    global _pgvector_available
    if _pgvector_available is None:
        _pgvector_available = _check_pgvector_available()
        if _pgvector_available:
            logger.info("pgvector extension detected — using PostgreSQL vector search")
        else:
            logger.warning("pgvector extension NOT available — falling back to FAISS index")
    return _pgvector_available


def get_vector_store() -> BaseVectorStore:
    """Get the singleton vector store instance."""
    global _vector_store_instance
    if _vector_store_instance is None:
        if is_pgvector_available():
            _vector_store_instance = PgVectorStore()
        else:
            _vector_store_instance = FaissVectorStore()
    return _vector_store_instance
