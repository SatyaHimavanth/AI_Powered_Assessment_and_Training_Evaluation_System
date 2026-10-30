"""Batch metadata, failed-request cleanup and concurrency, without external models."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace
import threading
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy", reason="Run with backend dependencies")
from sqlalchemy import JSON

from test_realworld_regressions import application, scenario_engine  # noqa: F401

pytestmark = pytest.mark.regression


def call(function, *args, **kwargs):
    return asyncio.run(function(*args, **kwargs))


@pytest.fixture
def generation_app(application, monkeypatch):
    from api import routers_question_generation

    app = application
    monkeypatch.setattr(routers_question_generation, "SessionLocal", app.sessions)

    async def inline(callback, *args):
        return callback(*args)

    monkeypatch.setattr(routers_question_generation, "run_db_sync", inline)
    # These are lifecycle tests, not embedding quality tests.
    monkeypatch.setattr(app.models.QuestionEmbedding.__table__.c.embedding, "type", JSON())
    app.models.QuestionEmbedding.__table__.create(app.db.bind)
    app.generation = routers_question_generation
    return app


def batch(app, status="failed", **kwargs):
    m = app.models
    row = m.QuestionGenerationBatch(
        admin_id=app.user.id, source_text="Original persisted source", filename="notes.txt",
        topic_id=app.topic.id, question_type=m.QuestionType.multi_mcq,
        difficulty=m.Difficulty.hard, requested_count=10, auto_approve_unique=True,
        status=m.GenerationBatchStatus(status), error_message="Original failure" if status == "failed" else None,
        **kwargs,
    )
    app.db.add(row)
    app.db.commit()
    return row


def staging(app, row, status="pending", embedding=True):
    m = app.models
    staged = m.StagedQuestion(
        batch_id=row.id, question_type=row.question_type, difficulty=row.difficulty,
        topic_id=row.topic_id, question_text="A partially generated question",
        status=m.StagedQuestionStatus(status),
    )
    app.db.add(staged)
    app.db.flush()
    if embedding:
        app.db.add(m.QuestionEmbedding(staged_question_id=staged.id, embedding_text="Synthetic", embedding=[0.1, 0.2]))
    app.db.commit()
    return staged


@pytest.mark.parametrize("status", ["pending", "processing", "embedding", "similarity_check", "completed", "failed"])
def test_every_batch_state_exposes_topic_type_count_and_difficulty(generation_app, status):
    app = generation_app
    row = batch(app, status)
    result = call(app.generation.get_batch, row.id, app.user)
    validated = app.generation.BatchResponse(**result)
    assert validated.topic_name == app.topic.name
    assert validated.topic_id == app.topic.id
    assert validated.question_type == "multi_mcq"
    assert validated.requested_count == 10 and validated.difficulty == "hard"
    assert validated.can_retry == (status == "failed")


def test_create_and_list_return_the_same_batch_metadata_contract(generation_app):
    app = generation_app
    result = call(app.generation.start_generation, app.generation.GenerateBatchRequest(
        source_text="Synthetic source", topic_id=app.topic.id, question_type="single_mcq",
        difficulty="medium", count=12,
    ), app.user)
    created = app.generation.BatchResponse(**result)
    listed = app.generation.BatchListResponse(**call(app.generation.list_batches, app.user, page=1, page_size=20))
    assert created == listed.items[0]
    assert (created.topic_name, created.question_type, created.requested_count) == (app.topic.name, "single_mcq", 12)


def test_retry_reuses_persisted_inputs_and_discards_only_partial_staging(generation_app):
    app = generation_app
    m = app.models
    row = batch(app, total_generated=3, total_rejected=1, completed_at=datetime.now(timezone.utc))
    staging(app, row, "auto_rejected")
    other = batch(app)
    retained = staging(app, other)
    result = call(app.generation.retry_failed_batch, row.id, app.user)
    assert result["status"] == "pending" and result["error_message"] is None
    assert result["total_generated"] == result["total_approved"] == result["total_rejected"] == 0
    assert result["completed_at"] is None
    app.db.refresh(row)
    assert row.source_text == "Original persisted source" and row.auto_approve_unique
    assert row.topic_id == app.topic.id and row.requested_count == 10
    assert app.db.query(m.StagedQuestion).filter_by(batch_id=row.id).count() == 0
    assert app.db.query(m.QuestionEmbedding).one().staged_question_id == retained.id
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        call(app.generation.retry_failed_batch, row.id, app.user)
    assert exc.value.status_code == 409


@pytest.mark.parametrize("action", ["retry_failed_batch", "delete_failed_batch"])
@pytest.mark.parametrize("status", ["pending", "processing", "embedding", "similarity_check", "completed"])
def test_active_or_completed_batches_cannot_be_retried_or_deleted(generation_app, action, status):
    from fastapi import HTTPException
    app = generation_app
    row = batch(app, status)
    with pytest.raises(HTTPException) as exc:
        call(getattr(app.generation, action), row.id, app.user)
    assert exc.value.status_code == 409
    app.db.refresh(row)
    assert row.status.value == status


@pytest.mark.parametrize("action", ["retry_failed_batch", "delete_failed_batch"])
def test_failed_batch_actions_enforce_owner_and_missing_ids(generation_app, action):
    from fastapi import HTTPException
    app = generation_app
    row = batch(app)
    for batch_id, user in [(row.id, SimpleNamespace(id=uuid4())), (uuid4(), app.user)]:
        with pytest.raises(HTTPException) as exc:
            call(getattr(app.generation, action), batch_id, user)
        assert exc.value.status_code == 404
    assert app.db.query(app.models.QuestionGenerationBatch).count() == 1


def test_retry_rejects_batches_with_approved_questions_without_erasing_history(generation_app):
    from fastapi import HTTPException
    app = generation_app
    row = batch(app)
    staged = staging(app, row, "approved")
    response = call(app.generation.get_batch, row.id, app.user)
    assert not response["can_retry"] and "approved" in response["retry_blocked_reason"]
    with pytest.raises(HTTPException) as exc:
        call(app.generation.retry_failed_batch, row.id, app.user)
    assert exc.value.status_code == 409
    assert app.db.get(app.models.StagedQuestion, staged.id)
    assert app.db.query(app.models.QuestionEmbedding).count() == 1


def test_retry_missing_source_is_explicit(generation_app):
    from fastapi import HTTPException
    app = generation_app
    row = batch(app)
    row.source_text = None
    app.db.commit()
    with pytest.raises(HTTPException) as exc:
        call(app.generation.retry_failed_batch, row.id, app.user)
    assert exc.value.status_code == 409 and "source" in exc.value.detail


def test_delete_removes_failed_batch_and_embeddings_but_preserves_saved_bank_content(generation_app):
    app = generation_app
    m = app.models
    row = batch(app, total_approved=1)
    staged = staging(app, row, "approved")
    question = m.Question(
        topic_id=app.topic.id, type=row.question_type, difficulty=row.difficulty,
        question="A bank question that must not be deleted",
    )
    app.db.add(question)
    app.db.flush()
    bank_embedding = m.QuestionEmbedding(
        question_id=question.id, embedding_text="Bank embedding", embedding=[0.3, 0.4],
    )
    app.db.add(bank_embedding)
    app.db.commit()
    batch_id, staged_id = row.id, staged.id
    result = call(app.generation.delete_failed_batch, batch_id, app.user)
    assert "not changed" in result["message"]
    app.db.expire_all()
    assert app.db.get(m.QuestionGenerationBatch, batch_id) is None
    assert app.db.get(m.StagedQuestion, staged_id) is None
    assert app.db.get(m.Question, question.id) is not None
    assert app.db.query(m.QuestionEmbedding).one().id == bank_embedding.id


@pytest.mark.parametrize("actions", [("retry_failed_batch", "retry_failed_batch"), ("retry_failed_batch", "delete_failed_batch")])
def test_concurrent_failed_batch_actions_are_serialized(generation_app, actions):
    from fastapi import HTTPException
    app = generation_app
    if app.db.bind.dialect.name != "postgresql":
        pytest.skip("Requires PostgreSQL row locks and independent connections")
    row = batch(app)
    staging(app, row)
    batch_id, owner_id = row.id, app.user.id
    ready = threading.Barrier(2)

    def invoke(action):
        ready.wait(timeout=10)
        try:
            return call(getattr(app.generation, action), batch_id, SimpleNamespace(id=owner_id))
        except HTTPException as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(invoke, actions))
    assert sum(not isinstance(result, HTTPException) for result in results) == 1
    errors = [result.status_code for result in results if isinstance(result, HTTPException)]
    assert errors[0] in {404, 409}


def test_retry_can_be_processed_by_the_existing_worker_without_partial_duplicates(generation_app, monkeypatch):
    from core import question_generation
    app = generation_app
    m = app.models
    row = batch(app, total_generated=3)
    row.auto_approve_unique = False
    app.db.commit()
    staging(app, row)
    observed = {}

    def generate(**kwargs):
        observed.update(kwargs)
        return [{
            "question_text": f"Generated question {index}", "question_type": "multi_mcq",
            "difficulty": "hard", "options": [
                {"option_text": str(option), "is_correct": option < 2} for option in range(4)
            ],
        } for index in range(kwargs["count"])]

    def store(**kwargs):
        with app.sessions() as db:
            db.add(m.QuestionEmbedding(
                staged_question_id=kwargs["staged_question_id"],
                embedding_text=kwargs["text"], embedding=kwargs["embedding"],
            ))
            db.commit()

    monkeypatch.setattr(question_generation, "SessionLocal", app.sessions)
    monkeypatch.setattr(question_generation, "generate_questions_from_text", generate)
    monkeypatch.setattr(question_generation, "compute_embeddings", lambda texts: [[0.1, 0.2] for _ in texts])
    monkeypatch.setattr(question_generation, "check_similarity", lambda _text: (0.0, None, "unique"))
    monkeypatch.setattr(question_generation, "store_question_embedding", store)
    call(app.generation.retry_failed_batch, row.id, app.user)
    question_generation.process_generation_batch(row.id)
    app.db.refresh(row)
    assert row.status == m.GenerationBatchStatus.completed and row.total_generated == 10
    assert observed == {
        "source_text": "Original persisted source", "question_type": "multi_mcq",
        "difficulty": "hard", "topic_name": app.topic.name, "count": 10,
    }
    assert app.db.query(m.StagedQuestion).filter_by(batch_id=row.id).count() == 10
    assert app.db.query(m.QuestionEmbedding).count() == 10
