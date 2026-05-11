from __future__ import annotations
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from models import Charger, ChargingSession

router = APIRouter(prefix="/api/chargers", tags=["chargers"])

NEARBY_RADIUS_M = 100


class ChargerCreate(BaseModel):
    name: str
    latitude: float
    longitude: float


class ChargerUpdate(BaseModel):
    name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def find_nearby(db: Session, lat: float, lon: float, radius_m: float = NEARBY_RADIUS_M) -> Charger | None:
    chargers = db.scalars(select(Charger)).all()
    best: Charger | None = None
    best_dist = float("inf")
    for c in chargers:
        d = haversine_m(lat, lon, c.latitude, c.longitude)
        if d <= radius_m and d < best_dist:
            best = c
            best_dist = d
    return best


@router.get("")
def list_chargers(db: Session = Depends(get_db)):
    chargers = db.scalars(select(Charger).order_by(Charger.name)).all()
    return [_to_dict(c) for c in chargers]


@router.post("", status_code=201)
def create_charger(body: ChargerCreate, db: Session = Depends(get_db)):
    c = Charger(name=body.name, latitude=body.latitude, longitude=body.longitude)
    db.add(c)
    db.commit()
    db.refresh(c)
    return _to_dict(c)


@router.patch("/{charger_id}")
def update_charger(charger_id: int, body: ChargerUpdate, db: Session = Depends(get_db)):
    c = db.get(Charger, charger_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Charger not found")
    if body.name is not None:
        old_name = c.name
        c.name = body.name
        # Keep location_name on linked sessions in sync
        sessions = db.scalars(
            select(ChargingSession).where(ChargingSession.charger_id == charger_id)
        ).all()
        for s in sessions:
            if s.location_name == old_name:
                s.location_name = body.name
    if body.latitude is not None:
        c.latitude = body.latitude
    if body.longitude is not None:
        c.longitude = body.longitude
    db.commit()
    db.refresh(c)
    return _to_dict(c)


@router.delete("/{charger_id}", status_code=204)
def delete_charger(charger_id: int, db: Session = Depends(get_db)):
    c = db.get(Charger, charger_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Charger not found")
    sessions = db.scalars(
        select(ChargingSession).where(ChargingSession.charger_id == charger_id)
    ).all()
    for s in sessions:
        s.charger_id = None
    db.delete(c)
    db.commit()


@router.get("/nearby")
def nearby_charger(
    lat: float = Query(...),
    lon: float = Query(...),
    radius_m: float = Query(default=NEARBY_RADIUS_M, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    charger = find_nearby(db, lat, lon, radius_m)
    if charger is None:
        return None
    return _to_dict(charger)


def _to_dict(c: Charger) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "latitude": c.latitude,
        "longitude": c.longitude,
    }
