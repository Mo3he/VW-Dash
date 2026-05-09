from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from database import get_db
from models import ChargingSession
from config import settings


class SessionUpdate(BaseModel):
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    soc_start_pct: Optional[float] = None
    soc_end_pct: Optional[float] = None
    kwh_added: Optional[float] = None
    kwh_added_real: Optional[float] = None
    cost: Optional[float] = None
    cost_per_kwh: Optional[float] = None
    charge_type: Optional[str] = None
    peak_power_kw: Optional[float] = None

router = APIRouter(prefix="/api/charging", tags=["charging"])


@router.get("/sessions")
def list_sessions(
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    sessions = db.scalars(
        select(ChargingSession)
        .order_by(ChargingSession.started_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    total = db.scalar(select(func.count()).select_from(ChargingSession))
    return {"total": total, "sessions": [_session_to_dict(s) for s in sessions]}


@router.get("/sessions/{session_id}")
def get_session(session_id: int, db: Session = Depends(get_db)):
    session = db.get(ChargingSession, session_id)
    if session is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Session not found")
    return _session_to_dict(session)


@router.patch("/sessions/{session_id}")
def update_session(session_id: int, body: SessionUpdate, db: Session = Depends(get_db)):
    session = db.get(ChargingSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if body.started_at is not None:
        session.started_at = datetime.fromisoformat(body.started_at.replace("Z", "+00:00"))
    if body.ended_at is not None:
        session.ended_at = datetime.fromisoformat(body.ended_at.replace("Z", "+00:00"))
    if body.soc_start_pct is not None:
        session.soc_start_pct = body.soc_start_pct
    if body.soc_end_pct is not None:
        session.soc_end_pct = body.soc_end_pct
    if body.kwh_added is not None:
        session.kwh_added = body.kwh_added
        rate = body.cost_per_kwh if body.cost_per_kwh is not None else (
            session.cost_per_kwh if session.cost_per_kwh is not None else settings.electricity_rate_per_kwh
        )
        session.cost = round(body.kwh_added * rate, 2)
    if body.cost_per_kwh is not None:
        session.cost_per_kwh = body.cost_per_kwh
        if session.kwh_added is not None:
            session.cost = round(session.kwh_added * body.cost_per_kwh, 2)
    if body.cost is not None:
        session.cost = body.cost
    if body.charge_type is not None:
        session.charge_type = body.charge_type
    if body.peak_power_kw is not None:
        session.peak_power_kw = body.peak_power_kw
    if body.kwh_added_real is not None:
        session.kwh_added_real = body.kwh_added_real

    db.commit()
    db.refresh(session)
    return _session_to_dict(session)


@router.get("/locations")
def charging_locations(db: Session = Depends(get_db)):
    """All completed sessions with coordinates, for the charge map."""
    sessions = db.scalars(
        select(ChargingSession).where(
            ChargingSession.ended_at.is_not(None),
            ChargingSession.latitude.is_not(None),
            ChargingSession.longitude.is_not(None),
        )
    ).all()
    # Group by location_name (or lat/lon bucket) to avoid stacking identical points
    grouped: dict[str, dict] = {}
    for s in sessions:
        key = s.location_name or f"{round(s.latitude or 0, 3)},{round(s.longitude or 0, 3)}"
        if key not in grouped:
            grouped[key] = {
                "name": s.location_name or "Unknown",
                "latitude": s.latitude,
                "longitude": s.longitude,
                "sessions": 0,
                "total_kwh": 0.0,
            }
        grouped[key]["sessions"] += 1
        grouped[key]["total_kwh"] += s.kwh_added or 0
    result = list(grouped.values())
    for r in result:
        r["total_kwh"] = round(r["total_kwh"], 1)
    return result


@router.get("/stats")
def charging_stats(
    days: int = Query(default=30, ge=1, le=3650),
    db: Session = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    sessions = db.scalars(
        select(ChargingSession).where(ChargingSession.started_at >= since)
    ).all()

    completed = [s for s in sessions if s.ended_at is not None]
    total_kwh = sum(s.kwh_added or 0 for s in completed)
    total_cost = sum(s.cost or 0 for s in completed)
    total_range_km = sum(s.range_added_km or 0 for s in completed)
    dc_sessions = [s for s in completed if (s.charge_type or "").upper() == "DC"]
    ac_sessions = [s for s in completed if (s.charge_type or "").upper() == "AC"]

    # Estimated vs real accuracy
    sessions_with_real = [s for s in completed if s.kwh_added_real is not None and s.kwh_added]
    est_vs_real_pct = None
    if sessions_with_real:
        deltas = [(s.kwh_added_real - s.kwh_added) / s.kwh_added * 100 for s in sessions_with_real]
        est_vs_real_pct = round(sum(deltas) / len(deltas), 2)

    # Battery cycles: total kWh / usable capacity
    battery_kwh = 77.0
    total_cycles = round(total_kwh / battery_kwh, 1) if total_kwh > 0 else 0

    # Charge load: 0.8C threshold for 77 kWh = 61.6 kW
    c_threshold = battery_kwh * 0.8
    high_c_sessions = [s for s in completed if (s.peak_power_kw or 0) >= c_threshold]
    low_c_sessions = [s for s in completed if (s.peak_power_kw or 0) < c_threshold]

    # Top chargers by location_name
    charger_map: dict[str, dict] = {}
    for s in completed:
        name = s.location_name or "Unknown"
        if name not in charger_map:
            charger_map[name] = {"name": name, "sessions": 0, "total_kwh": 0.0}
        charger_map[name]["sessions"] += 1
        charger_map[name]["total_kwh"] += s.kwh_added or 0
    top_chargers = sorted(charger_map.values(), key=lambda x: x["total_kwh"], reverse=True)[:10]
    for c in top_chargers:
        c["total_kwh"] = round(c["total_kwh"], 1)

    return {
        "period_days": days,
        "session_count": len(completed),
        "total_kwh": round(total_kwh, 2),
        "total_cost": round(total_cost, 2),
        "total_range_km": round(total_range_km, 1),
        "dc_session_count": len(dc_sessions),
        "ac_session_count": len(ac_sessions),
        "avg_kwh_per_session": round(total_kwh / len(completed), 2) if completed else 0,
        "total_cycles": total_cycles,
        "high_c_session_count": len(high_c_sessions),
        "low_c_session_count": len(low_c_sessions),
        "top_chargers": top_chargers,
        "est_vs_real_pct": est_vs_real_pct,
        "electricity_rate": settings.electricity_rate_per_kwh,
        "currency_symbol": settings.currency_symbol,
        "currency_after": settings.currency_after,
    }


def _session_to_dict(s: ChargingSession) -> dict:
    duration_min = None
    if s.started_at and s.ended_at:
        duration_min = round((s.ended_at - s.started_at).total_seconds() / 60)
    return {
        "id": s.id,
        "started_at": s.started_at.isoformat(),
        "ended_at": s.ended_at.isoformat() if s.ended_at else None,
        "duration_min": duration_min,
        "soc_start_pct": s.soc_start_pct,
        "soc_end_pct": s.soc_end_pct,
        "kwh_added": s.kwh_added,
        "range_added_km": s.range_added_km,
        "range_added_miles": round(s.range_added_km * 0.621371, 1) if s.range_added_km else None,
        "peak_power_kw": s.peak_power_kw,
        "charge_type": s.charge_type,
        "cost": s.cost,
        "cost_per_kwh": s.cost_per_kwh,
        "kwh_added_real": s.kwh_added_real,
        "avg_power_kw": s.avg_power_kw,
        "latitude": s.latitude,
        "longitude": s.longitude,
        "location_name": s.location_name,
        "currency_symbol": settings.currency_symbol,
        "currency_after": settings.currency_after,
    }
