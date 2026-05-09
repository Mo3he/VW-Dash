from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from models import VehicleSnapshot
from config import settings

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
def battery_health(db: Session = Depends(get_db)):
    """
    Estimate SoH by comparing observed max range at 100% SoC against EPA rated range.
    Returns trend data points over time.
    """
    rows = db.scalars(
        select(VehicleSnapshot)
        .where(
            VehicleSnapshot.soc_pct >= 99,
            VehicleSnapshot.range_km.is_not(None),
        )
        .order_by(VehicleSnapshot.recorded_at.asc())
    ).all()

    points = []
    for r in rows:
        soh = round((r.range_km / settings.epa_rated_range_km) * 100, 1)
        points.append({
            "date": r.recorded_at.isoformat(),
            "range_km": r.range_km,
            "soh_pct": soh,
        })

    latest_soh = points[-1]["soh_pct"] if points else None
    return {"latest_soh_pct": latest_soh, "history": points}


def _snap_to_dict(s: VehicleSnapshot) -> dict:
    return {
        "id": s.id,
        "recorded_at": s.recorded_at.isoformat(),
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
        "parking_time": s.parking_time.isoformat() if s.parking_time else None,
        "outdoor_temp_c": s.outdoor_temp_c,
        "cabin_temp_c": s.cabin_temp_c,
        "battery_temp_c": s.battery_temp_c,
        "climatisation_state": s.climatisation_state,
        "locked": s.locked,
        "odometer_km": s.odometer_km,
        "plug_connected": s.plug_connected,
    }
