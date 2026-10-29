"""Bounded synthetic live LLM checks; never read candidate data or require embeddings."""

import json
import os
from pathlib import Path

import pytest

from test_realworld_regressions import application, scenario_engine  # noqa: F401

pytestmark = pytest.mark.live_llm


@pytest.fixture(scope="module")
def live_model():
    if os.getenv("RUN_LIVE_LLM_TESTS", "").lower() not in {"1", "true", "yes"}:
        pytest.skip("Set RUN_LIVE_LLM_TESTS=1 to send synthetic prompts to the configured test LLM")
    pytest.importorskip("langchain_openai", reason="Run with the backend Python environment")
    from dotenv import load_dotenv
    import sys

    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / "backend"))
    load_dotenv(root / "TestSuite" / "client_llms" / ".env", override=False)
    from TestSuite.client_llms.llms import get_chat_model

    yield get_chat_model()
    get_chat_model.cache_clear()
    sys.path.remove(str(root / "backend"))
    sys.path.remove(str(root))


@pytest.fixture
def application_llm(live_model, monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "synthetic-llm-workflow-test-key")
    from app import llms
    from core import evaluation_service, interview_agent, question_generation

    for module in (llms, evaluation_service, interview_agent, question_generation):
        monkeypatch.setattr(module, "get_chat_model", lambda: live_model)
    return live_model


@pytest.mark.parametrize("answer,minimum,maximum", [
    ("A transaction is an atomic unit of work. Either all operations commit or all are rolled back.", 0.75, 1.0),
    ("A transaction guarantees that every query always runs faster.", 0.0, 0.3),
    ("It groups several database operations together.", 0.15, 0.8),
])
def test_live_structured_grading_respects_known_answer_quality(application_llm, answer, minimum, maximum):
    from core.evaluation_service import _evaluate_subjective_with_llm

    score, feedback = _evaluate_subjective_with_llm(
        "What is a database transaction? Include the all-or-nothing property.",
        "An atomic unit of database work: all operations commit together or are rolled back together.",
        answer, "text",
    )
    assert minimum <= score <= maximum
    assert feedback.strip() and len(feedback) <= 3000


def test_live_interview_followup_obeys_the_application_schema(application_llm):
    from core.interview_agent import evaluate_and_generate_followup

    result = evaluate_and_generate_followup(
        "synthetic-test", "Developer", "junior", "easy", ["transactions"],
        "A transaction commits all its changes together or rolls them all back.",
        conversation=[{"role": "assistant", "content": "Explain database transactions."}],
    )
    assert 0 <= result["score"] <= 10
    assert result["next_question"].strip()
    assert isinstance(result["strengths"], list)


@pytest.mark.parametrize("question_type", ["text", "single_mcq", "multi_mcq"])
def test_live_question_generation_before_embedding_stage(application_llm, question_type):
    from core.question_generation import generate_questions_from_text

    questions = generate_questions_from_text(
        "A database transaction is atomic. COMMIT saves changes. ROLLBACK discards changes.",
        question_type, "easy", "Transactions", count=2,
    )
    assert len(questions) == 2
    assert all(question["question_type"] == question_type for question in questions)


def test_live_practice_generation_prompt_and_answer_keys(application_llm):
    from api.routers_practice import GENERATION_PROMPT, _validate_generated_questions

    response = application_llm.invoke(GENERATION_PROMPT.format(
        question_count=10,
        context_json=json.dumps({
            "job_title": "Junior developer", "topics": "SQL transactions", "difficulty": "easy",
            "job_description": "Synthetic test data; explain COMMIT and ROLLBACK.", "resume_text": None,
        }),
    ))
    validated = _validate_generated_questions(json.loads(response.content), 10)
    assert len(validated) == 10
    assert {"text", "single_mcq", "multi_mcq"} <= {question["type"] for question in validated}


def test_live_practice_worker_generates_and_persists_questions(application, live_model, monkeypatch):
    from app import llms
    from core.practice_generation import _claim_next_practice_test, _generate_claimed_practice_test

    m = application.models
    test = m.PracticeTest(
        user_id=application.user.id, job_title="Synthetic junior developer", topics="SQL transactions",
        difficulty="easy", question_count=10, status=m.PracticeTestStatus.generating,
    )
    application.db.add(test)
    application.db.commit()
    monkeypatch.setattr(llms, "get_chat_model", lambda: live_model)
    assert _claim_next_practice_test(application.db) == test.id
    _generate_claimed_practice_test(test.id)
    application.db.refresh(test)
    assert test.status == m.PracticeTestStatus.ready
    assert test.generation_claimed_at is None
    assert application.db.query(m.PracticeQuestion).filter_by(practice_test_id=test.id).count() == 10
