from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from api.routers_interviews import (
    _interview_remaining_seconds,
    _mark_interview_expired,
    _snapshot_legacy_duration,
)
from db.models import InterviewSessionStatus


def test_paused_interview_time_does_not_consume_duration():
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    paused = started + timedelta(seconds=30)
    now = paused + timedelta(minutes=20)
    session = SimpleNamespace(
        started_at=started,
        paused_at=paused,
        duration_seconds=60,
        status=InterviewSessionStatus.paused,
        completed_at=None,
    )

    assert not _mark_interview_expired(session, now)
    assert _interview_remaining_seconds(session, now) == 30


def test_interview_expires_after_active_time_budget():
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    now = started + timedelta(seconds=61)
    session = SimpleNamespace(
        started_at=started,
        paused_at=None,
        duration_seconds=60,
        status=InterviewSessionStatus.in_progress,
        completed_at=None,
    )

    assert _mark_interview_expired(session, now)
    assert session.status == InterviewSessionStatus.missed
    assert session.completed_at == now
    assert _interview_remaining_seconds(session, now) == 0


def test_legacy_session_gets_duration_from_template():
    session = SimpleNamespace(duration_seconds=None)
    template = SimpleNamespace(duration_minutes=20)

    _snapshot_legacy_duration(session, template)

    assert session.duration_seconds == 1200
