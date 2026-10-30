import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.results_helpers import answer_score_label, assessment_evaluation_status, classify_answer_status, require_completed_attempt
from api.routers_code import RunCodeRequest, run_code
from api.routers_practice import require_completed_practice_test
from db.models import AttemptStatus, EvaluationJobStatus, PracticeTestStatus


@pytest.mark.parametrize(
    "attempt_status,job_status,expected",
    [
        (AttemptStatus.completed, EvaluationJobStatus.failed, "evaluation_failed"),
        (AttemptStatus.completed, EvaluationJobStatus.pending, "evaluating"),
        (AttemptStatus.completed, EvaluationJobStatus.in_progress, "evaluating"),
        (AttemptStatus.completed, EvaluationJobStatus.completed, "completed"),
        (AttemptStatus.missed, EvaluationJobStatus.failed, "missed"),
    ],
)
def test_assessment_status_exposes_failed_evaluation(attempt_status, job_status, expected):
    assert assessment_evaluation_status(attempt_status, job_status) == expected


def test_code_execution_validates_question_before_sandbox_access():
    request = RunCodeRequest(question_id=uuid4(), code="print('candidate')")

    with pytest.raises(HTTPException) as exc:
        asyncio.run(run_code(request, _user=SimpleNamespace(id=uuid4())))

    # The route resolves the question before checking sandbox availability.
    assert exc.value.status_code == 404


@pytest.mark.parametrize("status", [AttemptStatus.in_progress, AttemptStatus.missed])
def test_assessment_answer_key_is_not_released_before_completion(status):
    with pytest.raises(HTTPException) as exc:
        require_completed_attempt(SimpleNamespace(status=status))

    assert exc.value.status_code == 409


def test_assessment_results_are_released_after_completion():
    require_completed_attempt(SimpleNamespace(status=AttemptStatus.completed))


@pytest.mark.parametrize(
    "answer,score,expected",
    [
        (None, None, "unattempted"),
        ("  ", None, "unattempted"),
        ("answer", None, "awaiting_evaluation"),
        ("answer", 1.0, "correct"),
        ("answer", 0.35, "partial"),
        ("answer", 0.0, "incorrect"),
        ("answer", -1.0, "incorrect"),
    ],
)
def test_result_classifies_unattempted_pending_correct_partial_and_wrong(answer, score, expected):
    assert classify_answer_status(answer, score) == expected


def test_failed_attempt_marks_unscored_answer_as_not_evaluated():
    assert classify_answer_status("candidate answer", None, evaluation_failed=True) == "not_evaluated"
    assert answer_score_label("not_evaluated", None) == "Not evaluated"


@pytest.mark.parametrize(
    "status,score,expected",
    [
        ("unattempted", None, "Unattempted"),
        ("awaiting_evaluation", None, "Pending"),
        ("incorrect", 0.0, 0.0),
    ],
)
def test_export_score_label_distinguishes_unattempted_from_pending(status, score, expected):
    assert answer_score_label(status, score) == expected


@pytest.mark.parametrize("status", [PracticeTestStatus.ready, PracticeTestStatus.in_progress])
def test_practice_answer_key_is_not_released_before_completion(status):
    with pytest.raises(HTTPException) as exc:
        require_completed_practice_test(SimpleNamespace(status=status))

    assert exc.value.status_code == 409
