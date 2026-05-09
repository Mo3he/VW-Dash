from __future__ import annotations
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from database import get_db
from models import Trip
from config import settings

router = APIRouter(prefix="/api/trips", tags=["trips"])


@router.get("")
def list_trips(
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    trips = db.scalars(
        select(Trip)
        .order_by(Trip.started_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    total = db.scalar(select(func.count()).select_from(Trip))
    return {"total": total, "trips": [_trip_to_dict(t) for t in trips]}


@router.get("/stats")
def trip_stats(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    trips = db.scalars(
        select(Trip)
        .where(Trip.started_at >= since, Trip.ended_at.is_not(None))
    ).all()

    total_km = sum(t.distance_km or 0 for t in trips)
    total_kwh = sum(t.kwh_used or 0 for t in trips)
    efficiencies = [t.efficiency_kwh_100km for t in trips if t.efficiency_kwh_100km]
    avg_efficiency = sum(efficiencies) / len(efficiencies) if efficiencies else None

    cost_per_100km = None
    if total_km > 0 and total_kwh > 0:
        cost_per_100km = round((total_kwh / total_km) * 100 * settings.electricity_rate_per_kwh, 2)

    # Temperature vs efficiency buckets (Celsius)
    temp_buckets: dict[str, list[float]] = {
        "cold (<0°C)": [],
        "cool (0–10°C)": [],
        "mild (10–20°C)": [],
        "warm (>20°C)": [],
    }
    for t in trips:
        if t.outdoor_temp_c is not None and t.efficiency_kwh_100km is not None:
            c = t.outdoor_temp_c
            if c < 0:
                temp_buckets["cold (<0°C)"].append(t.efficiency_kwh_100km)
            elif c < 10:
                temp_buckets["cool (0–10°C)"].append(t.efficiency_kwh_100km)
            elif c < 20:
                temp_buckets["mild (10–20°C)"].append(t.efficiency_kwh_100km)
            else:
                temp_buckets["warm (>20°C)"].append(t.efficiency_kwh_100km)

    temp_efficiency = {
        k: round(sum(v) / len(v), 1) for k, v in temp_buckets.items() if v
    }

    return {
        "period_days": days,
        "trip_count": len(trips),
        "total_km": round(total_km, 1),
        "total_kwh": round(total_kwh, 2),
        "avg_efficiency_kwh_100km": round(avg_efficiency, 1) if avg_efficiency else None,
        "cost_per_100km": cost_per_100km,
        "currency_symbol": settings.currency_symbol,
        "currency_after": settings.currency_after,
        "temp_efficiency": temp_efficiency,
    }


def _trip_to_dict(t: Trip) -> dict:
    duration_min = None
    if t.started_at and t.ended_at:
        duration_min = round((t.ended_at - t.started_at).total_seconds() / 60)
    return {
        "id": t.id,
        "started_at": t.started_at.isoformat(),
        "ended_at": t.ended_at.isoformat() if t.ended_at else None,
        "duration_min": duration_min,
        "distance_km": t.distance_km,
        "distance_miles": t.distance_miles,
        "soc_start_pct": t.soc_start_pct,
        "soc_end_pct": t.soc_end_pct,
        "kwh_used": t.kwh_used,
        "efficiency_kwh_100km": t.efficiency_kwh_100km,
        "avg_speed_kmh": t.avg_speed_kmh,
        "start_lat": t.start_lat,
        "start_lon": t.start_lon,
        "end_lat": t.end_lat,
        "end_lon": t.end_lon,
        "outdoor_temp_c": t.outdoor_temp_c,
        "outdoor_temp_f": round(t.outdoor_temp_c * 9 / 5 + 32, 1) if t.outdoor_temp_c else None,
    }
