"""Durable practice-test generation queue consumed by the dedicated worker."""

import logging
import time
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from db.database import SessionLocal, engine
from db.models import PracticeTest, PracticeTestStatus

logger = logging.getLogger(__name__)
PRACTICE_GENERATION_WORKER_LOCK_ID = 731204893


def _recover_interrupted_practice_tests(db: Session) -> int:
    """Release persisted claims after the prior singleton worker has exited."""
    recovered = (
        db.query(PracticeTest)
        .filter(
            PracticeTest.status == PracticeTestStatus.generating,
            PracticeTest.generation_claimed_at.is_not(None),
        )
        .update({PracticeTest.generation_claimed_at: None}, synchronize_session=False)
    )
    db.commit()
    return recovered


def _claim_next_practice_test(db: Session) -> UUID | None:
    """Atomically claim one queued practice test; callers commit the claim."""
    test = (
        db.query(PracticeTest)
        .filter(
            PracticeTest.status == PracticeTestStatus.generating,
            PracticeTest.generation_claimed_at.is_(None),
        )
        .order_by(PracticeTest.created_at.asc())
        .with_for_update(skip_locked=True)
        .first()
    )
    if test is None:
        return None
    test.generation_claimed_at = datetime.now(timezone.utc)
    db.commit()
    return test.id


def _generate_claimed_practice_test(test_id: UUID) -> None:
    """Run the existing validated generator for a durably claimed test."""
    # Keep provider/prompt validation in the API module until it is extracted
    # into the shared domain service. This import is delayed to avoid loading
    # the API router while the queue module is imported by worker startup.
    from api.routers_practice import _generate_questions_background

    _generate_questions_background(test_id)


def process_practice_generation_queue(poll_interval: int = 5) -> None:
    """Consume queued practice tests under a PostgreSQL singleton lock."""
    if engine.dialect.name != "postgresql":
        logger.error("Practice generation worker requires PostgreSQL advisory locks")
        return

    lock_connection = None
    while True:
        try:
            if lock_connection is None:
                lock_connection = engine.connect()
                acquired = bool(lock_connection.execute(
                    text("SELECT pg_try_advisory_lock(:lock_id)"),
                    {"lock_id": PRACTICE_GENERATION_WORKER_LOCK_ID},
                ).scalar())
                lock_connection.commit()
                if not acquired:
                    lock_connection.close()
                    lock_connection = None
                    time.sleep(poll_interval)
                    continue

                with SessionLocal() as recovery_db:
                    recovered = _recover_interrupted_practice_tests(recovery_db)
                    if recovered:
                        logger.warning("Released %s interrupted practice generation claim(s)", recovered)
            else:
                lock_connection.execute(text("SELECT 1"))
                lock_connection.commit()

            with SessionLocal() as db:
                test_id = _claim_next_practice_test(db)

            if test_id is None:
                time.sleep(poll_interval)
                continue

            try:
                _generate_claimed_practice_test(test_id)
            except Exception:
                logger.exception("Practice test generation failed for %s", test_id)
            finally:
                with SessionLocal() as db:
                    test = db.query(PracticeTest).filter(PracticeTest.id == test_id).first()
                    if test is not None:
                        test.generation_claimed_at = None
                        db.commit()
        except Exception:
            logger.exception("Practice generation worker failed; it will retry")
            if lock_connection is not None:
                lock_connection.close()
                lock_connection = None
            time.sleep(poll_interval)
