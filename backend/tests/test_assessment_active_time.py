from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from core.assessment_timing import (
    checkpoint_active_time,
    remaining_active_seconds,
    start_active_session,
)


def test_active_time_accumulates_between_checkpoints_and_pauses_on_resume():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    attempt = SimpleNamespace(
        active_seconds=0, active_started_at=start, active_heartbeat_at=start
    )

    checkpoint_active_time(attempt, start + timedelta(seconds=5))
    checkpoint_active_time(attempt, start + timedelta(seconds=10))
    assert attempt.active_seconds == 10
    assert attempt.active_started_at == start + timedelta(seconds=10)

    attempt.active_started_at = None
    attempt.active_heartbeat_at = None
    start_active_session(attempt, start + timedelta(minutes=10))
    checkpoint_active_time(attempt, start + timedelta(minutes=10, seconds=5))
    assert attempt.active_seconds == 15


def test_stale_session_is_capped_at_lease_and_does_not_count_offline_gap():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    attempt = SimpleNamespace(
        active_seconds=0, active_started_at=start, active_heartbeat_at=start
    )

    checkpoint_active_time(attempt, start + timedelta(seconds=60), lease_seconds=12)

    assert attempt.active_seconds == 12
    assert attempt.active_started_at is None


def test_duration_exhaustion_uses_accumulated_active_seconds():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    attempt = SimpleNamespace(
        active_seconds=59, active_started_at=start, active_heartbeat_at=start
    )

    checkpoint_active_time(attempt, start + timedelta(seconds=5))
    assert attempt.active_seconds == 64
    assert attempt.active_seconds >= 60


def test_remaining_time_counts_fractional_active_seconds_without_drift():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    attempt = SimpleNamespace(
        active_seconds=59.5,
        active_started_at=start,
        active_heartbeat_at=start,
    )

    assert remaining_active_seconds(attempt, 1, start + timedelta(milliseconds=400)) == 1
    assert remaining_active_seconds(attempt, 1, start + timedelta(milliseconds=500)) == 0
