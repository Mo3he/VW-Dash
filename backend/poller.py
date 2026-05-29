from __future__ import annotations
"""
Polls the WeConnect API and persists snapshots + derived session/trip records.
Runs as an APScheduler background job inside the FastAPI process.
"""
import asyncio
import json
import logging
import os
import queue
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from config import settings
from database import SessionLocal
from geocoder import reverse_geocode
from models import ChargingSession, Event, Trip, TripPoint, VehicleSnapshot
from routers.chargers import find_nearby
from ws import broadcast
from utils import as_utc, iso_utc
import webhook

logger = logging.getLogger(__name__)

# Main asyncio event loop — captured at startup so the poller thread can
# schedule coroutines onto it with run_coroutine_threadsafe.
_main_loop: asyncio.AbstractEventLoop | None = None

# Mock WeConnect instance — set when use_mock_weconnect=True
_mock_weconnect = None


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


# --- WeConnect instance (created once at startup) ---
_weconnect: Any = None
_wc_fail_count: int = 0          # consecutive login failures for backoff
_wc_next_retry: datetime | None = None   # earliest time to retry after backoff

# Serialize poll() so a scheduler tick and a manual trigger never overlap
_poll_lock = threading.Lock()

# Geocode jobs collected during a poll cycle, flushed after db.commit() so the
# worker always sees committed end_lat/end_lon values.
_pending_geocode: list[tuple[str, int]] = []

# State carried between poll cycles to detect session boundaries
_active_charging_session_id: int | None = None
# Consecutive polls where charging state was not CHARGING while a session was active.
# Used to debounce transient API dropouts — only close the session after 2+ polls.
_charging_glitch_polls: int = 0
_active_trip_id: int | None = None
_prev_odometer: float | None = None
_trip_start_odometer: float | None = None
_charging_power_samples: list[float] = []
_prev_climatisation_state: str | None = None
_prev_locked: bool | None = None
_prev_plug_connected: bool | None = None
# Parking-position based trip detection (mirrors VWsFriend PARKING_POSITION mode)
_prev_parking_time: datetime | None = None   # carCapturedTimestamp from last poll
_prev_lat: float | None = None               # last known parked latitude
_prev_lon: float | None = None               # last known parked longitude
_prev_soc_pct: float | None = None           # last known parked SoC %
_parking_time_unchanged_polls: int = 0       # consecutive polls with same parking_time

# Maximum breadcrumbs per trip before we stop recording (prevents unbounded growth)
_TRIP_POINT_CAP = 500
_trip_point_count: int = 0          # resets when a new trip starts
# Force-close a trip that has been open longer than this
_TRIP_MAX_DURATION_H = 24

# --- Background geocoding queue ---
_geo_queue: queue.Queue = queue.Queue()
_geo_thread_started = False


def _cc_attr_val(obj, *attrs):
    """Navigate a carconnectivity attribute chain and unwrap the final .value.

    Each step uses getattr with a None default so missing fields return None
    rather than raising.  The final object's .value is unwrapped once; if the
    value is itself an enum with a .value, that inner .value is returned too
    (carconnectivity stores enum attributes as EnumAttribute whose .value is
    the enum, and the enum's .value is the plain string/float).
    """
    try:
        for attr in attrs:
            if obj is None:
                return None
            obj = getattr(obj, attr, None)
        if obj is None:
            return None
        v = obj.value if hasattr(obj, 'value') else obj
        if hasattr(v, 'value'):   # unwrap nested enum
            return v.value
        return v
    except Exception:
        return None


def _geocoder_worker() -> None:
    """Background thread: drain the geocoding queue at ≤1 req/sec."""
    while True:
        try:
            item = _geo_queue.get(timeout=60)
        except queue.Empty:
            continue
        try:
            kind = item["kind"]
            obj_id = item["id"]
            db = SessionLocal()
            try:
                if kind == "trip":
                    trip = db.get(Trip, obj_id)
                    if trip:
                        if trip.start_lat and trip.start_lon and not trip.start_address:
                            trip.start_address = reverse_geocode(trip.start_lat, trip.start_lon)
                        if trip.end_lat and trip.end_lon and not trip.end_address:
                            trip.end_address = reverse_geocode(trip.end_lat, trip.end_lon)
                        db.commit()
                elif kind == "session":
                    session = db.get(ChargingSession, obj_id)
                    if session and session.latitude and session.longitude and not session.location_name:
                        session.location_name = reverse_geocode(session.latitude, session.longitude)
                        db.commit()
            finally:
                db.close()
        except Exception as exc:
            logger.warning("Geocoder worker error: %s", exc)
        finally:
            _geo_queue.task_done()


def _queue_geocode(kind: str, obj_id: int, *_coords) -> None:
    """Push a geocoding job onto the background queue (non-blocking)."""
    global _geo_thread_started
    if not _geo_thread_started:
        t = threading.Thread(target=_geocoder_worker, daemon=True)
        t.start()
        _geo_thread_started = True
    _geo_queue.put({"kind": kind, "id": obj_id})


def _emit_event(db: Session, event_type: str, detail: str | None = None) -> None:
    db.add(Event(occurred_at=datetime.now(timezone.utc), event_type=event_type, detail=detail))


def init_state_from_db() -> None:
    """Recover in-memory trip/charging state from the DB after a restart."""
    global _active_trip_id, _trip_start_odometer, _active_charging_session_id, _prev_odometer
    global _trip_point_count, _prev_parking_time, _prev_lat, _prev_lon, _prev_soc_pct
    global _prev_locked, _prev_plug_connected, _prev_climatisation_state

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
            # Recover how many breadcrumbs already exist for this trip
            count_row = db.execute(_text(
                "SELECT COUNT(*) FROM trip_points WHERE trip_id = :id"
            ), {"id": _active_trip_id}).fetchone()
            _trip_point_count = count_row[0] if count_row else 0

            # Close any other open trips — these are duplicates/orphans from a
            # previous crash or race condition; keep only the most recent one.
            stale = db.execute(_text(
                "SELECT id FROM trips WHERE ended_at IS NULL AND id != :current"
            ), {"current": _active_trip_id}).fetchall()
            if stale:
                now_utc = datetime.now(timezone.utc)
                for (stale_id,) in stale:
                    db.execute(_text(
                        "UPDATE trips SET ended_at = :now WHERE id = :id"
                    ), {"now": now_utc, "id": stale_id})
                    logger.warning("Closed dangling open trip id=%d on startup", stale_id)
                db.commit()

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
                trip_row = db.execute(_text(
                    "SELECT started_at FROM trips WHERE id = :id"
                ), {"id": _active_trip_id}).fetchone()
                if trip_row:
                    odo_row = db.execute(_text(
                        "SELECT odometer_km FROM vehicle_snapshots WHERE odometer_km IS NOT NULL AND recorded_at <= :t ORDER BY recorded_at DESC LIMIT 1"
                    ), {"t": trip_row[0]}).fetchone()
                    if odo_row:
                        _trip_start_odometer = odo_row[0]

        # Seed parking state from the most recent snapshot so the first poll
        # doesn't trigger a spurious parking_disappeared / parking_appeared event
        from sqlalchemy import select as _sel
        last_snap = db.execute(
            _sel(VehicleSnapshot).order_by(VehicleSnapshot.recorded_at.desc()).limit(1)
        ).scalars().first()
        if last_snap:
            # Intentionally do NOT seed _prev_parking_time here.
            # Seeding it causes a spurious trip on the first post-restart poll:
            # if the VW API returns a stale/different carCapturedTimestamp
            # (which it does routinely even while parked), parking_disappeared fires
            # → trip opens; next poll has a timestamp → parking_appeared fires → trip
            # closes, creating a zero-distance phantom trip every restart.
            # Leaving it as None means parking_disappeared can't fire on poll #1;
            # the first poll just establishes the baseline state safely.
            _prev_lat = last_snap.latitude
            _prev_lon = last_snap.longitude
            _prev_soc_pct = last_snap.soc_pct
            # Seed event-detection baselines so the first post-restart poll
            # doesn't create a blind spot where a lock/unlock/plug/climate
            # change goes undetected.
            _prev_locked = last_snap.locked
            _prev_plug_connected = last_snap.plug_connected
            _prev_climatisation_state = last_snap.climatisation_state
    except Exception as exc:
        logger.warning("Could not restore state from DB: %s", exc)
    finally:
        db.close()


def _backoff_seconds(fail_count: int) -> float:
    """Exponential backoff: 30s, 60s, 120s, 240s, capped at 600s."""
    return min(30 * (2 ** (fail_count - 1)), 600)


def get_mock_weconnect():
    """Return the active MockWeConnect instance, or None if not in mock mode."""
    return _mock_weconnect


def init_weconnect() -> None:
    global _weconnect, _wc_fail_count, _wc_next_retry, _mock_weconnect
    if settings.use_mock_weconnect:
        if _mock_weconnect is None:
            from mock_weconnect import MockWeConnect
            _mock_weconnect = MockWeConnect()
            logger.info("Mock WeConnect active — scenario: %s", _mock_weconnect._scenario_name)
        _weconnect = _mock_weconnect
        return
    if not settings.vw_username or not settings.vw_password:
        logger.info("No VW credentials configured — skipping WeConnect login")
        return
    if _wc_next_retry and datetime.now(timezone.utc) < _wc_next_retry:
        logger.debug("CarConnectivity login backoff active — skipping until %s", _wc_next_retry)
        return
    try:
        from carconnectivity import carconnectivity as cc_module
        config = {
            "carConnectivity": {
                "connectors": [{
                    "type": "volkswagen",
                    "config": {
                        "username": settings.vw_username,
                        "password": settings.vw_password,
                    }
                }]
            }
        }
        cc = cc_module.CarConnectivity(config=config)
        cc.startup()
        _weconnect = cc
        _wc_fail_count = 0
        _wc_next_retry = None
        logger.info("CarConnectivity login successful")
    except Exception as exc:
        _wc_fail_count += 1
        delay = _backoff_seconds(_wc_fail_count)
        _wc_next_retry = datetime.now(timezone.utc) + timedelta(seconds=delay)
        logger.error("CarConnectivity login failed (attempt %d, retry in %.0fs): %s", _wc_fail_count, delay, exc)
        _weconnect = None


def reset_weconnect() -> None:
    """Tear down the existing session and re-authenticate (called after credential change)."""
    global _weconnect, _wc_fail_count, _wc_next_retry
    if not settings.use_mock_weconnect and _weconnect is not None:
        try:
            _weconnect.shutdown()
        except Exception:
            pass
        _weconnect = None
    _wc_fail_count = 0
    _wc_next_retry = None
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
    try:
        garage = _weconnect.get_garage()
        vehicles = garage.list_vehicles()
        if not vehicles:
            return None
        if settings.vw_vin:
            v = garage.get_vehicle(settings.vw_vin)
            if v:
                return v
        return vehicles[0]
    except Exception:
        return None


def _extract_snapshot(vehicle) -> dict:
    """Pull all telemetry from a carconnectivity vehicle object into a flat dict."""
    data: dict = {}
    car_timestamps: list[datetime] = []

    try:
        # Electric drive — SoC, range, battery temperature
        drives_obj = getattr(vehicle, 'drives', None)
        drive = None
        if drives_obj:
            drives_dict = getattr(drives_obj, 'drives', {})
            drive = drives_dict.get('primary') or (next(iter(drives_dict.values()), None) if drives_dict else None)

        if drive:
            level_attr = getattr(drive, 'level', None)
            if level_attr and level_attr.value is not None:
                data["soc_pct"] = _safe_float(level_attr.value)
                if level_attr.last_updated:
                    car_timestamps.append(level_attr.last_updated)
            range_attr = getattr(drive, 'range', None)
            if range_attr and range_attr.value is not None:
                data["range_km"] = _safe_float(range_attr.value)
                if data.get("range_km") is not None:
                    data["range_miles"] = data["range_km"] * 0.621371
            battery = getattr(drive, 'battery', None)
            if battery:
                t_min_attr = getattr(battery, 'temperature_min', None)
                t_max_attr = getattr(battery, 'temperature_max', None)
                t_min = _safe_float(t_min_attr.value if t_min_attr else None)
                t_max = _safe_float(t_max_attr.value if t_max_attr else None)
                if t_min is not None:
                    data["battery_temp_min_c"] = round(t_min - 273.15, 1)
                if t_max is not None:
                    data["battery_temp_max_c"] = round(t_max - 273.15, 1)
                if t_min is not None and t_max is not None:
                    data["battery_temp_c"] = round((t_min + t_max) / 2 - 273.15, 1)

        # Charging state, power, type, plug, settings
        charging = getattr(vehicle, 'charging', None)
        if charging:
            state_attr = getattr(charging, 'state', None)
            if state_attr:
                data["charging_state"] = _cc_attr_val(charging, 'state') or ""
                if state_attr.last_updated:
                    car_timestamps.append(state_attr.last_updated)
            data["charge_power_kw"] = _safe_float(_cc_attr_val(charging, 'power'))
            data["charge_rate_km_h"] = _safe_float(_cc_attr_val(charging, 'rate'))
            data["charge_type"] = _cc_attr_val(charging, 'type') or ""
            # Remaining time from estimated_date_reached
            est_attr = getattr(charging, 'estimated_date_reached', None)
            if est_attr and est_attr.value:
                remaining = (est_attr.value - datetime.now(timezone.utc)).total_seconds() / 60
                data["remaining_charge_time_min"] = max(0.0, remaining)
            # Target SoC
            data["target_soc_pct"] = _safe_float(_cc_attr_val(charging, 'settings', 'target_level'))
            # Plug connected
            conn_val = _cc_attr_val(charging, 'connector', 'connection_state')
            if conn_val is not None:
                data["plug_connected"] = (str(conn_val) == "connected")

        # Position — latitude/longitude and parking_time for trip detection.
        # parking_time is None while driving (position unavailable); non-None while parked.
        # last_updated changes every poll but that is acceptable for the trip logic.
        position = getattr(vehicle, 'position', None)
        if position:
            lat_attr = getattr(position, 'latitude', None)
            lon_attr = getattr(position, 'longitude', None)
            lat = _safe_float(lat_attr.value if lat_attr else None)
            lon = _safe_float(lon_attr.value if lon_attr else None)
            data["latitude"] = lat
            data["longitude"] = lon
            if lat is not None and lat_attr:
                data["parking_time"] = lat_attr.last_updated
                if lat_attr.last_updated:
                    car_timestamps.append(lat_attr.last_updated)
            else:
                data["parking_time"] = None

        # Climatisation
        climatization = getattr(vehicle, 'climatization', None)
        if climatization:
            data["climatisation_state"] = _cc_attr_val(climatization, 'state') or ""
            data["cabin_temp_c"] = _safe_float(_cc_attr_val(climatization, 'settings', 'target_temperature'))

        # Lock state
        doors = getattr(vehicle, 'doors', None)
        if doors:
            lock_val = _cc_attr_val(doors, 'lock_state')
            if lock_val is not None:
                data["locked"] = (str(lock_val) == "locked")

        # Windows — open/closed state only (open percentage not available in carconnectivity)
        windows_obj = getattr(vehicle, 'windows', None)
        if windows_obj:
            windows_dict = getattr(windows_obj, 'windows', {})
            if windows_dict:
                windows_data: dict = {}
                for win_name, win_obj in windows_dict.items():
                    open_val = _cc_attr_val(win_obj, 'open_state')
                    if open_val is not None:
                        windows_data[str(win_name)] = {"state": str(open_val)}
                if windows_data:
                    data["windows_json"] = json.dumps(windows_data)

        # Odometer (km)
        odo_attr = getattr(vehicle, 'odometer', None)
        if odo_attr and odo_attr.value is not None:
            data["odometer_km"] = _safe_float(odo_attr.value)
            if odo_attr.last_updated:
                car_timestamps.append(odo_attr.last_updated)

        # Outside temperature — already in °C in carconnectivity
        ot_attr = getattr(vehicle, 'outside_temperature', None)
        if ot_attr and ot_attr.value is not None:
            data["outdoor_temp_c"] = _safe_float(ot_attr.value)

    except Exception as exc:
        logger.warning("Error extracting snapshot: %s", exc)

    data["car_captured_at"] = max(car_timestamps) if car_timestamps else None
    return data


def _update_charging_session(db: Session, snap: VehicleSnapshot) -> None:
    global _active_charging_session_id, _charging_power_samples, _charging_glitch_polls

    state = snap.charging_state
    is_charging = (state or "").upper() == "CHARGING"

    if is_charging and _active_charging_session_id is None:
        # Fall back to last known parked position if the parking domain isn't returning
        # coordinates right now (common while actively charging)
        lat = snap.latitude if snap.latitude is not None else _prev_lat
        lon = snap.longitude if snap.longitude is not None else _prev_lon
        session = ChargingSession(
            started_at=snap.recorded_at,
            soc_start_pct=snap.soc_pct,
            charge_type=snap.charge_type,
            latitude=lat,
            longitude=lon,
        )
        db.add(session)
        db.flush()
        _active_charging_session_id = session.id
        if lat and lon:
            nearby = find_nearby(db, lat, lon)
            if nearby:
                session.charger_id = nearby.id
                session.location_name = nearby.name
        _charging_glitch_polls = 0
        _charging_power_samples = []
        if snap.charge_power_kw and snap.charge_power_kw > 0:
            _charging_power_samples.append(snap.charge_power_kw)
        _emit_event(db, "charging_started", json.dumps({"soc_pct": snap.soc_pct}))
        webhook.fire("charging_started", {"session_id": session.id, "soc_pct": snap.soc_pct, "charge_type": snap.charge_type})
        logger.info("Charging session %d started (SOC %.0f%%)", session.id, snap.soc_pct or 0)

    elif is_charging and _active_charging_session_id is not None:
        _charging_glitch_polls = 0
        if snap.charge_power_kw and snap.charge_power_kw > 0:
            _charging_power_samples.append(snap.charge_power_kw)
        session = db.get(ChargingSession, _active_charging_session_id)
        if session and snap.charge_power_kw:
            if session.peak_power_kw is None or snap.charge_power_kw > session.peak_power_kw:
                session.peak_power_kw = snap.charge_power_kw

    elif not is_charging and _active_charging_session_id is not None:
        # Debounce: require 2 consecutive non-CHARGING polls before closing the session.
        # A single stale/missing API response should not split a real charge in two.
        _charging_glitch_polls += 1
        if _charging_glitch_polls < 2:
            return
        session = db.get(ChargingSession, _active_charging_session_id)
        if session:
            session.ended_at = snap.recorded_at
            session.soc_end_pct = snap.soc_pct
            if session.soc_start_pct and snap.soc_pct:
                delta_soc = snap.soc_pct - session.soc_start_pct
                if delta_soc > 0:
                    session.kwh_added = round(delta_soc / 100 * settings.battery_capacity_kwh, 2)
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
                if session.peak_power_kw is None:
                    session.peak_power_kw = round(max(_charging_power_samples), 2)
            _emit_event(db, "charging_ended", json.dumps({"soc_pct": snap.soc_pct, "kwh_added": session.kwh_added}))
            webhook.fire("charging_ended", {"session_id": session.id, "soc_pct": snap.soc_pct, "kwh_added": session.kwh_added})
            logger.info("Charging session %d ended (SOC %.0f%%)", session.id, snap.soc_pct or 0)
            _pending_geocode.append(("session", session.id))
        _active_charging_session_id = None
        _charging_glitch_polls = 0
        _charging_power_samples = []


def _close_trip(db: Session, trip: Trip, snap: VehicleSnapshot) -> None:
    """Finalize an active trip row. Also called for the 24h force-close."""
    global _trip_point_count
    odometer = snap.odometer_km
    trip.ended_at = snap.recorded_at
    trip.soc_end_pct = snap.soc_pct
    trip.end_lat = snap.latitude
    trip.end_lon = snap.longitude
    trip.odometer_end_km = odometer
    dist: float | None = None
    if odometer and _trip_start_odometer:
        raw_dist = odometer - _trip_start_odometer
        if raw_dist > 0:
            dist = raw_dist
            trip.distance_km = round(dist, 2)
            trip.distance_miles = round(dist * 0.621371, 2)
            duration_h = (snap.recorded_at - as_utc(trip.started_at)).total_seconds() / 3600
            if duration_h > 0:
                trip.avg_speed_kmh = round(dist / duration_h, 1)
    # Energy used: prefer SoC delta (coarse, whole-%) but fall back to range delta
    # when SoC didn't drop a full percent (short trips, quantization).
    kwh: float | None = None
    if trip.soc_start_pct and snap.soc_pct and trip.soc_start_pct > snap.soc_pct:
        kwh = (trip.soc_start_pct - snap.soc_pct) / 100 * settings.battery_capacity_kwh
    elif (
        trip.range_km_start is not None
        and snap.range_km is not None
        and trip.range_km_start > snap.range_km
        and settings.epa_rated_range_km > 0
    ):
        # Range-delta fallback: 1 km of indicated range ≈ battery_kwh / rated_range kWh
        range_drop = trip.range_km_start - snap.range_km
        kwh = range_drop / settings.epa_rated_range_km * settings.battery_capacity_kwh
    if kwh is not None and kwh > 0:
        trip.kwh_used = round(kwh, 2)
        if dist and dist > 0:
            trip.efficiency_kwh_100km = round(kwh / dist * 100, 1)
    _emit_event(db, "trip_ended", json.dumps({"distance_km": trip.distance_km, "kwh_used": trip.kwh_used}))
    webhook.fire("trip_ended", {"trip_id": trip.id, "distance_km": trip.distance_km, "kwh_used": trip.kwh_used})
    logger.info("Trip %d ended (%.1f km)", trip.id, trip.distance_km or 0)
    _pending_geocode.append(("trip", trip.id))
    _trip_point_count = 0


def _update_trip(db: Session, snap: VehicleSnapshot) -> None:
    global _active_trip_id, _prev_odometer, _trip_start_odometer, _trip_point_count
    global _prev_parking_time, _prev_lat, _prev_lon, _prev_soc_pct, _parking_time_unchanged_polls

    odometer = snap.odometer_km
    charging = (snap.charging_state or "").upper() == "CHARGING"
    plug_in = snap.plug_connected
    parking_time = snap.parking_time

    # Force-close stale open trip before anything else
    if _active_trip_id is not None:
        trip = db.get(Trip, _active_trip_id)
        if trip and trip.started_at:
            age_h = (datetime.now(timezone.utc) - as_utc(trip.started_at)).total_seconds() / 3600
            if age_h >= _TRIP_MAX_DURATION_H:
                logger.warning("Force-closing trip %d — open for %.1fh", trip.id, age_h)
                _close_trip(db, trip, snap)
                _active_trip_id = None
                _trip_start_odometer = None
                _parking_time_unchanged_polls = 0

    # Definitive proof the car is not driving (plug in or actively charging)
    definitely_parked = plug_in or charging

    # PRIMARY signals — mirrors VWsFriend PARKING_POSITION mode:
    # carCapturedTimestamp going away means the car left its parking spot;
    # a new/changed timestamp means it arrived at a new parking spot.
    parking_disappeared = _prev_parking_time is not None and parking_time is None
    parking_appeared = parking_time is not None and parking_time != _prev_parking_time

    # Track how many consecutive polls have seen the same parking_time (frozen API)
    if parking_time is not None and parking_time == _prev_parking_time:
        _parking_time_unchanged_polls += 1
    else:
        _parking_time_unchanged_polls = 0

    odometer_moved = (
        odometer is not None
        and _prev_odometer is not None
        and odometer > _prev_odometer
    )

    # FALLBACK A: parking_time has never been seen — use odometer delta
    parking_time_available = parking_time is not None or _prev_parking_time is not None
    should_start_odometer_fallback = not parking_time_available and odometer_moved

    # FALLBACK B: parking_time is present but frozen for 2+ polls while odometer moved.
    # This means WeConnect is returning a stale parkingPosition instead of clearing it,
    # so parking_disappeared will never fire. Use odometer as the signal instead.
    should_start_stale_parking = (
        _active_trip_id is None
        and not definitely_parked
        and _parking_time_unchanged_polls >= 2
        and odometer_moved
    )

    should_start_fallback = should_start_odometer_fallback or should_start_stale_parking

    # --- START ---
    if _active_trip_id is None and not definitely_parked:
        if parking_disappeared or should_start_fallback:
            # When parking_disappeared, use the last known parked position as the
            # trip origin (current snap may have no GPS since the car just moved)
            start_lat = _prev_lat if parking_disappeared else snap.latitude
            start_lon = _prev_lon if parking_disappeared else snap.longitude
            start_soc = _prev_soc_pct if parking_disappeared else snap.soc_pct
            start_odo = _prev_odometer if parking_disappeared else odometer
            trip = Trip(
                started_at=snap.recorded_at,
                soc_start_pct=start_soc,
                range_km_start=snap.range_km,
                start_lat=start_lat,
                start_lon=start_lon,
                outdoor_temp_c=snap.outdoor_temp_c,
                odometer_start_km=start_odo,
            )
            db.add(trip)
            db.flush()
            _active_trip_id = trip.id
            # When parking_disappeared, the current odometer may already be mid-drive
            # (car has been moving since the last poll). Use _prev_odometer — the value
            # from the last parked poll — as the true trip start, same as we do for lat/lon/soc.
            _trip_start_odometer = start_odo
            _trip_point_count = 0
            trigger = "parking_disappeared" if parking_disappeared else ("stale_parking" if should_start_stale_parking else "odometer")
            logger.info("Trip %d started (trigger=%s, soc=%.0f%%)", trip.id, trigger, start_soc or 0)
            _emit_event(db, "trip_started", json.dumps({"soc_pct": start_soc}))
            webhook.fire("trip_started", {"trip_id": trip.id, "soc_pct": start_soc})

    # --- BREADCRUMBS ---
    elif _active_trip_id is not None and not definitely_parked and not parking_appeared:
        if snap.latitude and snap.longitude and _trip_point_count < _TRIP_POINT_CAP:
            db.add(TripPoint(
                trip_id=_active_trip_id,
                recorded_at=snap.recorded_at,
                latitude=snap.latitude,
                longitude=snap.longitude,
            ))
            _trip_point_count += 1

    # --- END ---
    # Use separate `if` (not `elif`) so it can fire on the same poll as a breadcrumb
    if _active_trip_id is not None and (definitely_parked or parking_appeared):
        trip = db.get(Trip, _active_trip_id)
        if trip:
            _close_trip(db, trip, snap)
        _active_trip_id = None
        _trip_start_odometer = None
        _parking_time_unchanged_polls = 0  # reset so next drive starts fresh

    _prev_odometer = odometer
    _prev_parking_time = parking_time
    # Keep last known good parked position for use as trip start origin
    if parking_time is not None:
        _prev_lat = snap.latitude
        _prev_lon = snap.longitude
        _prev_soc_pct = snap.soc_pct


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

    if not _poll_lock.acquire(blocking=False):
        logger.debug("Poll already in progress — skipping this tick")
        return
    try:
        _do_poll()
    finally:
        _poll_lock.release()


def _do_poll() -> None:
    global _weconnect

    if _weconnect is None:
        init_weconnect()
        if _weconnect is None:
            return

    try:
        _weconnect.fetch_all()
    except Exception as exc:
        logger.error("CarConnectivity fetch failed: %s", exc)
        try:
            _weconnect.shutdown()
        except Exception:
            pass
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
        _pending_geocode.clear()
        return
    finally:
        db.close()

    # Dispatch geocode jobs only after the commit so the worker always sees
    # committed end_lat/end_lon and end coordinates are not skipped.
    for _geo_kind, _geo_id in _pending_geocode:
        _queue_geocode(_geo_kind, _geo_id)
    _pending_geocode.clear()

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
        "windows": json.loads(snap.windows_json) if snap.windows_json else None,
        "outdoor_temp_c": snap.outdoor_temp_c,
        "battery_temp_c": snap.battery_temp_c,
        "battery_temp_min_c": snap.battery_temp_min_c,
        "battery_temp_max_c": snap.battery_temp_max_c,
        "cabin_temp_c": snap.cabin_temp_c,
        "climatisation_state": snap.climatisation_state,
        "recorded_at": iso_utc(snap.recorded_at),
        "car_captured_at": iso_utc(snap.car_captured_at),
    }
    if _main_loop is not None and _main_loop.is_running():
        asyncio.run_coroutine_threadsafe(broadcast(payload), _main_loop)
    else:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(broadcast(payload))
        except RuntimeError:
            pass
