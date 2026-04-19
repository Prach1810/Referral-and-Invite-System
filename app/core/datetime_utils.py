"""UTC helpers for TIMESTAMP columns and ISO-8601 request bodies (naive vs aware)."""

from datetime import datetime, timezone


def utc_now_naive() -> datetime:
    """Current instant as naive UTC — matches how we store times in PostgreSQL."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_utc_naive(dt: datetime) -> datetime:
    """
    Normalize to naive UTC for DB storage and comparisons.
    - Aware datetimes (typical from JSON / Pydantic) → convert to UTC, strip tzinfo.
    - Naive datetimes → assumed to be UTC already (DB reads, legacy callers).
    """
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)
