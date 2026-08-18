from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from models import VehicleSnapshot, Trip, ChargingSession
from config import settings
from utils import iso_utc, as_utc

router = APIRouter(prefix="/api/vehicle", tags=["vehicle"])


@router.post("/poll")
async def force_poll():
    """Trigger an immediate poll of the WeConnect API."""
    from poller import poll
    await run_in_threadpool(poll)
    return {"status": "ok"}


@router.get("/latest")
def latest_snapshot(db: Session = Depends(get_db)):
    snap = db.scalars(
        select(VehicleSnapshot).order_by(VehicleSnapshot.recorded_at.desc()).limit(1)
    ).first()
    if snap is None:
        return {}
    return _snap_to_dict(snap)


@router.get("/history")
def snapshot_history(
    hours: int = Query(default=24, ge=1, le=999999),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    if start_date:
        since = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
        until = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc).replace(hour=23, minute=59, second=59) if end_date else now
    else:
        since = now - timedelta(hours=hours)
        until = now
    snaps = db.scalars(
        select(VehicleSnapshot)
        .where(VehicleSnapshot.recorded_at >= since, VehicleSnapshot.recorded_at <= until)
        .order_by(VehicleSnapshot.recorded_at.asc())
    ).all()
    return [_snap_to_dict(s) for s in snaps]


@router.get("/battery-health")
def battery_health(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    Return range extrapolated to 100% SoC over the requested date window,
    grouped by day (median), alongside the configured rated range.
    Accepts any snapshot with SoC >= 20% to maximise data density.
    """
    now = datetime.now(timezone.utc)
    since = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc) if start_date else now - timedelta(days=365 * 10)
    until = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc).replace(hour=23, minute=59, second=59) if end_date else now

    rows = db.scalars(
        select(VehicleSnapshot)
        .where(
            VehicleSnapshot.soc_pct >= 20,
            VehicleSnapshot.range_km.is_not(None),
            VehicleSnapshot.recorded_at >= since,
            VehicleSnapshot.recorded_at <= until,
        )
        .order_by(VehicleSnapshot.recorded_at.asc())
    ).all()

    # Extrapolate each snapshot to 100% SoC, then group by calendar day and take median
    from collections import defaultdict
    daily: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        extrapolated = r.range_km * (100.0 / r.soc_pct)
        day = r.recorded_at.strftime("%Y-%m-%d")
        daily[day].append(extrapolated)

    def _median(vals: list[float]) -> float:
        s = sorted(vals)
        mid = len(s) // 2
        return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2

    # Weighted-average daily consumption from completed trips (kWh/100 km)
    trip_rows = db.scalars(
        select(Trip)
        .where(
            Trip.ended_at >= since,
            Trip.ended_at <= until,
            Trip.efficiency_kwh_100km.is_not(None),
            Trip.distance_km.is_not(None),
            Trip.distance_km > 0,
        )
        .order_by(Trip.ended_at.asc())
    ).all()

    daily_consumption: dict[str, tuple[float, float]] = defaultdict(lambda: (0.0, 0.0))  # day -> (sum_kwh, sum_km)
    for t in trip_rows:
        day = t.ended_at.strftime("%Y-%m-%d")
        prev_kwh, prev_km = daily_consumption[day]
        daily_consumption[day] = (prev_kwh + t.kwh_used, prev_km + t.distance_km)

    def _weighted_consumption(day: str) -> float | None:
        if day not in daily_consumption:
            return None
        total_kwh, total_km = daily_consumption[day]
        if total_km <= 0:
            return None
        return round(total_kwh / total_km * 100, 1)

    points = [
        {
            "date": day + "T12:00:00Z",
            "range_km": round(_median(vals)),
            "consumption_kwh_100km": _weighted_consumption(day),
        }
        for day, vals in sorted(daily.items())
    ]

    return {
        "rated_range_km": settings.epa_rated_range_km,
        "history": points,
    }


@router.get("/vampire-drain")
def vampire_drain(
    days: int = Query(default=30, ge=1, le=3650),
    min_park_hours: float = Query(default=2.0, ge=0.5),
    db: Session = Depends(get_db),
):
    """
    Detect SoC drops during parked periods — the gaps between consecutive Trips and
    ChargingSessions. Deriving windows this way (rather than from raw per-snapshot
    charge_power_kw/odometer_km) matters because those two fields are frequently null in
    practice — WeConnect often omits them, and imported historical data may not carry them
    at all — which used to make the old snapshot-scanning approach silently unable to tell
    charging/driving from parked, collapsing unrelated trips and charges into one bogus
    mega-window. Trip/ChargingSession boundaries are already derived correctly elsewhere
    (poller._update_trip / _update_charging_session), so a gap between one ending and the
    next starting is by definition a period we know nothing else was happening.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    activities: list[tuple[datetime, datetime, Optional[float], Optional[float]]] = []
    for t in db.scalars(select(Trip).where(Trip.started_at.is_not(None), Trip.ended_at.is_not(None))):
        activities.append((as_utc(t.started_at), as_utc(t.ended_at), t.soc_start_pct, t.soc_end_pct))
    for c in db.scalars(select(ChargingSession).where(ChargingSession.started_at.is_not(None), ChargingSession.ended_at.is_not(None))):
        activities.append((as_utc(c.started_at), as_utc(c.ended_at), c.soc_start_pct, c.soc_end_pct))
    activities.sort(key=lambda a: a[0])

    events = []
    for (_prev_start, prev_end, _prev_soc_start, prev_soc_end), (next_start, _next_end, next_soc_start, _next_soc_end) in zip(activities, activities[1:]):
        if prev_end < since or prev_end >= next_start:
            continue  # outside the requested window, or overlapping/back-to-back activities
        duration_h = (next_start - prev_end).total_seconds() / 3600
        if duration_h < min_park_hours or prev_soc_end is None or next_soc_start is None:
            continue
        drop = prev_soc_end - next_soc_start
        if drop > 0:
            events.append({
                "start": iso_utc(prev_end),
                "end": iso_utc(next_start),
                "duration_h": round(duration_h, 1),
                "soc_drop_pct": round(drop, 1),
                "drain_pct_per_h": round(drop / duration_h, 3),
            })

    if not events:
        return {"events": [], "avg_drain_pct_per_h": None, "total_soc_lost": None}

    total_lost = sum(e["soc_drop_pct"] for e in events)
    total_hours = sum(e["duration_h"] for e in events)
    # Weighted average: total SoC lost / total hours parked (longer windows count more)
    avg_drain = total_lost / total_hours if total_hours > 0 else 0
    return {
        "events": events[-20:],  # most recent 20
        "avg_drain_pct_per_h": round(avg_drain, 3),
        "total_soc_lost": round(total_lost, 1),
    }


@router.post("/climate")
def control_climate(action: Literal["start", "stop"] = Query(...)):
    """Send a start/stop climatisation command to the vehicle."""
    from poller import set_climate
    ok, message = set_climate(action)
    if not ok:
        status_code = 503 if "not connected" in message or "not available" in message else 500
        raise HTTPException(status_code=status_code, detail=message)
    return {"status": message, "action": action}


@router.post("/charging-control")
def control_charging(action: Literal["start", "stop"] = Query(...)):
    """Send a start/stop charging command to the vehicle."""
    from poller import set_charging
    ok, message = set_charging(action)
    if not ok:
        status_code = 503 if "not connected" in message or "not available" in message else 500
        raise HTTPException(status_code=status_code, detail=message)
    return {"status": message, "action": action}


@router.post("/window-heating")
def control_window_heating(action: Literal["start", "stop"] = Query(...)):
    """Send a start/stop window-heating command to the vehicle."""
    from poller import set_window_heating
    ok, message = set_window_heating(action)
    if not ok:
        status_code = 503 if "not connected" in message or "not available" in message else 500
        raise HTTPException(status_code=status_code, detail=message)
    return {"status": message, "action": action}


@router.post("/wake")
def control_wake():
    """Force VW to refresh the vehicle's data."""
    from poller import wake_vehicle
    ok, message = wake_vehicle()
    if not ok:
        status_code = 503 if "not connected" in message or "not available" in message else 500
        raise HTTPException(status_code=status_code, detail=message)
    return {"status": message}


def _snap_to_dict(s: VehicleSnapshot) -> dict:
    return {
        "id": s.id,
        "recorded_at": iso_utc(s.recorded_at),
        "soc_pct": s.soc_pct,
        "range_km": s.range_km,
        "range_miles": s.range_miles,
        "charging_state": s.charging_state,
        "charge_power_kw": s.charge_power_kw,
        "charge_rate_km_h": s.charge_rate_km_h,
        "charge_type": s.charge_type,
        "remaining_charge_time_min": s.remaining_charge_time_min,
        "target_soc_pct": s.target_soc_pct,
        "latitude": s.latitude,
        "longitude": s.longitude,
        "parking_time": iso_utc(s.parking_time),
        "outdoor_temp_c": s.outdoor_temp_c,
        "cabin_temp_c": s.cabin_temp_c,
        "battery_temp_c": s.battery_temp_c,
        "battery_temp_min_c": s.battery_temp_min_c,
        "battery_temp_max_c": s.battery_temp_max_c,
        "climatisation_state": s.climatisation_state,
        "locked": s.locked,
        "odometer_km": s.odometer_km,
        "plug_connected": s.plug_connected,
        "windows": __import__("json").loads(s.windows_json) if s.windows_json else None,
        "car_captured_at": iso_utc(s.car_captured_at),
    }
