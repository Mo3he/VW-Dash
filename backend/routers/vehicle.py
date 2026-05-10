from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from models import VehicleSnapshot
from config import settings
from utils import iso_utc

router = APIRouter(prefix="/api/vehicle", tags=["vehicle"])


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
    hours: int = Query(default=24, ge=1, le=168),
    db: Session = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    snaps = db.scalars(
        select(VehicleSnapshot)
        .where(VehicleSnapshot.recorded_at >= since)
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
    Return observed range at ≥99% SoC over the requested date window,
    alongside the configured rated range for comparison.
    """
    filters = [
        VehicleSnapshot.soc_pct >= 99,
        VehicleSnapshot.range_km.is_not(None),
    ]
    now = datetime.now(timezone.utc)
    since = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc) if start_date else now - timedelta(days=365 * 10)
    until = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc).replace(hour=23, minute=59, second=59) if end_date else now
    filters += [VehicleSnapshot.recorded_at >= since, VehicleSnapshot.recorded_at <= until]

    rows = db.scalars(
        select(VehicleSnapshot)
        .where(*filters)
        .order_by(VehicleSnapshot.recorded_at.asc())
    ).all()

    points = [{"date": iso_utc(r.recorded_at), "range_km": r.range_km} for r in rows]
    return {
        "rated_range_km": settings.epa_rated_range_km,
        "history": points,
    }


@router.post("/climate")
def control_climate(action: Literal["start", "stop"] = Query(...)):
    """Send a start/stop climatisation command to the vehicle."""
    from poller import get_weconnect_vehicle
    _wc, vehicle = get_weconnect_vehicle()
    if vehicle is None:
        raise HTTPException(status_code=503, detail="Vehicle not connected to WeConnect")
    try:
        # Use try/except dict access matching the poller's _domain() pattern
        try:
            clim_status = vehicle.domains["climatisation"]["climatisationStatus"]
        except (KeyError, TypeError):
            raise HTTPException(status_code=503, detail="Climatisation domain not available")

        target_state = "COOLING" if action == "start" else "OFF"

        # weconnect 0.60.x: setting .value on an Attribute triggers the CarAPI PUT
        try:
            clim_status.climatisationState.value = target_state
        except Exception as inner:
            raise HTTPException(status_code=500, detail=f"Climate command failed: {inner}")

        return {"status": "command_sent", "action": action, "target_state": target_state}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


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
        "climatisation_state": s.climatisation_state,
        "locked": s.locked,
        "odometer_km": s.odometer_km,
        "plug_connected": s.plug_connected,
        "car_captured_at": iso_utc(s.car_captured_at),
    }
