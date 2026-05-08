from __future__ import annotations
"""
Polls the WeConnect API and persists snapshots + derived session/trip records.
Runs as an APScheduler background job inside the FastAPI process.
"""
import logging
import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from config import settings
from database import SessionLocal
from models import ChargingSession, Trip, VehicleSnapshot
from ws import broadcast

logger = logging.getLogger(__name__)

# --- WeConnect instance (created once at startup) ---
_weconnect: Any = None

# State carried between poll cycles to detect session boundaries
_prev_charging_state: str | None = None
_prev_soc: float | None = None
_active_charging_session_id: int | None = None
_active_trip_id: int | None = None
_prev_odometer: float | None = None


def init_weconnect() -> None:
    global _weconnect
    if not settings.vw_username or not settings.vw_password:
        logger.info("No VW credentials configured — skipping WeConnect login")
        return
    try:
        from weconnect import weconnect as wc
        tokenfile = os.path.join(os.path.dirname(__file__), "..", "data", "weconnect_token.json")
        _weconnect = wc.WeConnect(
            username=settings.vw_username,
            password=settings.vw_password,
            tokenfile=tokenfile,
            updateAfterLogin=False,
            loginOnInit=False,
        )
        _weconnect.login()
        logger.info("WeConnect login successful")
    except Exception as exc:
        logger.error("WeConnect login failed: %s", exc)
        _weconnect = None


def reset_weconnect() -> None:
    """Tear down the existing session and re-authenticate (called after credential change)."""
    global _weconnect
    _weconnect = None
    init_weconnect()


def _safe_float(val) -> float | None:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _safe_bool(val) -> bool | None:
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    return str(val).lower() in ("true", "1", "yes", "locked", "connected")


def _get_vehicle():
    """Return the configured VIN's vehicle object, or first available."""
    if _weconnect is None:
        return None
    vehicles = _weconnect.vehicles
    if not vehicles:
        return None
    if settings.vw_vin and settings.vw_vin in vehicles:
        return vehicles[settings.vw_vin]
    return next(iter(vehicles.values()))


def _domain(vehicle, domain: str, status: str):
    """Return a status object from vehicle.domains, or None if absent."""
    try:
        return vehicle.domains[domain][status]
    except (KeyError, TypeError):
        return None


def _val(obj, attr: str):
    """Get .attribute.value, unwrapping enums to their string name."""
    try:
        a = getattr(obj, attr)
        v = a.value if hasattr(a, "value") else a
        # Enums have a nested .value; plain scalars don't
        if hasattr(v, "value"):
            return v.value
        return v
    except Exception:
        return None


def _extract_snapshot(vehicle) -> dict:
    """Pull all telemetry from a WeConnect vehicle object into a flat dict."""
    data: dict = {}

    try:
        # Battery / range  (domain: charging)
        bs = _domain(vehicle, "charging", "batteryStatus")
        if bs:
            data["soc_pct"] = _safe_float(_val(bs, "currentSOC_pct"))
            data["range_km"] = _safe_float(_val(bs, "cruisingRangeElectric_km"))
            if data.get("range_km") is not None:
                data["range_miles"] = data["range_km"] * 0.621371

        # Charging status  (domain: charging)
        cs = _domain(vehicle, "charging", "chargingStatus")
        if cs:
            data["charging_state"] = str(_val(cs, "chargingState") or "")
            data["charge_power_kw"] = _safe_float(_val(cs, "chargePower_kW"))
            data["charge_rate_km_h"] = _safe_float(_val(cs, "chargeRate_kmph"))
            data["charge_type"] = str(_val(cs, "chargeType") or "")
            data["remaining_charge_time_min"] = _safe_float(_val(cs, "remainingChargingTimeToComplete_min"))

        # Charging settings — target SoC  (domain: charging)
        cst = _domain(vehicle, "charging", "chargingSettings")
        if cst:
            data["target_soc_pct"] = _safe_float(_val(cst, "targetSOC_pct"))

        # Plug  (domain: charging)
        ps = _domain(vehicle, "charging", "plugStatus")
        if ps:
            conn = _val(ps, "plugConnectionState")
            data["plug_connected"] = conn == "CONNECTED" if conn else None

        # Parking position  (domain: parking)
        pp = _domain(vehicle, "parking", "parkingPosition")
        if pp:
            data["latitude"] = _safe_float(_val(pp, "latitude"))
            data["longitude"] = _safe_float(_val(pp, "longitude"))
            pt = _val(pp, "carCapturedTimestamp")
            data["parking_time"] = pt if isinstance(pt, datetime) else None

        # Climatisation status  (domain: climatisation)
        cl = _domain(vehicle, "climatisation", "climatisationStatus")
        if cl:
            data["climatisation_state"] = str(_val(cl, "climatisationState") or "")

        # Climatisation settings — target/outdoor temp  (domain: climatisation)
        clst = _domain(vehicle, "climatisation", "climatisationSettings")
        if clst:
            data["cabin_temp_c"] = _safe_float(_val(clst, "targetTemperature_C"))

        # Access — lock status  (domain: access)
        ac = _domain(vehicle, "access", "accessStatus")
        if ac:
            lock = _val(ac, "doorLockStatus")
            data["locked"] = lock == "LOCKED" if lock else None

        # Maintenance — odometer  (domain: maintenance)
        ms = _domain(vehicle, "maintenance", "maintenanceStatus")
        if ms:
            data["odometer_km"] = _safe_float(_val(ms, "mileage_km"))

    except Exception as exc:
        logger.warning("Error extracting snapshot: %s", exc)

    return data


def _update_charging_session(db: Session, snap: VehicleSnapshot) -> None:
    global _prev_charging_state, _active_charging_session_id, _prev_soc

    state = snap.charging_state
    is_charging = state == "CHARGING"

    if is_charging and _active_charging_session_id is None:
        # Session started
        session = ChargingSession(
            started_at=snap.recorded_at,
            soc_start_pct=snap.soc_pct,
            charge_type=snap.charge_type,
        )
        db.add(session)
        db.flush()
        _active_charging_session_id = session.id
        logger.info("Charging session %d started (SOC %.0f%%)", session.id, snap.soc_pct or 0)

    elif not is_charging and _active_charging_session_id is not None:
        # Session ended
        session = db.get(ChargingSession, _active_charging_session_id)
        if session:
            session.ended_at = snap.recorded_at
            session.soc_end_pct = snap.soc_pct
            if session.soc_start_pct and snap.soc_pct:
                delta_soc = snap.soc_pct - session.soc_start_pct
                # Rough kWh estimate: ID.4 usable capacity ~77 kWh
                session.kwh_added = round(delta_soc / 100 * 77.0, 2)
                session.cost = round(session.kwh_added * settings.electricity_rate_per_kwh, 2)
                if snap.range_km and session.soc_start_pct:
                    session.range_added_km = round(
                        (snap.range_km / snap.soc_pct) * delta_soc, 1
                    ) if snap.soc_pct else None
            logger.info("Charging session %d ended (SOC %.0f%%)", session.id, snap.soc_pct or 0)
        _active_charging_session_id = None

    _prev_charging_state = state
    _prev_soc = snap.soc_pct


def _update_trip(db: Session, snap: VehicleSnapshot) -> None:
    global _active_trip_id, _prev_odometer

    odometer = snap.odometer_km
    charging = snap.charging_state == "CHARGING"
    plug_in = snap.plug_connected

    # Moving = not charging, not plugged in, odometer increasing
    is_moving = not charging and not plug_in

    if is_moving and _active_trip_id is None and _prev_odometer is not None:
        trip = Trip(
            started_at=snap.recorded_at,
            soc_start_pct=snap.soc_pct,
            start_lat=snap.latitude,
            start_lon=snap.longitude,
            outdoor_temp_c=snap.outdoor_temp_c,
        )
        db.add(trip)
        db.flush()
        _active_trip_id = trip.id

    elif not is_moving and _active_trip_id is not None:
        trip = db.get(Trip, _active_trip_id)
        if trip and odometer and _prev_odometer:
            trip.ended_at = snap.recorded_at
            trip.soc_end_pct = snap.soc_pct
            trip.end_lat = snap.latitude
            trip.end_lon = snap.longitude
            dist = odometer - _prev_odometer
            trip.distance_km = round(dist, 2)
            trip.distance_miles = round(dist * 0.621371, 2)
            if trip.soc_start_pct and snap.soc_pct:
                kwh = (trip.soc_start_pct - snap.soc_pct) / 100 * 77.0
                trip.kwh_used = round(kwh, 2)
                if dist > 0:
                    trip.efficiency_kwh_100km = round(kwh / dist * 100, 1)
            logger.info("Trip %d ended (%.1f km)", trip.id, trip.distance_km or 0)
        _active_trip_id = None

    _prev_odometer = odometer


def poll() -> None:
    """Main poll callback — called by APScheduler every N seconds."""
    global _weconnect

    if _weconnect is None:
        init_weconnect()
        if _weconnect is None:
            return

    try:
        _weconnect.update()
    except Exception as exc:
        logger.error("WeConnect update failed: %s", exc)
        _weconnect = None
        return

    vehicle = _get_vehicle()
    if vehicle is None:
        logger.warning("No vehicle found after update")
        return

    raw = _extract_snapshot(vehicle)
    snap = VehicleSnapshot(recorded_at=datetime.now(timezone.utc), **raw)

    db: Session = SessionLocal()
    try:
        db.add(snap)
        _update_charging_session(db, snap)
        _update_trip(db, snap)
        db.commit()
        db.refresh(snap)
    except Exception as exc:
        logger.error("DB write failed: %s", exc)
        db.rollback()
        return
    finally:
        db.close()

    # Push live update to all WebSocket clients
    import asyncio
    payload = {
        "type": "snapshot",
        "soc_pct": snap.soc_pct,
        "range_miles": snap.range_miles,
        "charging_state": snap.charging_state,
        "charge_power_kw": snap.charge_power_kw,
        "plug_connected": snap.plug_connected,
        "locked": snap.locked,
        "outdoor_temp_c": snap.outdoor_temp_c,
        "recorded_at": snap.recorded_at.isoformat(),
    }
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(broadcast(payload))
    except RuntimeError:
        pass
