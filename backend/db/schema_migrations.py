"""Small idempotent PostgreSQL schema upgrades for installations predating Alembic."""

from contextlib import contextmanager
import os

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.engine import Engine

MIGRATION_VERSIONS = (
    "20261028_assessment_question_positions",
    "20261028_refresh_sessions",
    "20261028_application_uniqueness_and_vector_index",
    "20261028_embedding_storage_backend",
    "20261028_association_integrity",
    "20261028_query_indexes",
    "20261028_practice_generation_claims",
    "20261028_attempt_integrity_events",
    "20261028_individual_assessment_assignments",
    "20261028_attempt_active_time",
    "20261028_attempt_active_time_precision",
    "20261029_attempt_offline_sync_grace",
)


def assert_migrations_applied(engine: Engine) -> None:
    """Fail startup when the one-shot migration command has not completed."""
    try:
        with engine.connect() as connection:
            applied = connection.execute(text(
                "SELECT version FROM app_schema_migrations"
            )).scalars().all()
    except SQLAlchemyError as exc:
        raise RuntimeError(
            "Database migration history is missing or unreadable; run `python -m db.migrate`."
        ) from exc
    missing = sorted(set(MIGRATION_VERSIONS) - set(applied))
    if missing:
        raise RuntimeError(
            "Database migrations are pending: " + ", ".join(missing)
            + ". Run `python -m db.migrate` before starting the API."
        )


@contextmanager
def serialized_startup(engine: Engine):
    """Serialize schema setup and default seeding across API replicas."""
    connection = engine.connect()
    locked = engine.dialect.name == "postgresql"
    try:
        if locked:
            connection.execute(text("SELECT pg_advisory_lock(:lock_id)"), {"lock_id": 731204890})
            connection.commit()
        yield
    finally:
        if locked:
            try:
                connection.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": 731204890})
                connection.commit()
            finally:
                connection.close()
        else:
            connection.close()


def upgrade_refresh_sessions(engine: Engine) -> None:
    """Create persistent refresh-token state before the auth routes are served."""
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS refresh_sessions ("
            "jti VARCHAR(36) PRIMARY KEY, "
            "user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
            "expires_at TIMESTAMP WITH TIME ZONE NOT NULL, "
            "created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "revoked_at TIMESTAMP WITH TIME ZONE NULL)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_refresh_sessions_user_id "
            "ON refresh_sessions (user_id)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_refresh_sessions_expires_at "
            "ON refresh_sessions (expires_at)"
        ))


def upgrade_application_uniqueness(engine: Engine) -> None:
    """Add safe uniqueness invariants after refusing to discard duplicate data."""
    if engine.dialect.name != "postgresql":
        return

    indexes = [
        ("uq_topics_name_safe", "topics", "name", "name IS NOT NULL"),
        ("uq_answers_attempt_question_safe", "answers", "attempt_id, question_id", "question_id IS NOT NULL"),
        ("uq_answers_attempt_item_safe", "answers", "attempt_id, assessment_item_id", "assessment_item_id IS NOT NULL"),
        ("uq_practice_answers_question_safe", "practice_answers", "question_id", "question_id IS NOT NULL"),
        ("uq_batch_users_batch_user", "batch_users", "batch_id, user_id", None),
        ("uq_assignments_assessment_batch", "assignments", "assessment_id, batch_id", None),
        ("uq_assessment_questions_global", "assessment_questions", "assessment_id, question_id", "question_id IS NOT NULL"),
        ("uq_assessment_questions_item", "assessment_questions", "assessment_id, assessment_item_id", "assessment_item_id IS NOT NULL"),
        ("uq_assessment_sections_global", "assessment_question_sections", "assessment_id, question_id", "question_id IS NOT NULL"),
        ("uq_assessment_sections_item", "assessment_question_sections", "assessment_id, assessment_item_id", "assessment_item_id IS NOT NULL"),
        ("uq_interview_response_session_turn", "interview_response_evaluations", "session_id, turn_index", None),
        ("uq_question_embeddings_question", "question_embeddings", "question_id", "question_id IS NOT NULL"),
        ("uq_question_embeddings_staged", "question_embeddings", "staged_question_id", "staged_question_id IS NOT NULL"),
        ("uq_active_attempt_assessment_user", "attempts", "assessment_id, user_id", "status = 'in_progress'"),
    ]
    with engine.begin() as connection:
        for name, table, columns, predicate in indexes:
            existing_model_constraint = {
                "uq_topics_name_safe": "topics_name_key",
                "uq_answers_attempt_question_safe": "uq_answer_attempt_question",
                "uq_answers_attempt_item_safe": "uq_answer_attempt_item",
                "uq_practice_answers_question_safe": "practice_answers_question_id_key",
            }.get(name)
            if existing_model_constraint and connection.execute(
                text("SELECT to_regclass(:index_name)"),
                {"index_name": existing_model_constraint},
            ).scalar():
                continue
            if connection.execute(
                text("SELECT to_regclass(:index_name)"),
                {"index_name": name},
            ).scalar():
                continue
            where = f" WHERE {predicate}" if predicate else ""
            filter_sql = f" AND ({predicate})" if predicate else ""
            duplicate_groups = connection.execute(text(
                f"SELECT {columns}, COUNT(*) AS duplicate_count FROM {table} "
                f"WHERE TRUE{filter_sql} GROUP BY {columns} "
                "HAVING COUNT(*) > 1 LIMIT 10"
            )).mappings().all()
            if duplicate_groups:
                raise RuntimeError(
                    f"Cannot add {name}: duplicate rows exist in {table}; "
                    f"sample duplicate groups: {duplicate_groups}. "
                    "Inventory and reconcile those rows before retrying the migration."
                )
            connection.execute(text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table} ({columns}){where}"
            ))
        if (
            os.getenv("EMBEDDING_STORAGE_BACKEND", "pgvector").strip().lower() == "pgvector"
            and int(os.getenv("EMBEDDING_DIM", "1536")) <= 2000
        ):
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_question_embeddings_hnsw_cosine "
                "ON question_embeddings USING hnsw (embedding vector_cosine_ops) "
                "WHERE question_id IS NOT NULL"
            ))


def upgrade_embedding_storage(engine: Engine) -> None:
    """Convert existing pgvector columns when JSON embedding mode is selected."""
    if (
        engine.dialect.name != "postgresql"
        or os.getenv("EMBEDDING_STORAGE_BACKEND", "pgvector").strip().lower() != "json"
    ):
        return
    with engine.begin() as connection:
        current_type = connection.execute(text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = current_schema() "
            "AND table_name = 'question_embeddings' AND column_name = 'embedding'"
        )).scalar()
        if current_type and current_type not in {"json", "jsonb"}:
            connection.execute(text(
                "DROP INDEX IF EXISTS ix_question_embeddings_hnsw_cosine"
            ))
            connection.execute(text(
                "ALTER TABLE question_embeddings ALTER COLUMN embedding TYPE json "
                "USING embedding::text::json"
            ))


def upgrade_association_integrity(engine: Engine) -> None:
    """Enforce required relationship columns and exactly-one-owner invariants.

    Existing data is checked first. Any invalid rows stop this migration without
    deleting or rewriting them; operators must reconcile them explicitly.
    """
    if engine.dialect.name != "postgresql":
        return

    required = {
        "batch_users": ("batch_id", "user_id"),
        "assessment_topics": ("assessment_id", "topic_id"),
        "assessment_questions": ("assessment_id",),
        "assessment_question_sections": ("assessment_id",),
        "assignments": ("assessment_id", "batch_id"),
        "attempts": ("user_id", "assessment_id"),
        "answers": ("attempt_id",),
    }
    source_expressions = {
        "assessment_questions": "(question_id IS NULL) <> (assessment_item_id IS NULL)",
        "assessment_question_sections": "(question_id IS NULL) <> (assessment_item_id IS NULL)",
        "answers": "(question_id IS NULL) <> (assessment_item_id IS NULL)",
        "question_embeddings": "(question_id IS NULL) <> (staged_question_id IS NULL)",
    }
    checks = {
        "assessment_questions": ("ck_assessment_questions_exactly_one_source", source_expressions["assessment_questions"]),
        "assessment_question_sections": ("ck_assessment_question_sections_exactly_one_source", source_expressions["assessment_question_sections"]),
        "answers": ("ck_answers_exactly_one_source", source_expressions["answers"]),
        "question_embeddings": ("ck_question_embeddings_exactly_one_owner", source_expressions["question_embeddings"]),
    }
    unique_indexes = (
        ("uq_assessment_topics_config", "assessment_topics", "assessment_id, topic_id, question_type, difficulty", None),
        ("uq_assessment_questions_position", "assessment_questions", "assessment_id, position", None),
    )

    with engine.begin() as connection:
        for table, columns in required.items():
            for column in columns:
                null_count = connection.execute(text(
                    f"SELECT count(*) FROM {table} WHERE {column} IS NULL"
                )).scalar_one()
                if null_count:
                    raise RuntimeError(
                        f"Cannot make {table}.{column} required: "
                        f"{null_count} existing row(s) have no value. Reconcile before retrying."
                    )

        for table, expression in source_expressions.items():
            invalid_count = connection.execute(text(
                f"SELECT count(*) FROM {table} WHERE NOT ({expression})"
            )).scalar_one()
            if invalid_count:
                raise RuntimeError(
                    f"Cannot enforce source ownership in {table}: "
                    f"{invalid_count} existing row(s) have zero or multiple owners. "
                    "Reconcile before retrying."
                )

        topic_duplicates = connection.execute(text(
            "SELECT count(*) FROM (SELECT assessment_id, topic_id, question_type, difficulty "
            "FROM assessment_topics GROUP BY assessment_id, topic_id, question_type, difficulty "
            "HAVING count(*) > 1) AS duplicates"
        )).scalar_one()
        if topic_duplicates:
            raise RuntimeError(
                f"Cannot add uq_assessment_topics_config: {topic_duplicates} duplicate groups exist."
            )

        for table, columns in required.items():
            for column in columns:
                is_nullable = connection.execute(text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = :table "
                    "AND column_name = :column"
                ), {"table": table, "column": column}).scalar_one()
                if is_nullable == "YES":
                    connection.execute(text(
                        f"ALTER TABLE {table} ALTER COLUMN {column} SET NOT NULL"
                    ))

        for table, (name, expression) in checks.items():
            exists = connection.execute(text(
                "SELECT 1 FROM pg_constraint WHERE conname = :name "
                "AND conrelid = to_regclass(:table)"
            ), {"name": name, "table": table}).first()
            if not exists:
                connection.execute(text(
                    f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expression})"
                ))

        for name, table, columns, predicate in unique_indexes:
            if connection.execute(text("SELECT to_regclass(:name)"), {"name": name}).scalar():
                continue
            groups = connection.execute(text(
                f"SELECT count(*) FROM (SELECT {columns} FROM {table} GROUP BY {columns} "
                "HAVING count(*) > 1) AS duplicates"
            )).scalar_one()
            if groups:
                raise RuntimeError(f"Cannot add {name}: {groups} duplicate groups exist.")
            connection.execute(text(
                f"CREATE UNIQUE INDEX {name} ON {table} ({columns})"
            ))


def upgrade_query_indexes(engine: Engine) -> None:
    """Provision composites matching existing list, queue and history queries."""
    if engine.dialect.name != "postgresql":
        return
    indexes = (
        ("ix_assignments_batch_id", "assignments", "batch_id"),
        ("ix_attempts_user_status_started", "attempts", "user_id, status, started_at"),
        ("ix_attempts_assessment_status", "attempts", "assessment_id, status"),
        ("ix_evaluation_jobs_status_created", "evaluation_jobs", "status, created_at"),
        ("ix_practice_tests_user_created", "practice_tests", "user_id, created_at"),
        ("ix_practice_questions_test_position", "practice_questions", "practice_test_id, position"),
        ("ix_interview_sessions_user_status_created", "interview_sessions", "user_id, status, created_at"),
        ("ix_interview_sessions_template_status_created", "interview_sessions", "template_id, status, created_at"),
        ("ix_generation_batches_status_created", "question_generation_batches", "status, created_at"),
        ("ix_staged_questions_batch_status_created", "staged_questions", "batch_id, status, created_at"),
    )
    with engine.begin() as connection:
        for name, table, columns in indexes:
            if connection.execute(text("SELECT to_regclass(:name)"), {"name": name}).scalar():
                continue
            connection.execute(text(
                f"CREATE INDEX {name} ON {table} ({columns})"
            ))


def upgrade_practice_generation_claims(engine: Engine) -> None:
    """Persist practice-generation worker claims for restart recovery."""
    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE practice_tests ADD COLUMN IF NOT EXISTS "
            "generation_claimed_at TIMESTAMP WITH TIME ZONE NULL"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_practice_tests_generation_claimed_at "
            "ON practice_tests (generation_claimed_at)"
        ))


def upgrade_attempt_integrity_events(engine: Engine) -> None:
    """Record typed, deduplicated advisory signals without changing attempt outcomes."""
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS attempt_integrity_events ("
            "id UUID PRIMARY KEY, "
            "attempt_id UUID NOT NULL REFERENCES attempts(id) ON DELETE CASCADE, "
            "event_id UUID NOT NULL, "
            "event_type VARCHAR(32) NOT NULL CHECK (event_type IN "
            "('focus_lost','fullscreen_exit','escape_key','devtools_shortcut')), "
            "created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "CONSTRAINT uq_attempt_integrity_event_id UNIQUE (attempt_id,event_id))"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_attempt_integrity_events_attempt_created "
            "ON attempt_integrity_events (attempt_id,created_at)"
        ))


def upgrade_individual_assessment_assignments(engine: Engine) -> None:
    """Create the additive direct-user assignment table for existing databases."""
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS assessment_user_assignments ("
            "id UUID PRIMARY KEY, "
            "assessment_id UUID NOT NULL REFERENCES assessments(id) ON DELETE CASCADE, "
            "user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
            "CONSTRAINT uq_assessment_user_assignments_target UNIQUE (assessment_id,user_id))"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_assessment_user_assignments_user_id "
            "ON assessment_user_assignments (user_id)"
        ))


def upgrade_attempt_active_time(engine: Engine) -> None:
    """Persist server-accounted active duration and heartbeat lease state."""
    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE attempts ADD COLUMN IF NOT EXISTS active_seconds INTEGER NOT NULL DEFAULT 0"
        ))
        connection.execute(text(
            "ALTER TABLE attempts ADD COLUMN IF NOT EXISTS active_started_at TIMESTAMP WITH TIME ZONE NULL"
        ))
        connection.execute(text(
            "ALTER TABLE attempts ADD COLUMN IF NOT EXISTS active_heartbeat_at TIMESTAMP WITH TIME ZONE NULL"
        ))


def upgrade_attempt_active_time_precision(engine: Engine) -> None:
    """Retain sub-second heartbeat intervals without systematic timer drift."""
    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE attempts ALTER COLUMN active_seconds TYPE DOUBLE PRECISION "
            "USING active_seconds::DOUBLE PRECISION"
        ))


def upgrade_attempt_offline_sync_grace(engine: Engine) -> None:
    """Hold evaluation briefly so locally buffered answers can sync after expiry."""
    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE attempts ADD COLUMN IF NOT EXISTS sync_deadline_at "
            "TIMESTAMP WITH TIME ZONE NULL"
        ))


def upgrade_assessment_question_positions(engine: Engine) -> None:
    """Persist assessment order, retaining the previously observed UUID order for old rows."""
    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE assessment_questions "
            "ADD COLUMN IF NOT EXISTS position INTEGER"
        ))
        connection.execute(text(
            "WITH ordered AS ("
            " SELECT id, ROW_NUMBER() OVER ("
            "   PARTITION BY assessment_id "
            "   ORDER BY COALESCE(question_id, assessment_item_id), id"
            " ) - 1 AS position"
            " FROM assessment_questions WHERE position IS NULL"
            ") UPDATE assessment_questions AS target "
            "SET position = ordered.position FROM ordered WHERE target.id = ordered.id"
        ))
        connection.execute(text(
            "ALTER TABLE assessment_questions "
            "ALTER COLUMN position SET DEFAULT 0"
        ))
        connection.execute(text(
            "ALTER TABLE assessment_questions "
            "ALTER COLUMN position SET NOT NULL"
        ))
