from datetime import datetime, timedelta, timezone
import math

# A disconnected exam may continue locally for five minutes. After the lease
# expires, server accounting pauses until the browser reconnects.
ACTIVE_SESSION_LEASE_SECONDS = 5 * 60


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def start_active_session(attempt, now: datetime | None = None) -> None:
    instant = _utc(now or datetime.now(timezone.utc))
    if attempt.active_started_at is None:
        attempt.active_started_at = instant
    attempt.active_heartbeat_at = instant


def checkpoint_active_time(
    attempt,
    now: datetime | None = None,
    lease_seconds: int = ACTIVE_SESSION_LEASE_SECONDS,
    renew_lease: bool = True,
) -> float:
    """Accumulate active time, bounding unobserved time after a lost browser session."""
    instant = _utc(now or datetime.now(timezone.utc))
    started = getattr(attempt, "active_started_at", None)
    if started is None:
        return float(getattr(attempt, "active_seconds", 0) or 0)

    started = _utc(started)
    heartbeat = _utc(attempt.active_heartbeat_at or started)
    cutoff = min(instant, heartbeat + timedelta(seconds=lease_seconds))
    if cutoff > started:
        attempt.active_seconds = float(attempt.active_seconds or 0) + (cutoff - started).total_seconds()

    if instant >= heartbeat + timedelta(seconds=lease_seconds):
        attempt.active_started_at = None
        attempt.active_heartbeat_at = None
    else:
        attempt.active_started_at = instant
        if renew_lease:
            attempt.active_heartbeat_at = instant
    return float(attempt.active_seconds or 0)


def remaining_active_seconds(attempt, duration_minutes: int, now: datetime | None = None) -> int:
    total = max(0, int(duration_minutes or 0)) * 60
    current = float(getattr(attempt, "active_seconds", 0) or 0)
    if getattr(attempt, "active_started_at", None) is not None:
        instant = _utc(now or datetime.now(timezone.utc))
        started = _utc(attempt.active_started_at)
        heartbeat = _utc(attempt.active_heartbeat_at or started)
        cutoff = min(instant, heartbeat + timedelta(seconds=ACTIVE_SESSION_LEASE_SECONDS))
        current += max(0.0, (cutoff - started).total_seconds())
    return max(0, math.ceil(total - current))
