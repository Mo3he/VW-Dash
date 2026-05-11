from __future__ import annotations
"""
Polls the WeConnect API and persists snapshots + derived session/trip records.
Runs as an APScheduler background job inside the FastAPI process.
"""
import asyncio
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
from ws import broadcast
from utils import as_utc, iso_utc
import webhook

logger = logging.getLogger(__name__)

# --- WeConnect instance (created once at startup) ---
_weconnect: Any = None
_wc_fail_count: int = 0          # consecutive login failures for backoff
_wc_next_retry: datetime | None = None   # earliest time to retry after backoff

# Serialize poll() so a scheduler tick and a manual trigger never overlap
_poll_lock = threading.Lock()

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
# Parking-position based trip detection (mirrors VWsFriend PARKING_POSITION mode)
_prev_parking_time: datetime | None = None   # carCapturedTimestamp from last poll
_prev_lat: float | None = None               # last known parked latitude
_prev_lon: float | None = None               # last known parked longitude

# Maximum breadcrumbs per trip before we stop recording (prevents unbounded growth)
_TRIP_POINT_CAP = 500
_trip_point_count: int = 0          # resets when a new trip starts
# Force-close a trip that has been open longer than this
_TRIP_MAX_DURATION_H = 24

# --- Background geocoding queue ---
_geo_queue: queue.Queue = queue.Queue()
_geo_thread_started = False


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
    global _trip_point_count, _prev_parking_time, _prev_lat, _prev_lon

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
            _prev_parking_time = last_snap.parking_time
            _prev_lat = last_snap.latitude
            _prev_lon = last_snap.longitude
    except Exception as exc:
        logger.warning("Could not restore state from DB: %s", exc)
    finally:
        db.close()


def _backoff_seconds(fail_count: int) -> float:
    """Exponential backoff: 30s, 60s, 120s, 240s, capped at 600s."""
    return min(30 * (2 ** (fail_count - 1)), 600)


def init_weconnect() -> None:
    global _weconnect, _wc_fail_count, _wc_next_retry
    if not settings.vw_username or not settings.vw_password:
        logger.info("No VW credentials configured — skipping WeConnect login")
        return
    if _wc_next_retry and datetime.now(timezone.utc) < _wc_next_retry:
        logger.debug("WeConnect login backoff active — skipping until %s", _wc_next_retry)
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
        _wc_fail_count = 0
        _wc_next_retry = None
        logger.info("WeConnect login successful")
    except Exception as exc:
        _wc_fail_count += 1
        delay = _backoff_seconds(_wc_fail_count)
        _wc_next_retry = datetime.now(timezone.utc) + timedelta(seconds=delay)
        logger.error("WeConnect login failed (attempt %d, retry in %.0fs): %s", _wc_fail_count, delay, exc)
        _weconnect = None


def reset_weconnect() -> None:
    """Tear down the existing session and re-authenticate (called after credential change)."""
    global _weconnect, _wc_fail_count, _wc_next_retry
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

        # Outdoor temperature — values are in Kelvin  (domain: measurements)
        ot = _domain(vehicle, "measurements", "outsideTemperatureStatus")
        if ot:
            car_timestamps.append(ts) if (ts := _car_ts(ot)) else None
            temp_k = _safe_float(_val(ot, "temperatureOutside_K"))
            if temp_k is not None:
                data["outdoor_temp_c"] = round(temp_k - 273.15, 1)

    except Exception as exc:
        logger.warning("Error extracting snapshot: %s", exc)

    data["car_captured_at"] = max(car_timestamps) if car_timestamps else None
    return data


def _update_charging_session(db: Session, snap: VehicleSnapshot) -> None:
    global _prev_charging_state, _active_charging_session_id, _prev_soc, _charging_power_samples

    state = snap.charging_state
    is_charging = state == "CHARGING"

    if is_charging and _active_charging_session_id is None:
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
        webhook.fire("charging_started", {"session_id": session.id, "soc_pct": snap.soc_pct, "charge_type": snap.charge_type})
        logger.info("Charging session %d started (SOC %.0f%%)", session.id, snap.soc_pct or 0)

    elif is_charging and _active_charging_session_id is not None:
        if snap.charge_power_kw and snap.charge_power_kw > 0:
            _charging_power_samples.append(snap.charge_power_kw)
        session = db.get(ChargingSession, _active_charging_session_id)
        if session and snap.charge_power_kw:
            if session.peak_power_kw is None or snap.charge_power_kw > session.peak_power_kw:
                session.peak_power_kw = snap.charge_power_kw

    elif not is_charging and _active_charging_session_id is not None:
        session = db.get(ChargingSession, _active_charging_session_id)
        if session:
            session.ended_at = snap.recorded_at
            session.soc_end_pct = snap.soc_pct
            if session.soc_start_pct and snap.soc_pct:
                delta_soc = snap.soc_pct - session.soc_start_pct
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
            _emit_event(db, "charging_ended", f'{{"soc_pct": {snap.soc_pct}, "kwh_added": {session.kwh_added}}}')
            webhook.fire("charging_ended", {"session_id": session.id, "soc_pct": snap.soc_pct, "kwh_added": session.kwh_added})
            logger.info("Charging session %d ended (SOC %.0f%%)", session.id, snap.soc_pct or 0)
            _queue_geocode("session", session.id)
        _active_charging_session_id = None
        _charging_power_samples = []

    _prev_charging_state = state
    _prev_soc = snap.soc_pct


def _close_trip(db: Session, trip: Trip, snap: VehicleSnapshot) -> None:
    """Finalize an active trip row. Also called for the 24h force-close."""
    global _trip_point_count
    odometer = snap.odometer_km
    trip.ended_at = snap.recorded_at
    trip.soc_end_pct = snap.soc_pct
    trip.end_lat = snap.latitude
    trip.end_lon = snap.longitude
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
    if trip.soc_start_pct and snap.soc_pct and trip.soc_start_pct > snap.soc_pct:
        kwh = (trip.soc_start_pct - snap.soc_pct) / 100 * settings.battery_capacity_kwh
        trip.kwh_used = round(kwh, 2)
        if dist and dist > 0:
            trip.efficiency_kwh_100km = round(kwh / dist * 100, 1)
    _emit_event(db, "trip_ended", f'{{"distance_km": {trip.distance_km}, "kwh_used": {trip.kwh_used}}}')
    webhook.fire("trip_ended", {"trip_id": trip.id, "distance_km": trip.distance_km, "kwh_used": trip.kwh_used})
    logger.info("Trip %d ended (%.1f km)", trip.id, trip.distance_km or 0)
    _queue_geocode("trip", trip.id)
    _trip_point_count = 0


def _update_trip(db: Session, snap: VehicleSnapshot) -> None:
    global _active_trip_id, _prev_odometer, _trip_start_odometer, _trip_point_count
    global _prev_parking_time, _prev_lat, _prev_lon

    odometer = snap.odometer_km
    charging = snap.charging_state == "CHARGING"
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

    # Definitive proof the car is not driving (plug in or actively charging)
    definitely_parked = plug_in or charging

    # PRIMARY signals — mirrors VWsFriend PARKING_POSITION mode:
    # carCapturedTimestamp going away means the car left its parking spot;
    # a new/changed timestamp means it arrived at a new parking spot.
    parking_disappeared = _prev_parking_time is not None and parking_time is None
    parking_appeared = parking_time is not None and parking_time != _prev_parking_time

    # FALLBACK for vehicles that never populate parking_time: use odometer delta
    odometer_moved = (
        odometer is not None
        and _prev_odometer is not None
        and odometer > _prev_odometer
    )
    # Only use the fallback when parking_time is consistently absent
    parking_time_available = parking_time is not None or _prev_parking_time is not None
    should_start_fallback = not parking_time_available and odometer_moved

    # --- START ---
    if _active_trip_id is None and not definitely_parked:
        if parking_disappeared or should_start_fallback:
            # When parking_disappeared, use the last known parked position as the
            # trip origin (current snap may have no GPS since the car just moved)
            start_lat = _prev_lat if parking_disappeared else snap.latitude
            start_lon = _prev_lon if parking_disappeared else snap.longitude
            trip = Trip(
                started_at=snap.recorded_at,
                soc_start_pct=snap.soc_pct,
                start_lat=start_lat,
                start_lon=start_lon,
                outdoor_temp_c=snap.outdoor_temp_c,
            )
            db.add(trip)
            db.flush()
            _active_trip_id = trip.id
            _trip_start_odometer = odometer
            _trip_point_count = 0
            _emit_event(db, "trip_started", f'{{"soc_pct": {snap.soc_pct}}}')
            webhook.fire("trip_started", {"trip_id": trip.id, "soc_pct": snap.soc_pct})

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

    _prev_odometer = odometer
    _prev_parking_time = parking_time
    # Keep last known good parked position for use as trip start origin
    if parking_time is not None:
        _prev_lat = snap.latitude
        _prev_lon = snap.longitude


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
