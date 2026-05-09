from __future__ import annotations
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from database import get_db
from models import Trip, TripPoint
from config import settings

router = APIRouter(prefix="/api/trips", tags=["trips"])


@router.get("")
def list_trips(
    limit: int = Query(default=20, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    days: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    q = select(Trip).order_by(Trip.started_at.desc())
    if days > 0:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        q = q.where(Trip.started_at >= since, Trip.ended_at.is_not(None))
    trips = db.scalars(q.limit(limit).offset(offset)).all()
    count_q = select(func.count()).select_from(Trip)
    if days > 0:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        count_q = count_q.where(Trip.started_at >= since, Trip.ended_at.is_not(None))
    total = db.scalar(count_q)
    return {"total": total, "trips": [_trip_to_dict(t) for t in trips]}


@router.get("/{trip_id}/route")
def trip_route(trip_id: int, db: Session = Depends(get_db)):
    """Ordered GPS breadcrumbs for a single trip, including start/end from the Trip row."""
    trip = db.get(Trip, trip_id)
    if trip is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Trip not found")

    points = db.scalars(
        select(TripPoint)
        .where(TripPoint.trip_id == trip_id)
        .order_by(TripPoint.recorded_at)
    ).all()

    coords = [{"lat": p.latitude, "lon": p.longitude} for p in points]

    # If no mid-trip breadcrumbs, fall back to start/end points only
    if not coords:
        if trip.start_lat and trip.start_lon:
            coords.append({"lat": trip.start_lat, "lon": trip.start_lon})
        if trip.end_lat and trip.end_lon:
            coords.append({"lat": trip.end_lat, "lon": trip.end_lon})

    return {"trip_id": trip_id, "points": coords}


@router.get("/stats")
def trip_stats(
    days: int = Query(default=30, ge=1, le=3650),
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


@router.get("/popular")
def popular_routes(
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Most frequent origin→destination pairs (requires geocoded addresses)."""
    trips = db.scalars(
        select(Trip).where(
            Trip.start_address.is_not(None),
            Trip.end_address.is_not(None),
            Trip.ended_at.is_not(None),
        )
    ).all()

    route_map: dict[str, dict] = {}
    for t in trips:
        key = f"{t.start_address}||{t.end_address}"
        if key not in route_map:
            route_map[key] = {
                "start": t.start_address,
                "end": t.end_address,
                "count": 0,
                "avg_distance_km": 0.0,
                "distances": [],
            }
        route_map[key]["count"] += 1
        if t.distance_km:
            route_map[key]["distances"].append(t.distance_km)

    results = []
    for r in route_map.values():
        dists = r.pop("distances")
        r["avg_distance_km"] = round(sum(dists) / len(dists), 1) if dists else None
        results.append(r)

    results.sort(key=lambda x: x["count"], reverse=True)
    return results[:limit]


@router.get("/journeys")
def list_journeys(
    days: int = Query(default=30, ge=1, le=3650),
    db: Session = Depends(get_db),
):
    """Group completed trips into day-level journeys."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    trips = db.scalars(
        select(Trip)
        .where(Trip.started_at >= since, Trip.ended_at.is_not(None))
        .order_by(Trip.started_at.desc())
    ).all()

    # Group by calendar date (UTC)
    from collections import defaultdict
    day_map: dict[str, list] = defaultdict(list)
    for t in trips:
        day = t.started_at.strftime("%Y-%m-%d")
        day_map[day].append(t)

    journeys = []
    for day, day_trips in sorted(day_map.items(), reverse=True):
        total_km = sum(t.distance_km or 0 for t in day_trips)
        total_kwh = sum(t.kwh_used or 0 for t in day_trips)
        journeys.append({
            "date": day,
            "trip_count": len(day_trips),
            "total_km": round(total_km, 1),
            "total_kwh": round(total_kwh, 2),
            "start_address": day_trips[-1].start_address,  # earliest trip
            "end_address": day_trips[0].end_address,       # latest trip
            "trips": [_trip_to_dict(t) for t in day_trips],
        })

    return journeys


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
        "start_address": t.start_address,
        "end_address": t.end_address,
    }
