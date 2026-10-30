"""Durable practice-test generation queue consumed by the dedicated worker."""

import logging
import json
import time
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from db.database import SessionLocal, engine
from db.models import PracticeQuestion, PracticeTest, PracticeTestStatus

logger = logging.getLogger(__name__)
PRACTICE_GENERATION_WORKER_LOCK_ID = 731204893
MAX_LLM_RETRIES = 3


class PracticeGeneratedOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: StrictStr = Field(min_length=1, max_length=1000)
    is_correct: StrictBool


class PracticeGeneratedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: StrictStr
    question: StrictStr = Field(min_length=1, max_length=10_000)
    topic: StrictStr | None = Field(default=None, max_length=500)
    options: list[PracticeGeneratedOption] | None = Field(default=None, max_length=10)
    correct_answer: StrictStr | list[StrictStr] | None = None


class PracticeGeneratedQuestionSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    questions: list[PracticeGeneratedQuestion] = Field(min_length=1, max_length=100)


def _invoke_practice_generation(model, prompt: str) -> PracticeGeneratedQuestionSet:
    """Invoke the structured model, retrying transient/provider/schema failures."""
    structured_model = model.with_structured_output(PracticeGeneratedQuestionSet)
    last_error = None
    for attempt in range(1, MAX_LLM_RETRIES + 2):
        try:
            return PracticeGeneratedQuestionSet.model_validate(structured_model.invoke(prompt))
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Practice generation model attempt %s/%s failed: %s",
                attempt, MAX_LLM_RETRIES + 1, type(exc).__name__,
            )
    raise RuntimeError(
        f"Practice question generation failed after {MAX_LLM_RETRIES} retries"
    ) from last_error


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
    """Generate outside the DB transaction, then atomically persist validated questions."""
    from app.llms import get_chat_model
    from api.routers_practice import GENERATION_PROMPT, _validate_generated_questions

    with SessionLocal() as db:
        test = db.get(PracticeTest, test_id)
        if test is None or test.status != PracticeTestStatus.generating:
            return
        requested_count = test.question_count
        context = {
            "job_title": test.job_title,
            "job_description": test.job_description,
            "topics": test.topics,
            "difficulty": test.difficulty,
            "resume_text": test.resume_text,
        }

    prompt = GENERATION_PROMPT.format(
        question_count=requested_count,
        context_json=json.dumps(context, ensure_ascii=True),
    )
    generated = _invoke_practice_generation(get_chat_model(), prompt)
    questions = _validate_generated_questions(
        [question.model_dump() for question in generated.questions], requested_count
    )

    with SessionLocal() as db:
        test = db.query(PracticeTest).filter(PracticeTest.id == test_id).with_for_update().first()
        if test is None or test.status != PracticeTestStatus.generating:
            return
        if db.query(PracticeQuestion.id).filter(PracticeQuestion.practice_test_id == test_id).first():
            raise RuntimeError("Generating practice test already has persisted questions")
        for position, question in enumerate(questions, start=1):
            db.add(PracticeQuestion(
                practice_test_id=test_id,
                position=position,
                type=question["type"],
                question=question["question"],
                options=json.dumps(question["options"]) if question["options"] is not None else None,
                correct_answer=(
                    json.dumps(question["correct_answer"])
                    if isinstance(question["correct_answer"], list) else question["correct_answer"]
                ),
                topic=question["topic"],
            ))
        test.status = PracticeTestStatus.ready
        test.generation_claimed_at = None
        test.error_message = None
        db.commit()


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
            except Exception as exc:
                logger.exception("Practice test generation failed for %s", test_id)
                with SessionLocal() as db:
                    test = db.query(PracticeTest).filter(PracticeTest.id == test_id).with_for_update().first()
                    if test is not None and test.status == PracticeTestStatus.generating:
                        test.status = PracticeTestStatus.failed
                        test.error_message = f"Practice generation failed ({type(exc).__name__}). Retry generation."
                        db.commit()
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
