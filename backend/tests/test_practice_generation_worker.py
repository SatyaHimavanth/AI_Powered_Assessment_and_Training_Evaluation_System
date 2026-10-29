"""Fast local tests for persisted practice-generation claims."""

from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.practice_generation import (
    _claim_next_practice_test,
    _recover_interrupted_practice_tests,
)
from db.models import Base, PracticeTest, PracticeTestStatus, User, UserRole


def _queue_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[User.__table__, PracticeTest.__table__])
    return engine


def test_practice_generation_claim_is_persisted_until_released():
    engine = _queue_db()
    suffix = uuid4().hex
    user = User(
        username=f"practice_queue_{suffix}",
        email=f"practice_queue_{suffix}@example.test",
        contact_email=f"practice_queue_{suffix}@example.test",
        name="Practice Queue Test",
        hashed_password="unused-test-hash",
        role=UserRole.user,
    )
    test = PracticeTest(
        user=user,
        job_title="Queue recovery",
        difficulty="easy",
        question_count=10,
        status=PracticeTestStatus.generating,
    )

    try:
        with Session(engine) as db:
            db.add(test)
            db.commit()
            test_id = test.id

            assert _claim_next_practice_test(db) == test_id
            db.refresh(test)
            assert test.generation_claimed_at is not None
            assert _claim_next_practice_test(db) is None

            assert _recover_interrupted_practice_tests(db) == 1
            db.refresh(test)
            assert test.generation_claimed_at is None
            assert test.status == PracticeTestStatus.generating
            assert _claim_next_practice_test(db) == test_id
    finally:
        engine.dispose()
