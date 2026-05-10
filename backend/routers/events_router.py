from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from models import Event
from utils import iso_utc

router = APIRouter(prefix="/api/events", tags=["events"])

_EVENT_LABELS = {
    "trip_started": "Trip started",
    "trip_ended": "Trip ended",
    "charging_started": "Charging started",
    "charging_ended": "Charging ended",
    "connector_connected": "Connector connected",
    "connector_disconnected": "Connector disconnected",
    "climatisation_started": "Climatisation started",
    "climatisation_stopped": "Climatisation stopped",
    "vehicle_locked": "Vehicle locked",
    "vehicle_unlocked": "Vehicle unlocked",
}


@router.get("")
def list_events(
    limit: int = Query(default=50, ge=1, le=200),
    days: int = Query(default=3, ge=1, le=30),
    db: Session = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    events = db.scalars(
        select(Event)
        .where(Event.occurred_at >= since)
        .order_by(Event.occurred_at.desc())
        .limit(limit)
    ).all()
    return [_event_to_dict(e) for e in events]


def _event_to_dict(e: Event) -> dict:
    detail = None
    if e.detail:
        try:
            detail = json.loads(e.detail)
        except Exception:
            detail = e.detail
    return {
        "id": e.id,
        "occurred_at": iso_utc(e.occurred_at),
        "event_type": e.event_type,
        "label": _EVENT_LABELS.get(e.event_type, e.event_type),
        "detail": detail,
    }
