from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import ChargingSession, Trip

router = APIRouter(prefix="/api/stats", tags=["stats"])


def _month_key(dt: datetime) -> str:
    """Returns e.g. '2026-05' for sorting and '2026 May' for display."""
    return dt.strftime("%Y-%m")


def _month_label(key: str) -> str:
    dt = datetime.strptime(key, "%Y-%m")
    return dt.strftime("%Y %B")


@router.get("/monthly")
def monthly_stats(db: Session = Depends(get_db)):
    trips = db.scalars(
        select(Trip).where(Trip.ended_at.is_not(None))
    ).all()

    sessions = db.scalars(
        select(ChargingSession).where(ChargingSession.ended_at.is_not(None))
    ).all()

    # --- Group trips by month ---
    trip_map: dict[str, list[Trip]] = defaultdict(list)
    for t in trips:
        trip_map[_month_key(t.started_at)].append(t)

    # --- Group charging sessions by month ---
    charge_map: dict[str, list[ChargingSession]] = defaultdict(list)
    for s in sessions:
        charge_map[_month_key(s.started_at)].append(s)

    all_keys = sorted(set(trip_map.keys()) | set(charge_map.keys()), reverse=True)

    rows = []
    for key in all_keys:
        month_trips = trip_map.get(key, [])
        month_charges = charge_map.get(key, [])

        # Trip aggregates
        drive_count = len(month_trips)
        time_driven_min = sum(
            round((t.ended_at - t.started_at).total_seconds() / 60)
            for t in month_trips
            if t.ended_at
        )
        distances = [t.distance_km for t in month_trips if t.distance_km is not None]
        total_distance_km = sum(distances)
        median_distance_km = round(statistics.median(distances), 1) if distances else None

        # Charging aggregates
        charge_count = len(month_charges)
        charge_durations = [
            round((s.ended_at - s.started_at).total_seconds() / 60)
            for s in month_charges
            if s.ended_at
        ]
        time_charging_min = sum(charge_durations)
        avg_charge_duration_min = round(time_charging_min / charge_count) if charge_count else None
        energy_kwh_list = [s.kwh_added for s in month_charges if s.kwh_added is not None]
        total_energy_kwh = sum(energy_kwh_list)
        avg_kwh_per_charge = round(total_energy_kwh / charge_count, 1) if charge_count and energy_kwh_list else None
        total_cost = sum(s.cost for s in month_charges if s.cost is not None)

        rows.append({
            "period": _month_label(key),
            "period_key": key,
            "drive_count": drive_count,
            "time_driven_min": time_driven_min,
            "distance_km": round(total_distance_km, 1),
            "median_distance_km": median_distance_km,
            "charge_count": charge_count,
            "time_charging_min": time_charging_min,
            "avg_charge_duration_min": avg_charge_duration_min,
            "energy_charged_kwh": round(total_energy_kwh, 1),
            "avg_kwh_per_charge": avg_kwh_per_charge,
            "total_cost": round(total_cost, 2),
            "currency_symbol": settings.currency_symbol,
            "currency_after": settings.currency_after,
        })

    return rows
