from __future__ import annotations

import logging
import os
import tempfile
import threading
import time

from fastapi import APIRouter, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import settings
from database import SessionLocal
from geocoder import reverse_geocode
from import_vwsfriend import import_from_backup
from models import ChargingSession, Trip

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/import", tags=["import"])

_backfill_running = False


def _geocode_backfill_bg() -> None:
    """
    Background geocoding with coordinate deduplication.
    Rounds coords to 3dp before looking up — many trips share the same location,
    so we only hit Nominatim once per unique spot.
    """
    global _backfill_running
    if _backfill_running:
        logger.info("Geocode backfill already running, skipping duplicate")
        return
    _backfill_running = True
    try:
        db: Session = SessionLocal()
        coord_cache: dict[tuple[float, float], str | None] = {}

        def cached_geocode(lat: float | None, lon: float | None) -> str | None:
            if lat is None or lon is None:
                return None
            key = (round(lat, 3), round(lon, 3))
            if key not in coord_cache:
                result = reverse_geocode(lat, lon)
                if result:  # only cache successes; failures may retry next time
                    coord_cache[key] = result
                return result
            return coord_cache[key]

        try:
            trips = db.scalars(
                select(Trip).where(
                    Trip.start_lat.is_not(None),
                    Trip.start_address.is_(None),
                )
            ).all()
            logger.info("Geocode backfill: %d trips to process", len(trips))
            for t in trips:
                t.start_address = cached_geocode(t.start_lat, t.start_lon)
                t.end_address = cached_geocode(t.end_lat, t.end_lon)
            db.commit()

            sessions = db.scalars(
                select(ChargingSession).where(
                    ChargingSession.latitude.is_not(None),
                    ChargingSession.location_name.is_(None),
                )
            ).all()
            logger.info("Geocode backfill: %d charging sessions to process", len(sessions))
            for s in sessions:
                s.location_name = cached_geocode(s.latitude, s.longitude)
            db.commit()

            logger.info(
                "Geocode backfill complete — %d unique coords resolved",
                sum(1 for v in coord_cache.values() if v),
            )
        finally:
            db.close()
    except Exception:
        logger.exception("Geocode backfill failed")
    finally:
        _backfill_running = False


@router.post("/vwsfriend")
async def import_vwsfriend(
    file: UploadFile,
    battery_kwh: float = Form(default=77.0),
    wipe: bool = Form(default=False),
):
    suffix = os.path.splitext(file.filename or "")[1] or ".backup"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        result = import_from_backup(
            backup_path=tmp_path,
            db_path=settings.db_path,
            battery_kwh=battery_kwh,
            wipe=wipe,
        )
    except Exception as exc:
        logger.exception("Import failed")
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        os.unlink(tmp_path)

    threading.Thread(target=_geocode_backfill_bg, daemon=True).start()
    return result


@router.post("/geocode-backfill")
def geocode_backfill():
    """Start geocoding in the background and return immediately."""
    if _backfill_running:
        return {"status": "already_running"}
    threading.Thread(target=_geocode_backfill_bg, daemon=True).start()
    return {"status": "started"}
