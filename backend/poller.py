from __future__ import annotations
"""
Polls the WeConnect API and persists snapshots + derived session/trip records.
Runs as an APScheduler background job inside the FastAPI process.
"""
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from config import settings
from database import SessionLocal
from geocoder import reverse_geocode
from models import ChargingSession, Event, Trip, TripPoint, VehicleSnapshot
from ws import broadcast
from utils import iso_utc

logger = logging.getLogger(__name__)

# --- WeConnect instance (created once at startup) ---
_weconnect: Any = None

# State carried between poll cycles to detect session boundaries
_prev_charging_state: str | None = None
_prev_soc: float | None = None
_active_charging_session_id: int | None = None
_active_trip_id: int | None = None
_prev_odometer: float | None = None
_trip_start_odometer: float | None = None
_charging_power_samples: list[float] = []
_prev_climatisation_state: str | None = None
_prev_locked: bool | None = None
_prev_plug_connected: bool | None = None


def _emit_event(db: Session, event_type: str, detail: str | None = None) -> None:
    db.add(Event(occurred_at=datetime.now(timezone.utc), event_type=event_type, detail=detail))


def init_state_from_db() -> None:
    """Recover in-memory trip/charging state from the DB after a restart."""
    global _active_trip_id, _trip_start_odometer, _active_charging_session_id, _prev_odometer

    db = SessionLocal()
    try:
        from sqlalchemy import text as _text

        # Resume any open trip
        row = db.execute(_text(
            "SELECT id FROM trips WHERE ended_at IS NULL ORDER BY started_at DESC LIMIT 1"
        )).fetchone()
        if row:
            _active_trip_id = row[0]
            logger.info("Resuming open trip id=%d", _active_trip_id)

        # Resume any open charging session
        row = db.execute(_text(
            "SELECT id FROM charging_sessions WHERE ended_at IS NULL ORDER BY started_at DESC LIMIT 1"
        )).fetchone()
        if row:
            _active_charging_session_id = row[0]
            logger.info("Resuming open charging session id=%d", _active_charging_session_id)

        # Seed prev odometer from the most recent snapshot that has one
        row = db.execute(_text(
            "SELECT odometer_km FROM vehicle_snapshots WHERE odometer_km IS NOT NULL ORDER BY recorded_at DESC LIMIT 1"
        )).fetchone()
        if row:
            _prev_odometer = row[0]
            if _active_trip_id:
                # Also try to recover trip start odometer from the snapshot nearest to trip start
                trip_row = db.execute(_text(
                    "SELECT started_at FROM trips WHERE id = :id"
                ), {"id": _active_trip_id}).fetchone()
                if trip_row:
                    odo_row = db.execute(_text(
                        "SELECT odometer_km FROM vehicle_snapshots WHERE odometer_km IS NOT NULL AND recorded_at <= :t ORDER BY recorded_at DESC LIMIT 1"
                    ), {"t": trip_row[0]}).fetchone()
                    if odo_row:
                        _trip_start_odometer = odo_row[0]
    except Exception as exc:
        logger.warning("Could not restore state from DB: %s", exc)
    finally:
        db.close()


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


def get_weconnect_vehicle():
    """Return the (WeConnect instance, vehicle) for control operations, or (None, None)."""
    return _weconnect, _get_vehicle()


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


def _car_ts(obj) -> Optional[datetime]:
    """Return carCapturedTimestamp.value from a GenericStatus object, or None."""
    try:
        v = obj.carCapturedTimestamp.value if obj else None
        return v if isinstance(v, datetime) else None
    except Exception:
        return None


def _extract_snapshot(vehicle) -> dict:
    """Pull all telemetry from a WeConnect vehicle object into a flat dict."""
    data: dict = {}
    car_timestamps: list[datetime] = []

    try:
        # Battery / range  (domain: charging)
        bs = _domain(vehicle, "charging", "batteryStatus")
        if bs:
            car_timestamps.append(ts) if (ts := _car_ts(bs)) else None
            data["soc_pct"] = _safe_float(_val(bs, "currentSOC_pct"))
            data["range_km"] = _safe_float(_val(bs, "cruisingRangeElectric_km"))
            if data.get("range_km") is not None:
                data["range_miles"] = data["range_km"] * 0.621371

        # Charging status  (domain: charging)
        cs = _domain(vehicle, "charging", "chargingStatus")
        if cs:
            car_timestamps.append(ts) if (ts := _car_ts(cs)) else None
            data["charging_state"] = str(_val(cs, "chargingState") or "")
            data["charge_power_kw"] = _safe_float(_val(cs, "chargePower_kW"))
            data["charge_rate_km_h"] = _safe_float(_val(cs, "chargeRate_kmph"))
            data["charge_type"] = str(_val(cs, "chargeType") or "")
            data["remaining_charge_time_min"] = _safe_float(_val(cs, "remainingChargingTimeToComplete_min"))

        # Charging settings — target SoC  (domain: charging)
        cst = _domain(vehicle, "charging", "chargingSettings")
        if cst:
            car_timestamps.append(ts) if (ts := _car_ts(cst)) else None
            data["target_soc_pct"] = _safe_float(_val(cst, "targetSOC_pct"))

        # Plug  (domain: charging)
        ps = _domain(vehicle, "charging", "plugStatus")
        if ps:
            car_timestamps.append(ts) if (ts := _car_ts(ps)) else None
            conn = _val(ps, "plugConnectionState")
            data["plug_connected"] = conn == "CONNECTED" if conn else None

        # Parking position  (domain: parking)
        pp = _domain(vehicle, "parking", "parkingPosition")
        if pp:
            car_timestamps.append(ts) if (ts := _car_ts(pp)) else None
            data["latitude"] = _safe_float(_val(pp, "latitude"))
            data["longitude"] = _safe_float(_val(pp, "longitude"))
            pt = _val(pp, "carCapturedTimestamp")
            data["parking_time"] = pt if isinstance(pt, datetime) else None

        # Climatisation status  (domain: climatisation)
        cl = _domain(vehicle, "climatisation", "climatisationStatus")
        if cl:
            car_timestamps.append(ts) if (ts := _car_ts(cl)) else None
            data["climatisation_state"] = str(_val(cl, "climatisationState") or "")

        # Climatisation settings — target cabin temp  (domain: climatisation)
        clst = _domain(vehicle, "climatisation", "climatisationSettings")
        if clst:
            car_timestamps.append(ts) if (ts := _car_ts(clst)) else None
            data["cabin_temp_c"] = _safe_float(_val(clst, "targetTemperature_C"))

        # Access — lock status: overallStatus is "safe" (locked) or "unsafe"
        ac = _domain(vehicle, "access", "accessStatus")
        if ac:
            car_timestamps.append(ts) if (ts := _car_ts(ac)) else None
            overall = _val(ac, "overallStatus")
            if overall is not None:
                data["locked"] = str(overall).lower() == "safe"

        # Odometer  (domain: measurements)
        om = _domain(vehicle, "measurements", "odometerStatus")
        if om:
            car_timestamps.append(ts) if (ts := _car_ts(om)) else None
            data["odometer_km"] = _safe_float(_val(om, "odometer"))

        # Battery temperature — values are in Kelvin  (domain: measurements)
        bt = _domain(vehicle, "measurements", "temperatureBatteryStatus")
        if bt:
            car_timestamps.append(ts) if (ts := _car_ts(bt)) else None
            t_min = _safe_float(_val(bt, "temperatureHvBatteryMin_K"))
            t_max = _safe_float(_val(bt, "temperatureHvBatteryMax_K"))
            if t_min is not None and t_max is not None:
                data["battery_temp_c"] = round((t_min + t_max) / 2 - 273.15, 1)

    except Exception as exc:
        logger.warning("Error extracting snapshot: %s", exc)

    data["car_captured_at"] = max(car_timestamps) if car_timestamps else None
    return data


def _update_charging_session(db: Session, snap: VehicleSnapshot) -> None:
    global _prev_charging_state, _active_charging_session_id, _prev_soc, _charging_power_samples

    state = snap.charging_state
    is_charging = state == "CHARGING"

    if is_charging and _active_charging_session_id is None:
        # Session started
        session = ChargingSession(
            started_at=snap.recorded_at,
            soc_start_pct=snap.soc_pct,
            charge_type=snap.charge_type,
            latitude=snap.latitude,
            longitude=snap.longitude,
        )
        db.add(session)
        db.flush()
        _active_charging_session_id = session.id
        _charging_power_samples = []
        if snap.charge_power_kw and snap.charge_power_kw > 0:
            _charging_power_samples.append(snap.charge_power_kw)
        _emit_event(db, "charging_started", f'{{"soc_pct": {snap.soc_pct}}}')
        logger.info("Charging session %d started (SOC %.0f%%)", session.id, snap.soc_pct or 0)

    elif is_charging and _active_charging_session_id is not None:
        # Mid-session: accumulate power samples and update peak
        if snap.charge_power_kw and snap.charge_power_kw > 0:
            _charging_power_samples.append(snap.charge_power_kw)
        session = db.get(ChargingSession, _active_charging_session_id)
        if session and snap.charge_power_kw:
            if session.peak_power_kw is None or snap.charge_power_kw > session.peak_power_kw:
                session.peak_power_kw = snap.charge_power_kw

    elif not is_charging and _active_charging_session_id is not None:
        # Session ended
        session = db.get(ChargingSession, _active_charging_session_id)
        if session:
            session.ended_at = snap.recorded_at
            session.soc_end_pct = snap.soc_pct
            if session.soc_start_pct and snap.soc_pct:
                delta_soc = snap.soc_pct - session.soc_start_pct
                session.kwh_added = round(delta_soc / 100 * 77.0, 2)
                session.cost_per_kwh = settings.electricity_rate_per_kwh
                session.cost = round(session.kwh_added * settings.electricity_rate_per_kwh, 2)
                if snap.range_km and snap.soc_pct:
                    session.range_added_km = round(
                        (snap.range_km / snap.soc_pct) * delta_soc, 1
                    )
            if _charging_power_samples:
                session.avg_power_kw = round(
                    sum(_charging_power_samples) / len(_charging_power_samples), 2
                )
            # Geocode charging location
            if session.latitude and session.longitude:
                session.location_name = reverse_geocode(session.latitude, session.longitude)
            _emit_event(db, "charging_ended", f'{{"soc_pct": {snap.soc_pct}, "kwh_added": {session.kwh_added}}}')
            logger.info("Charging session %d ended (SOC %.0f%%)", session.id, snap.soc_pct or 0)
        _active_charging_session_id = None
        _charging_power_samples = []

    _prev_charging_state = state
    _prev_soc = snap.soc_pct


def _update_trip(db: Session, snap: VehicleSnapshot) -> None:
    global _active_trip_id, _prev_odometer, _trip_start_odometer

    odometer = snap.odometer_km
    charging = snap.charging_state == "CHARGING"
    plug_in = snap.plug_connected

    # Moving = not charging and not plugged in.
    # Note: plug_in=None (unknown) is treated as not-plugged-in so we don't miss trips.
    is_moving = not charging and not plug_in

    if is_moving and _active_trip_id is None:
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
        _trip_start_odometer = odometer  # use current odometer as baseline; may be None
        _emit_event(db, "trip_started", f'{{"soc_pct": {snap.soc_pct}}}')

    elif is_moving and _active_trip_id is not None:
        # Mid-trip: record GPS breadcrumb
        if snap.latitude and snap.longitude:
            db.add(TripPoint(
                trip_id=_active_trip_id,
                recorded_at=snap.recorded_at,
                latitude=snap.latitude,
                longitude=snap.longitude,
            ))

    elif not is_moving and _active_trip_id is not None:
        trip = db.get(Trip, _active_trip_id)
        if trip and odometer and _trip_start_odometer:
            trip.ended_at = snap.recorded_at
            trip.soc_end_pct = snap.soc_pct
            trip.end_lat = snap.latitude
            trip.end_lon = snap.longitude
            dist = odometer - _trip_start_odometer
            if dist > 0:
                trip.distance_km = round(dist, 2)
                trip.distance_miles = round(dist * 0.621371, 2)
                duration_h = (snap.recorded_at - trip.started_at).total_seconds() / 3600
                if duration_h > 0:
                    trip.avg_speed_kmh = round(dist / duration_h, 1)
            if trip.soc_start_pct and snap.soc_pct and trip.soc_start_pct > snap.soc_pct:
                kwh = (trip.soc_start_pct - snap.soc_pct) / 100 * 77.0
                trip.kwh_used = round(kwh, 2)
                if dist and dist > 0:
                    trip.efficiency_kwh_100km = round(kwh / dist * 100, 1)
            # Geocode start and end addresses
            if trip.start_lat and trip.start_lon:
                trip.start_address = reverse_geocode(trip.start_lat, trip.start_lon)
            if trip.end_lat and trip.end_lon:
                trip.end_address = reverse_geocode(trip.end_lat, trip.end_lon)
            _emit_event(db, "trip_ended", f'{{"distance_km": {trip.distance_km}, "kwh_used": {trip.kwh_used}}}')
            logger.info("Trip %d ended (%.1f km)", trip.id, trip.distance_km or 0)
        _active_trip_id = None
        _trip_start_odometer = None

    _prev_odometer = odometer


def _update_misc_events(db: Session, snap: VehicleSnapshot) -> None:
    """Emit events for connector, climatisation, and lock state changes."""
    global _prev_climatisation_state, _prev_locked, _prev_plug_connected

    if _prev_plug_connected is not None and snap.plug_connected != _prev_plug_connected:
        event_type = "connector_connected" if snap.plug_connected else "connector_disconnected"
        _emit_event(db, event_type)

    clim = snap.climatisation_state
    if _prev_climatisation_state is not None and clim != _prev_climatisation_state:
        prev = (_prev_climatisation_state or "").upper()
        curr = (clim or "").upper()
        if curr not in ("OFF", "OFF_BY_REQUEST", "") and prev in ("OFF", "OFF_BY_REQUEST", ""):
            _emit_event(db, "climatisation_started")
        elif curr in ("OFF", "OFF_BY_REQUEST", "") and prev not in ("OFF", "OFF_BY_REQUEST", ""):
            _emit_event(db, "climatisation_stopped")

    if _prev_locked is not None and snap.locked != _prev_locked:
        _emit_event(db, "vehicle_locked" if snap.locked else "vehicle_unlocked")

    _prev_plug_connected = snap.plug_connected
    _prev_climatisation_state = snap.climatisation_state
    _prev_locked = snap.locked


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
        _update_misc_events(db, snap)
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
        "range_km": snap.range_km,
        "range_miles": snap.range_miles,
        "charging_state": snap.charging_state,
        "charge_power_kw": snap.charge_power_kw,
        "charge_rate_km_h": snap.charge_rate_km_h,
        "charge_type": snap.charge_type,
        "remaining_charge_time_min": snap.remaining_charge_time_min,
        "target_soc_pct": snap.target_soc_pct,
        "plug_connected": snap.plug_connected,
        "locked": snap.locked,
        "outdoor_temp_c": snap.outdoor_temp_c,
        "battery_temp_c": snap.battery_temp_c,
        "cabin_temp_c": snap.cabin_temp_c,
        "climatisation_state": snap.climatisation_state,
        "recorded_at": iso_utc(snap.recorded_at),
        "car_captured_at": iso_utc(snap.car_captured_at),
    }
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(broadcast(payload))
    except RuntimeError:
        pass
