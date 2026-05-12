from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional

import csv
import io
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from database import get_db
from utils import iso_utc
from models import Trip, TripPoint
from config import settings

router = APIRouter(prefix="/api/trips", tags=["trips"])


class TripCreate(BaseModel):
    started_at: str
    ended_at: str
    distance_km: float
    soc_start_pct: Optional[float] = None
    soc_end_pct: Optional[float] = None
    start_address: Optional[str] = None
    end_address: Optional[str] = None


@router.post("", status_code=201)
def create_trip(body: TripCreate, db: Session = Depends(get_db)):
    started = datetime.fromisoformat(body.started_at.replace("Z", "+00:00"))
    ended = datetime.fromisoformat(body.ended_at.replace("Z", "+00:00"))
    if ended <= started:
        raise HTTPException(status_code=422, detail="ended_at must be after started_at")
    if body.distance_km <= 0:
        raise HTTPException(status_code=422, detail="distance_km must be positive")

    distance_km = round(body.distance_km, 2)
    duration_h = (ended - started).total_seconds() / 3600

    kwh_used: Optional[float] = None
    efficiency: Optional[float] = None
    if body.soc_start_pct and body.soc_end_pct and body.soc_start_pct > body.soc_end_pct:
        kwh_used = round((body.soc_start_pct - body.soc_end_pct) / 100 * settings.battery_capacity_kwh, 2)
        efficiency = round(kwh_used / distance_km * 100, 1)

    trip = Trip(
        started_at=started,
        ended_at=ended,
        distance_km=distance_km,
        distance_miles=round(distance_km * 0.621371, 2),
        soc_start_pct=body.soc_start_pct,
        soc_end_pct=body.soc_end_pct,
        kwh_used=kwh_used,
        efficiency_kwh_100km=efficiency,
        avg_speed_kmh=round(distance_km / duration_h, 1) if duration_h > 0 else None,
        start_address=body.start_address or None,
        end_address=body.end_address or None,
    )
    db.add(trip)
    db.commit()
    db.refresh(trip)
    return _trip_to_dict(trip)


def _parse_range(start_date: Optional[str], end_date: Optional[str], days: int) -> tuple[datetime, datetime]:
    end_dt = datetime.now(timezone.utc)
    if start_date:
        start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    else:
        start_dt = end_dt - timedelta(days=days)
    if end_date:
        end_dt = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc).replace(hour=23, minute=59, second=59)
    return start_dt, end_dt


@router.get("")
def list_trips(
    limit: int = Query(default=20, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    days: int = Query(default=0, ge=0),
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    q = select(Trip).order_by(Trip.started_at.desc())
    if days > 0 or start_date or end_date:
        since, until = _parse_range(start_date, end_date, max(days, 1))
        q = q.where(Trip.started_at >= since, Trip.started_at <= until, Trip.ended_at.is_not(None))
    trips = db.scalars(q.limit(limit).offset(offset)).all()
    count_q = select(func.count()).select_from(Trip)
    if days > 0 or start_date or end_date:
        count_q = count_q.where(Trip.started_at >= since, Trip.started_at <= until, Trip.ended_at.is_not(None))
    total = db.scalar(count_q)
    return {"total": total, "trips": [_trip_to_dict(t) for t in trips]}


@router.get("/{trip_id}/route")
def trip_route(trip_id: int, db: Session = Depends(get_db)):
    """Ordered GPS breadcrumbs for a single trip, including start/end from the Trip row."""
    trip = db.get(Trip, trip_id)
    if trip is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Trip not found")

    mid_points = db.scalars(
        select(TripPoint)
        .where(TripPoint.trip_id == trip_id)
        .order_by(TripPoint.recorded_at)
    ).all()

    # Always anchor with Trip-row start/end so we have at least 2 points for
    # completed trips even when breadcrumbs are all at the stale parking position.
    coords = []
    if trip.start_lat and trip.start_lon:
        coords.append({"lat": trip.start_lat, "lon": trip.start_lon})

    for p in mid_points:
        coords.append({"lat": p.latitude, "lon": p.longitude})

    if trip.end_lat and trip.end_lon:
        coords.append({"lat": trip.end_lat, "lon": trip.end_lon})

    return {"trip_id": trip_id, "points": coords}


@router.get("/stats")
def trip_stats(
    days: int = Query(default=30, ge=1, le=3650),
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    since, until = _parse_range(start_date, end_date, days)
    trips = db.scalars(
        select(Trip)
        .where(Trip.started_at >= since, Trip.started_at <= until, Trip.ended_at.is_not(None))
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

    # Previous period (same duration, immediately before)
    period_len = until - since
    prev_until = since
    prev_since = since - period_len
    prev_trips = db.scalars(
        select(Trip)
        .where(Trip.started_at >= prev_since, Trip.started_at <= prev_until, Trip.ended_at.is_not(None))
    ).all()
    prev_km = sum(t.distance_km or 0 for t in prev_trips)
    prev_kwh = sum(t.kwh_used or 0 for t in prev_trips)

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
        "prev": {
            "trip_count": len(prev_trips),
            "total_km": round(prev_km, 1),
            "total_kwh": round(prev_kwh, 2),
        },
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
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Group completed trips into day-level journeys."""
    since, until = _parse_range(start_date, end_date, days)
    trips = db.scalars(
        select(Trip)
        .where(Trip.started_at >= since, Trip.started_at <= until, Trip.ended_at.is_not(None))
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


@router.get("/export.csv")
def export_trips_csv(
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    q = select(Trip).where(Trip.ended_at.is_not(None)).order_by(Trip.started_at.desc())
    if start_date or end_date:
        since, until = _parse_range(start_date, end_date, 3650)
        q = q.where(Trip.started_at >= since, Trip.started_at <= until)
    trips = db.scalars(q).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "started_at", "ended_at", "duration_min", "distance_km", "distance_miles",
        "soc_start_pct", "soc_end_pct", "kwh_used", "efficiency_kwh_100km",
        "avg_speed_kmh", "outdoor_temp_c", "start_address", "end_address",
        "start_lat", "start_lon", "end_lat", "end_lon",
    ])
    for t in trips:
        duration_min = None
        if t.started_at and t.ended_at:
            duration_min = round((t.ended_at - t.started_at).total_seconds() / 60)
        writer.writerow([
            iso_utc(t.started_at), iso_utc(t.ended_at), duration_min,
            t.distance_km, t.distance_miles,
            t.soc_start_pct, t.soc_end_pct,
            t.kwh_used, t.efficiency_kwh_100km, t.avg_speed_kmh,
            t.outdoor_temp_c, t.start_address, t.end_address,
            t.start_lat, t.start_lon, t.end_lat, t.end_lon,
        ])

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=trips.csv"},
    )


@router.delete("/{trip_id}", status_code=204)
def delete_trip(trip_id: int, db: Session = Depends(get_db)):
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status_code=404, detail="Trip not found")
    for pt in db.scalars(select(TripPoint).where(TripPoint.trip_id == trip_id)).all():
        db.delete(pt)
    db.delete(trip)
    db.commit()


def _trip_to_dict(t: Trip) -> dict:
    duration_min = None
    if t.started_at and t.ended_at:
        duration_min = round((t.ended_at - t.started_at).total_seconds() / 60)
    return {
        "id": t.id,
        "started_at": iso_utc(t.started_at),
        "ended_at": iso_utc(t.ended_at),
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
