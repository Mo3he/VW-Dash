from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional


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
