from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.routers_admin import _validate_retest_state
from db.models import AttemptStatus, EvaluationJobStatus


def test_retest_allowed_only_after_final_evaluation():
    attempt = SimpleNamespace(status=AttemptStatus.completed, score=82.0)
    job = SimpleNamespace(status=EvaluationJobStatus.completed)

    _validate_retest_state(attempt, job, has_unevaluated_answers=False)


@pytest.mark.parametrize(
    "job",
    [
        None,
        SimpleNamespace(status=EvaluationJobStatus.pending),
        SimpleNamespace(status=EvaluationJobStatus.failed),
        SimpleNamespace(status=EvaluationJobStatus.completed),
    ],
)
def test_missed_attempt_can_be_retested_when_no_worker_is_grading_it(job):
    attempt = SimpleNamespace(status=AttemptStatus.missed, score=None)

    _validate_retest_state(attempt, job, has_unevaluated_answers=True)


@pytest.mark.parametrize(
    "attempt,job,unevaluated,expected_detail",
    [
        (SimpleNamespace(status=AttemptStatus.in_progress, score=None), None, False, "Only missed or completed"),
        (SimpleNamespace(status=AttemptStatus.missed, score=None), SimpleNamespace(status=EvaluationJobStatus.in_progress), True, "still being evaluated"),
        (SimpleNamespace(status=AttemptStatus.completed, score=90), SimpleNamespace(status=EvaluationJobStatus.pending), False, "finish evaluation"),
        (SimpleNamespace(status=AttemptStatus.completed, score=90), SimpleNamespace(status=EvaluationJobStatus.failed), False, "finish evaluation"),
        (SimpleNamespace(status=AttemptStatus.completed, score=None), SimpleNamespace(status=EvaluationJobStatus.completed), False, "unevaluated answers"),
        (SimpleNamespace(status=AttemptStatus.completed, score=90), SimpleNamespace(status=EvaluationJobStatus.completed), True, "unevaluated answers"),
    ],
)
def test_retest_rejects_incomplete_or_unevaluated_attempts(attempt, job, unevaluated, expected_detail):
    with pytest.raises(HTTPException) as exc:
        _validate_retest_state(attempt, job, unevaluated)

    assert exc.value.status_code == 409
    assert expected_detail in exc.value.detail
