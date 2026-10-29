"""Run the application's ordered, idempotent PostgreSQL schema migrations."""

from sqlalchemy import text

from db.database import Base, engine
from db import models  # noqa: F401 - register all mapped tables
from db.schema_migrations import (
    MIGRATION_VERSIONS,
    serialized_startup,
    upgrade_application_uniqueness,
    upgrade_assessment_question_positions,
    upgrade_association_integrity,
    upgrade_query_indexes,
    upgrade_practice_generation_claims,
    upgrade_attempt_integrity_events,
    upgrade_individual_assessment_assignments,
    upgrade_embedding_storage,
    upgrade_refresh_sessions,
    upgrade_attempt_active_time,
    upgrade_attempt_active_time_precision,
    upgrade_attempt_offline_sync_grace,
)
from core.vector_store import ensure_pgvector_ready


def main() -> None:
    with serialized_startup(engine):
        ensure_pgvector_ready()
        # create_all bootstraps a new database; the ordered SQL upgrades below
        # handle the known alterations for existing installations.
        Base.metadata.create_all(bind=engine)
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE IF NOT EXISTS app_schema_migrations ("
                "version VARCHAR(120) PRIMARY KEY, "
                "applied_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            ))

        steps = (
            (MIGRATION_VERSIONS[0], upgrade_assessment_question_positions),
            (MIGRATION_VERSIONS[1], upgrade_refresh_sessions),
            (MIGRATION_VERSIONS[2], upgrade_application_uniqueness),
            (MIGRATION_VERSIONS[3], upgrade_embedding_storage),
            (MIGRATION_VERSIONS[4], upgrade_association_integrity),
            (MIGRATION_VERSIONS[5], upgrade_query_indexes),
            (MIGRATION_VERSIONS[6], upgrade_practice_generation_claims),
            (MIGRATION_VERSIONS[7], upgrade_attempt_integrity_events),
            (MIGRATION_VERSIONS[8], upgrade_individual_assessment_assignments),
            (MIGRATION_VERSIONS[9], upgrade_attempt_active_time),
            (MIGRATION_VERSIONS[10], upgrade_attempt_active_time_precision),
            (MIGRATION_VERSIONS[11], upgrade_attempt_offline_sync_grace),
        )
        for version, upgrade in steps:
            with engine.connect() as connection:
                applied = connection.execute(
                    text("SELECT 1 FROM app_schema_migrations WHERE version = :version"),
                    {"version": version},
                ).first()
            if applied:
                continue

            upgrade(engine)
            with engine.begin() as connection:
                connection.execute(
                    text("INSERT INTO app_schema_migrations(version) VALUES (:version)"),
                    {"version": version},
                )
            print(f"[OK] Applied migration {version}")


if __name__ == "__main__":
    main()
