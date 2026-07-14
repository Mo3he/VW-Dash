from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config import settings, persist_settings
import poller

_executor = ThreadPoolExecutor(max_workers=1)

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Scheduler reference injected by main.py after startup
_scheduler = None

def set_scheduler(s) -> None:
    global _scheduler
    _scheduler = s


class SettingsUpdate(BaseModel):
    vw_username: str | None = None
    vw_password: str | None = None
    vw_vin: str | None = None
    vw_provider: str | None = None
    vw_country: str | None = None
    electricity_rate_per_kwh: float | None = Field(default=None, ge=0)
    currency_symbol: str | None = None
    currency_after: bool | None = None
    epa_rated_range_km: float | None = Field(default=None, gt=0)
    poll_interval_seconds: int | None = Field(default=None, ge=60)
    vehicle_name: str | None = None
    battery_capacity_kwh: float | None = Field(default=None, gt=0)
    timezone: str | None = None
    time_24h: bool | None = None
    distance_unit: str | None = None
    access_token: str | None = None
    webhook_url: str | None = None
    mqtt_enabled: bool | None = None
    mqtt_host: str | None = None
    mqtt_port: int | None = Field(default=None, ge=1, le=65535)
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_base_topic: str | None = None
    mqtt_discovery: bool | None = None
    mqtt_discovery_prefix: str | None = None


@router.get("")
def get_settings():
    return {
        "vw_username": settings.vw_username,
        "vw_password_set": bool(settings.vw_password),
        "vw_vin": settings.vw_vin,
        "vw_provider": settings.vw_provider,
        "vw_country": settings.vw_country,
        "electricity_rate_per_kwh": settings.electricity_rate_per_kwh,
        "currency_symbol": settings.currency_symbol,
        "currency_after": settings.currency_after,
        "epa_rated_range_km": settings.epa_rated_range_km,
        "poll_interval_seconds": settings.poll_interval_seconds,
        "vehicle_name": settings.vehicle_name,
        "battery_capacity_kwh": settings.battery_capacity_kwh,
        "timezone": settings.timezone,
        "time_24h": settings.time_24h,
        "distance_unit": settings.distance_unit,
        "webhook_url": settings.webhook_url,
        "mqtt_enabled": settings.mqtt_enabled,
        "mqtt_host": settings.mqtt_host,
        "mqtt_port": settings.mqtt_port,
        "mqtt_username": settings.mqtt_username,
        "mqtt_password_set": bool(settings.mqtt_password),
        "mqtt_base_topic": settings.mqtt_base_topic,
        "mqtt_discovery": settings.mqtt_discovery,
        "mqtt_discovery_prefix": settings.mqtt_discovery_prefix,
    }


@router.patch("")
def update_settings(body: SettingsUpdate):
    credentials_changed = any([
        body.vw_username is not None,
        body.vw_password is not None,
        body.vw_vin is not None,
        body.vw_provider is not None,
        body.vw_country is not None,
    ])

    mqtt_changed = any([
        body.mqtt_enabled is not None,
        body.mqtt_host is not None,
        body.mqtt_port is not None,
        body.mqtt_username is not None,
        body.mqtt_password is not None,
        body.mqtt_base_topic is not None,
        body.mqtt_discovery is not None,
        body.mqtt_discovery_prefix is not None,
    ])

    persist_settings(
        vw_username=body.vw_username,
        vw_password=body.vw_password,
        vw_vin=body.vw_vin,
        vw_provider=body.vw_provider,
        vw_country=body.vw_country,
        electricity_rate_per_kwh=body.electricity_rate_per_kwh,
        currency_symbol=body.currency_symbol,
        currency_after=body.currency_after,
        epa_rated_range_km=body.epa_rated_range_km,
        poll_interval_seconds=body.poll_interval_seconds,
        vehicle_name=body.vehicle_name,
        battery_capacity_kwh=body.battery_capacity_kwh,
        timezone=body.timezone,
        time_24h=body.time_24h,
        distance_unit=body.distance_unit,
        access_token=body.access_token,
        webhook_url=body.webhook_url,
        mqtt_enabled=body.mqtt_enabled,
        mqtt_host=body.mqtt_host,
        mqtt_port=body.mqtt_port,
        mqtt_username=body.mqtt_username,
        mqtt_password=body.mqtt_password,
        mqtt_base_topic=body.mqtt_base_topic,
        mqtt_discovery=body.mqtt_discovery,
        mqtt_discovery_prefix=body.mqtt_discovery_prefix,
    )

    if credentials_changed:
        poller.reset_weconnect()
        _executor.submit(poller.poll)

    if mqtt_changed:
        import mqtt_client
        _executor.submit(mqtt_client.reset)

    if body.poll_interval_seconds is not None and _scheduler is not None:
        _scheduler.reschedule_job(
            "poller",
            trigger="interval",
            seconds=settings.poll_interval_seconds,
        )

    return get_settings()


@router.post("/test-connection")
def test_connection():
    """Attempt WeConnect login and return success/failure without persisting."""
    if not settings.vw_username or not settings.vw_password:
        raise HTTPException(status_code=400, detail="No credentials configured")
    try:
        import os
        from weconnect import weconnect as wc
        tokenfile = os.path.join(os.path.dirname(__file__), "..", "..", "data", "weconnect_token.json")
        wc_inst = wc.WeConnect(
            username=settings.vw_username,
            password=settings.vw_password,
            tokenfile=tokenfile,
            updateAfterLogin=False,
            loginOnInit=False,
        )
        wc_inst.login()
        vehicles = list(wc_inst.vehicles.keys())
        return {"status": "ok", "vehicles": vehicles}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/portal-status")
def portal_status():
    """Auth state of the read-only website-portal provider (for the Settings UI)."""
    return poller.portal_auth_status()


class PortalOTP(BaseModel):
    code: str


@router.post("/portal-otp")
def portal_otp(body: PortalOTP):
    """Submit an email-OTP code to finish a pending website-portal login."""
    code = (body.code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="OTP code is required")
    try:
        result = poller.submit_portal_otp(code)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    if result.get("status") == "ok":
        _executor.submit(poller.poll)
    return result
