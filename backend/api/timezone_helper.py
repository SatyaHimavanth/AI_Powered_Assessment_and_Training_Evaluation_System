from datetime import datetime, timezone


def as_utc_aware(dt: datetime | None) -> datetime | None:
    """Ensure a datetime is UTC-aware.

    - None passthrough.
    - Naive datetimes are assumed to be UTC and get tzinfo attached.
    - Aware datetimes are converted to UTC.

    Use this before any comparison or subtraction involving ORM
    DateTime(timezone=True) columns to avoid the
    "Cannot compare offset-native and offset-aware datetimes" error
    on PostgreSQL.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_to_utc_aware(value: str) -> datetime:
    """Parse an ISO-8601 string into a UTC-aware datetime.

    - Trailing 'Z' is normalised to '+00:00'.
    - Naive inputs (no timezone info) are treated as UTC.
    """
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    return as_utc_aware(dt)


def to_utc_iso(dt: datetime | None) -> str | None:
    """Format a datetime as a UTC ISO-8601 string ending with 'Z'.

    Returns None for None input.  Handles naive datetimes (treated as UTC)
    and aware datetimes (converted to UTC).
    """
    if dt is None:
        return None
    aware = as_utc_aware(dt)
    return aware.isoformat().replace("+00:00", "Z")
