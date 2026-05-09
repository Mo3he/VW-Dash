from __future__ import annotations
import asyncio
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter
from pydantic import BaseModel

from config import settings, persist_settings
import poller

_executor = ThreadPoolExecutor(max_workers=1)

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    vw_username: str | None = None
    vw_password: str | None = None
    vw_vin: str | None = None
    electricity_rate_per_kwh: float | None = None
    currency_symbol: str | None = None
    currency_after: bool | None = None
    epa_rated_range_km: float | None = None
    poll_interval_seconds: int | None = None
    vehicle_name: str | None = None


@router.get("")
def get_settings():
    return {
        "vw_username": settings.vw_username,
        "vw_password_set": bool(settings.vw_password),
        "vw_vin": settings.vw_vin,
        "electricity_rate_per_kwh": settings.electricity_rate_per_kwh,
        "currency_symbol": settings.currency_symbol,
        "currency_after": settings.currency_after,
        "epa_rated_range_km": settings.epa_rated_range_km,
        "poll_interval_seconds": settings.poll_interval_seconds,
        "vehicle_name": settings.vehicle_name,
    }


@router.patch("")
def update_settings(body: SettingsUpdate):
    credentials_changed = any([
        body.vw_username is not None,
        body.vw_password is not None,
        body.vw_vin is not None,
    ])

    persist_settings(
        vw_username=body.vw_username,
        vw_password=body.vw_password,
        vw_vin=body.vw_vin,
        electricity_rate_per_kwh=body.electricity_rate_per_kwh,
        currency_symbol=body.currency_symbol,
        currency_after=body.currency_after,
        epa_rated_range_km=body.epa_rated_range_km,
        poll_interval_seconds=body.poll_interval_seconds,
        vehicle_name=body.vehicle_name,
    )

    if credentials_changed:
        poller.reset_weconnect()
        # Kick off an immediate poll in the background so the dashboard updates right away
        loop = asyncio.get_event_loop()
        loop.run_in_executor(_executor, poller.poll)

    return get_settings()
