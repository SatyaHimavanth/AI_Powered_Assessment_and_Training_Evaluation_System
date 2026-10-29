from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from db.models import AttemptStatus
from core.evaluation_service import (
    finalize_attempt_at_deadline,
    finalize_expired_assessment_attempts,
)
from db.models import EvaluationJob, EvaluationJobStatus


def test_attempt_is_finalized_at_assessment_end_time_not_elapsed_duration():
    deadline = datetime.now(timezone.utc)
    attempt = SimpleNamespace(status=AttemptStatus.in_progress, submitted_at=None,
                              active_seconds=0, active_started_at=None, active_heartbeat_at=None)
    assessment = SimpleNamespace(end_time=deadline, duration=60)

    finalized = finalize_attempt_at_deadline(attempt, assessment, now=deadline + timedelta(minutes=45))

    assert finalized is True
    assert attempt.status == AttemptStatus.completed
    assert attempt.submitted_at == deadline


def test_attempt_before_assessment_end_remains_resumable():
    deadline = datetime.now(timezone.utc) + timedelta(hours=1)
    attempt = SimpleNamespace(status=AttemptStatus.in_progress, submitted_at=None,
                              active_seconds=0, active_started_at=None, active_heartbeat_at=None)
    assessment = SimpleNamespace(end_time=deadline, duration=60)

    finalized = finalize_attempt_at_deadline(attempt, assessment, now=datetime.now(timezone.utc))

    assert finalized is False
    assert attempt.status == AttemptStatus.in_progress
    assert attempt.submitted_at is None


def test_assessment_without_end_time_has_no_automatic_cutoff():
    attempt = SimpleNamespace(status=AttemptStatus.in_progress, submitted_at=None,
                              active_seconds=0, active_started_at=None, active_heartbeat_at=None)

    assert finalize_attempt_at_deadline(
        attempt, SimpleNamespace(end_time=None, duration=60), now=datetime.now(timezone.utc) + timedelta(days=30)
    ) is False
    assert attempt.status == AttemptStatus.in_progress


def test_active_duration_exhaustion_finalizes_even_when_shared_end_time_is_future():
    now = datetime.now(timezone.utc)
    attempt = SimpleNamespace(
        status=AttemptStatus.in_progress,
        submitted_at=None,
        active_seconds=55,
        active_started_at=now - timedelta(seconds=5),
        active_heartbeat_at=now - timedelta(seconds=5),
    )
    assessment = SimpleNamespace(end_time=now + timedelta(hours=1), duration=1)

    assert finalize_attempt_at_deadline(attempt, assessment, now=now)
    assert attempt.status == AttemptStatus.completed
    assert attempt.submitted_at == now
    assert attempt.sync_deadline_at == now + timedelta(minutes=5)


def test_worker_finalizes_expired_attempt_and_queues_persisted_answers():
    deadline = datetime.now(timezone.utc) - timedelta(seconds=1)
    attempt = SimpleNamespace(
        id="attempt-id", status=AttemptStatus.in_progress, submitted_at=None,
        active_seconds=0, active_started_at=None, active_heartbeat_at=None,
    )
    assessment = SimpleNamespace(end_time=deadline, duration=60)

    class Query:
        def __init__(self, rows=()):
            self.rows = rows

        def join(self, *_args):
            return self

        def filter(self, *_args):
            return self

        def order_by(self, *_args):
            return self

        def with_for_update(self, **_kwargs):
            return self

        def limit(self, *_args):
            return self

        def all(self):
            return self.rows if attempt.status == AttemptStatus.in_progress else []

        def first(self):
            return None

    class FakeDB:
        def __init__(self):
            self.jobs = []
            self.committed = False

        def query(self, *models):
            return Query([(attempt, assessment)] if models[0].__name__ == "Attempt" else ())

        def add(self, job):
            self.jobs.append(job)

        def commit(self):
            self.committed = True

    db = FakeDB()
    assert finalize_expired_assessment_attempts(db) == 1
    assert attempt.status == AttemptStatus.completed
    assert attempt.submitted_at == deadline
    assert len(db.jobs) == 1
    assert isinstance(db.jobs[0], EvaluationJob)
    assert db.jobs[0].status == EvaluationJobStatus.pending
    assert db.committed is True
