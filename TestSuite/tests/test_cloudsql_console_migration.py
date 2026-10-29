"""Rehearse console SQL against the exact deployed commit in disposable PG schemas."""

from pathlib import Path
import subprocess
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy", reason="Run with backend dependencies")
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import declarative_base

from test_realworld_regressions import scenario_engine  # noqa: F401

pytestmark = pytest.mark.regression
ROOT = Path(__file__).resolve().parents[2]
UPGRADE = ROOT / "backend" / "migrations" / "20261029_cloudsql_from_a02c14f.sql"


@pytest.fixture
def legacy_database(scenario_engine, monkeypatch):
    if scenario_engine.dialect.name != "postgresql":
        pytest.skip("Set REALWORLD_TEST_DATABASE_URL to a disposable PostgreSQL database")
    monkeypatch.syspath_prepend(str(ROOT / "backend"))
    monkeypatch.setenv("EMBEDDING_STORAGE_BACKEND", "json")
    from db import database

    legacy_base = declarative_base()
    source = subprocess.run(
        ["git", "--no-pager", "show", "a02c14f:backend/db/models.py"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    with monkeypatch.context() as legacy_context:
        legacy_context.setattr(database, "Base", legacy_base)
        exec(compile(source, "a02c14f:backend/db/models.py", "exec"), {"__name__": "legacy_models"})
    legacy_base.metadata.create_all(scenario_engine)
    ids = {key: uuid4() for key in ("user", "topic", "assessment", "question", "option", "link", "attempt", "answer", "practice", "embedding")}
    with scenario_engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO users (id, username, email, contact_email, name, hashed_password, role, is_active)
            VALUES (:user, 'legacy', 'legacy@example.test', 'contact@example.test', 'Legacy User', 'unchanged', 'user', true)
        """), ids)
        connection.execute(text("INSERT INTO topics(id, name) VALUES (:topic, 'Legacy topic')"), ids)
        connection.execute(text("""
            INSERT INTO questions(id, topic_id, type, question, difficulty)
            VALUES (:question, :topic, 'single_mcq', 'Historical question', 'easy')
        """), ids)
        connection.execute(text("""
            INSERT INTO question_options(id, question_id, option_text, is_correct)
            VALUES (:option, :question, 'Historical choice', true)
        """), ids)
        connection.execute(text("INSERT INTO assessments(id, title, duration) VALUES (:assessment, 'Historical assessment', 60)"), ids)
        connection.execute(text("""
            INSERT INTO assessment_questions(id, assessment_id, question_id)
            VALUES (:link, :assessment, :question)
        """), ids)
        connection.execute(text("""
            INSERT INTO assessment_topics(id, assessment_id, topic_id, question_type, difficulty, question_count)
            VALUES (:link, :assessment, :topic, 'single_mcq', 'easy', 1)
        """), ids)
        connection.execute(text("""
            INSERT INTO attempts(id, user_id, assessment_id, status, score)
            VALUES (:attempt, :user, :assessment, 'completed', 100)
        """), ids)
        connection.execute(text("""
            INSERT INTO answers(id, attempt_id, question_id, answer, score)
            VALUES (:answer, :attempt, :question, :saved_answer, 1)
        """), {**ids, "saved_answer": str(ids["option"])})
        connection.execute(text("""
            INSERT INTO practice_tests(id, user_id, job_title, difficulty, status, question_count)
            VALUES (:practice, :user, 'Historical practice', 'easy', 'completed', 10)
        """), ids)
        connection.execute(text("""
            INSERT INTO question_embeddings(id, question_id, embedding_text, embedding)
            VALUES (:embedding, :question, 'Historical embedding', '[0.1, 0.2]'::json)
        """), ids)
    return scenario_engine, ids


def run_upgrade(engine):
    with engine.begin() as connection:
        connection.execute(text(UPGRADE.read_text(encoding="utf-8")))


def test_console_upgrade_preserves_legacy_data_and_can_be_repeated(legacy_database):
    engine, ids = legacy_database
    before = {}
    with engine.connect() as connection:
        for table in ("users", "questions", "question_options", "assessments", "answers", "question_embeddings"):
            before[table] = connection.execute(text(f"SELECT row_to_json(row)::text FROM {table} AS row ORDER BY id")).scalars().all()
    run_upgrade(engine)
    run_upgrade(engine)
    with engine.connect() as connection:
        for table, rows in before.items():
            assert connection.execute(text(f"SELECT row_to_json(row)::text FROM {table} AS row ORDER BY id")).scalars().all() == rows
        assert connection.execute(text("SELECT score FROM attempts WHERE id = :attempt"), ids).scalar_one() == 100
        assert connection.execute(text("SELECT position FROM assessment_questions")).scalar_one() == 0
        assert connection.execute(text("SELECT active_seconds FROM attempts")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM refresh_sessions")).scalar_one() == 0
    from db.models import Base
    from db.schema_migrations import MIGRATION_VERSIONS, assert_migrations_applied

    assert_migrations_applied(engine)
    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        existing = {column["name"]: column for column in inspector.get_columns(table.name)}
        for column in table.columns:
            assert column.name in existing, (table.name, column.name)
            if not column.nullable:
                assert not existing[column.name]["nullable"], (table.name, column.name)
    with engine.connect() as connection:
        versions = set(connection.execute(text("SELECT version FROM app_schema_migrations")).scalars())
    assert versions == set(MIGRATION_VERSIONS)


@pytest.mark.parametrize("invalid", ["null_owner", "duplicate_topic_config", "missing_assessment"])
def test_console_upgrade_rolls_back_without_deleting_incompatible_legacy_rows(legacy_database, invalid):
    engine, ids = legacy_database
    with engine.begin() as connection:
        if invalid == "null_owner":
            connection.execute(text("UPDATE answers SET question_id = NULL WHERE id = :answer"), ids)
        elif invalid == "duplicate_topic_config":
            connection.execute(text("""
                INSERT INTO assessment_topics(id, assessment_id, topic_id, question_type, difficulty, question_count)
                VALUES (:new_id, :assessment, :topic, 'single_mcq', 'easy', 2)
            """), {**ids, "new_id": uuid4()})
        else:
            connection.execute(text("UPDATE assessment_questions SET assessment_id = NULL WHERE id = :link"), ids)
    with pytest.raises(DBAPIError):
        run_upgrade(engine)
    inspector = inspect(engine)
    assert "app_schema_migrations" not in inspector.get_table_names()
    assert "position" not in {column["name"] for column in inspector.get_columns("assessment_questions")}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM answers")).scalar_one() == 1
        assert connection.execute(text("SELECT count(*) FROM assessment_topics")).scalar_one() == (
            2 if invalid == "duplicate_topic_config" else 1
        )
