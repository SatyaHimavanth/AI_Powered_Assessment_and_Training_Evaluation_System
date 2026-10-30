"""Fast local tests for persisted practice-generation claims."""

from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.practice_generation import (
    MAX_LLM_RETRIES,
    PracticeGeneratedQuestionSet,
    _invoke_practice_generation,
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


def test_practice_generation_uses_structured_output_and_retries_provider_failures():
    class Runnable:
        calls = 0

        def invoke(self, _prompt):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("temporary provider failure")
            return {"questions": [{
                "type": "text",
                "question": "Explain a transaction.",
                "topic": "Databases",
                "options": None,
                "correct_answer": "A transaction is an atomic unit of work.",
            }]}

    class Model:
        def with_structured_output(self, schema):
            assert schema is PracticeGeneratedQuestionSet
            return runnable

    runnable = Runnable()
    result = _invoke_practice_generation(Model(), "prompt")
    assert result.questions[0].question == "Explain a transaction."
    assert runnable.calls == 2


def test_practice_generation_stops_after_three_retries():
    class Runnable:
        calls = 0

        def invoke(self, _prompt):
            self.calls += 1
            raise TimeoutError("provider unavailable")

    runnable = Runnable()

    class Model:
        def with_structured_output(self, _schema):
            return runnable

    import pytest

    with pytest.raises(RuntimeError, match="after 3 retries"):
        _invoke_practice_generation(Model(), "prompt")
    assert runnable.calls == MAX_LLM_RETRIES + 1 == 4
