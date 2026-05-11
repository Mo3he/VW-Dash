from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional


def as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Return dt as a timezone-aware UTC datetime.

    SQLite stores datetimes without timezone info. Use this whenever a datetime
    read from the DB needs to be compared with an aware datetime such as
    datetime.now(timezone.utc). No-ops if dt is already aware or None.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def iso_utc(dt: Optional[datetime]) -> Optional[str]:
    """Serialize a datetime to ISO 8601 with explicit UTC offset.

    SQLite stores naive datetimes; without the +00:00 suffix JavaScript's
    Date constructor treats them as local time instead of UTC.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()
