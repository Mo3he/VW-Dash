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
import mqtt_client

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
# Website-portal provider: True when login reached an email-OTP challenge that the
# user must resolve via the Settings UI before telemetry can be fetched.
_portal_otp_pending: bool = False

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
# Last known per-window open/closed state, carried forward when a poll's accessStatus
# domain doesn't refresh (the car can go several polls without WeConnect returning fresh
# door/window data — see the lock-state fix in _extract_snapshot for the same class of gap).
# Without this, the Windows dashboard card blinks in and out on every such poll even though
# nothing about the car actually changed. Capped by _WINDOWS_CARRY_FORWARD_MAX so a long
# accessStatus outage hides the card again rather than silently showing days-old state.
_prev_windows_json: str | None = None
_prev_windows_json_at: datetime | None = None
_WINDOWS_CARRY_FORWARD_MAX = timedelta(hours=24)
# Parking-position based trip detection (mirrors VWsFriend PARKING_POSITION mode)
_prev_parking_time: datetime | None = None   # carCapturedTimestamp from last poll
_prev_lat: float | None = None               # last known parked latitude
_prev_lon: float | None = None               # last known parked longitude
_prev_soc_pct: float | None = None           # last known parked SoC %
_parking_time_unchanged_polls: int = 0       # consecutive polls with same parking_time
# Wall-clock time the odometer last increased — used to end odometer-fallback trips
# (website-portal mode has no GPS/parking_time, so a stalled odometer is the only
# signal that the car has parked).
_last_odometer_move_at: datetime | None = None

# Maximum breadcrumbs per trip before we stop recording (prevents unbounded growth)
_TRIP_POINT_CAP = 500
_trip_point_count: int = 0          # resets when a new trip starts
# Force-close a trip that has been open longer than this
_TRIP_MAX_DURATION_H = 24
# End an odometer-fallback trip (no parking_time available) once the odometer has
# been stable for this long. Computed per-poll from the poll interval so it stays
# robust across configurations; floored to avoid premature ends on slow city driving.
_TRIP_IDLE_END_MIN_S = 600

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
    global _prev_locked, _prev_plug_connected, _prev_climatisation_state, _last_odometer_move_at
    global _prev_windows_json

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
            # Give the resumed trip a fresh idle window so the odometer-idle end
            # (website-portal mode) doesn't fire spuriously on the first poll after
            # restart; it will close normally once the odometer stalls again.
            _last_odometer_move_at = datetime.now(timezone.utc)
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

        last_windows_snap = db.execute(
            _sel(VehicleSnapshot)
            .where(VehicleSnapshot.windows_json.is_not(None))
            .order_by(VehicleSnapshot.recorded_at.desc())
            .limit(1)
        ).scalars().first()
        if last_windows_snap:
            _prev_windows_json = last_windows_snap.windows_json
            _prev_windows_json_at = as_utc(last_windows_snap.recorded_at)
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

    # Read-only website-portal provider (attestation-free; volkswagen.<country>)
    if settings.vw_provider == "website_portal":
        _init_website_portal()
        return

    try:
        from carconnectivity import carconnectivity as cc_module
        # The volkswagen connector caches every status HTTP response for `interval` seconds
        # (min 180, default 300 when unset) and serves that cache regardless of how often we
        # call fetch_all() — so without this, our own poll_interval_seconds setting has no
        # effect on how fresh the data actually is: a fresh poll every 5 minutes could still
        # return a car-status snapshot that's up to another 5 minutes stale on top of that.
        # Tying the connector's interval to our own setting keeps them aligned.
        wc_interval = max(180, int(settings.poll_interval_seconds or 300))
        config = {
            "carConnectivity": {
                "connectors": [{
                    "type": "volkswagen",
                    "config": {
                        "username": settings.vw_username,
                        "password": settings.vw_password,
                        "interval": wc_interval,
                        # The connector only requests the "access" domain (doors + windows +
                        # lock state) from VW's API if the account's own /capabilities
                        # response lists it as enabled with no restrictions — for many
                        # accounts it's flagged/omitted there even though the underlying
                        # data is available, so it silently never gets asked for at all
                        # (not a data-availability gap, just never requested). This forces
                        # the request regardless, same as other WeConnect integrations do.
                        "force_enable_access": True,
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


def _schedule_confirmation_polls() -> None:
    """Force a couple of follow-up polls after a control command so the dashboard (even with
    no tab open) and MQTT pick up the car's new state without waiting for the next scheduled
    poll interval.

    This does NOT make the update appear quickly: the volkswagen connector caches every
    status HTTP response for `interval` seconds (tied to poll_interval_seconds, floor 180s —
    see init_weconnect()) and serves that cache regardless of how often fetch_all() is called,
    so a command's effect is invisible to us until that cache actually expires. Polling faster
    than that wastes a request without getting fresher data, and hammering VW's API is exactly
    what triggered the WAF lockout this app already had to work around once — so this schedules
    exactly two attempts spaced past the cache window rather than a tight retry loop.
    """
    interval = max(180, int(settings.poll_interval_seconds or 300))
    delays_sec = (interval + 15, interval * 2 + 15)

    def _worker():
        for delay in delays_sec:
            time.sleep(delay)
            try:
                poll()
            except Exception:
                logger.exception("Confirmation poll after control command failed")
    threading.Thread(target=_worker, daemon=True).start()


def set_climate(action: str) -> tuple[bool, str]:
    """Send a start/stop climatisation command to the vehicle.

    Returns (ok, message) so callers (HTTP router, MQTT command handler) don't
    need to know about carconnectivity's command objects.
    """
    from carconnectivity.command_impl import ClimatizationStartStopCommand
    vehicle = _get_vehicle()
    if vehicle is None:
        return False, "Vehicle not connected to WeConnect"
    clim = getattr(vehicle, 'climatization', None)
    cmds = getattr(clim, 'commands', None) if clim else None
    cmd = cmds.commands.get('start-stop') if cmds else None
    if cmd is None:
        return False, "Climatisation control not available for this vehicle"
    try:
        cmd.value = ClimatizationStartStopCommand.Command.START if action == "start" else ClimatizationStartStopCommand.Command.STOP
    except Exception as exc:
        return False, f"Climate command failed: {exc}"
    if not settings.use_mock_weconnect:
        _schedule_confirmation_polls()
    return True, "command_sent"


def set_charging(action: str) -> tuple[bool, str]:
    """Send a start/stop charging command to the vehicle. See set_climate() for return shape."""
    from carconnectivity.command_impl import ChargingStartStopCommand
    vehicle = _get_vehicle()
    if vehicle is None:
        return False, "Vehicle not connected to WeConnect"
    charging = getattr(vehicle, 'charging', None)
    cmds = getattr(charging, 'commands', None) if charging else None
    cmd = cmds.commands.get('start-stop') if cmds else None
    if cmd is None:
        return False, "Charging control not available for this vehicle"
    try:
        cmd.value = ChargingStartStopCommand.Command.START if action == "start" else ChargingStartStopCommand.Command.STOP
    except Exception as exc:
        return False, f"Charging command failed: {exc}"
    if not settings.use_mock_weconnect:
        _schedule_confirmation_polls()
    return True, "command_sent"


def set_window_heating(action: str) -> tuple[bool, str]:
    """Send a start/stop window-heating command to the vehicle. See set_climate() for return shape."""
    from carconnectivity.command_impl import WindowHeatingStartStopCommand
    vehicle = _get_vehicle()
    if vehicle is None:
        return False, "Vehicle not connected to WeConnect"
    window_heatings = getattr(vehicle, 'window_heatings', None)
    cmds = getattr(window_heatings, 'commands', None) if window_heatings else None
    cmd = cmds.commands.get('start-stop') if cmds else None
    if cmd is None:
        return False, "Window heating control not available for this vehicle"
    try:
        cmd.value = WindowHeatingStartStopCommand.Command.START if action == "start" else WindowHeatingStartStopCommand.Command.STOP
    except Exception as exc:
        return False, f"Window heating command failed: {exc}"
    if not settings.use_mock_weconnect:
        _schedule_confirmation_polls()
    return True, "command_sent"


def wake_vehicle() -> tuple[bool, str]:
    """Send a wake command to the vehicle, forcing VW to refresh its data. Returns (ok, message)."""
    from carconnectivity.command_impl import WakeSleepCommand
    vehicle = _get_vehicle()
    if vehicle is None:
        return False, "Vehicle not connected to WeConnect"
    cmds = getattr(vehicle, 'commands', None)
    cmd = cmds.commands.get('wake-sleep') if cmds else None
    if cmd is None:
        return False, "Wake command not available for this vehicle"
    try:
        cmd.value = WakeSleepCommand.Command.WAKE
    except Exception as exc:
        return False, f"Wake command failed: {exc}"
    if not settings.use_mock_weconnect:
        _schedule_confirmation_polls()
    return True, "command_sent"


def _init_website_portal() -> None:
    """Authenticate the read-only volkswagen.<country> website-portal provider."""
    global _weconnect, _wc_fail_count, _wc_next_retry, _portal_otp_pending
    try:
        from website_portal import WebsitePortalProvider
        provider = WebsitePortalProvider(
            email=settings.vw_username,
            password=settings.vw_password,
            country=settings.vw_country,
            vin=settings.vw_vin or None,
        )
        result = provider.login()
        if result == "otp_required":
            _weconnect = provider
            _portal_otp_pending = True
            logger.warning("Website portal requires an email OTP — submit it in Settings to continue")
            return
        _weconnect = provider
        _portal_otp_pending = False
        _wc_fail_count = 0
        _wc_next_retry = None
        logger.info("Website portal login successful (country=%s)", settings.vw_country)
    except Exception as exc:
        _wc_fail_count += 1
        delay = _backoff_seconds(_wc_fail_count)
        _wc_next_retry = datetime.now(timezone.utc) + timedelta(seconds=delay)
        logger.error("Website portal login failed (attempt %d, retry in %.0fs): %s", _wc_fail_count, delay, exc)
        _weconnect = None


def portal_auth_status() -> dict:
    """Report the website-portal auth state for the Settings UI."""
    connected = (
        _weconnect is not None
        and getattr(_weconnect, "is_website_portal", False)
        and not _portal_otp_pending
    )
    return {
        "provider": settings.vw_provider,
        "country": settings.vw_country,
        "connected": connected,
        "otp_required": _portal_otp_pending,
    }


def submit_portal_otp(code: str) -> dict:
    """Submit an email-OTP code to finish a pending website-portal login."""
    global _portal_otp_pending
    if not (_weconnect is not None and getattr(_weconnect, "is_website_portal", False)):
        raise RuntimeError("Website portal provider is not active")
    if not _portal_otp_pending:
        return {"status": "ok", "message": "No OTP pending"}
    result = _weconnect.submit_otp(code)
    if result == "ok":
        _portal_otp_pending = False
        return {"status": "ok"}
    return {"status": "otp_required"}


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

        # Window heating
        window_heatings = getattr(vehicle, 'window_heatings', None)
        if window_heatings:
            wh_state = _cc_attr_val(window_heatings, 'heating_state')
            if isinstance(wh_state, str):
                data["window_heating_state"] = wh_state

        # Lock state — the aggregate vehicle.doors.lock_state is the reliable source (live-
        # verified: correctly resolves to 'locked'/'unlocked'). Per-door lock_state is NOT
        # reliable on carconnectivity 0.11.8 — its Doors.Door class is constructed with
        # value=Doors.LockState (the class itself) instead of value_type=Doors.LockState, so
        # every per-door lock_state holds the raw enum class rather than a real member even
        # after the connector sets real data on it (live-verified: _cc_attr_val returns
        # <enum 'LockState'> for all doors, never an actual string). We still prefer per-door
        # data when it resolves to a real string, in case a future library version fixes
        # this, but broken per-door values must never override a working aggregate.
        doors = getattr(vehicle, 'doors', None)
        if doors:
            per_door_locks = [
                v for v in (
                    _cc_attr_val(door_obj, 'lock_state')
                    for door_obj in (getattr(doors, 'doors', None) or {}).values()
                )
                if isinstance(v, str)
            ]
            if per_door_locks:
                data["locked"] = all(v == "locked" for v in per_door_locks)
            else:
                lock_val = _cc_attr_val(doors, 'lock_state')
                if isinstance(lock_val, str):
                    data["locked"] = (lock_val == "locked")

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
                else:
                    logger.debug("Windows present but no per-window open_state this poll (accessStatus gap) — carrying forward last known state")
            else:
                logger.debug("No per-window data this poll (accessStatus gap) — carrying forward last known state")

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


def _close_trip(db: Session, trip: Trip, snap: VehicleSnapshot, ended_at: datetime | None = None) -> None:
    """Finalize an active trip row. Also called for the 24h force-close.

    ``ended_at`` overrides the trip end timestamp (used by the odometer-idle end
    path, where the actual park happened well before the poll that detects it).
    """
    global _trip_point_count
    odometer = snap.odometer_km
    end_time = ended_at or snap.recorded_at
    trip.ended_at = end_time
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
            duration_h = (as_utc(end_time) - as_utc(trip.started_at)).total_seconds() / 3600
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
    global _last_odometer_move_at

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
    if odometer_moved:
        _last_odometer_move_at = datetime.now(timezone.utc)

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

    # FALLBACK END: when parking_time is unavailable (website-portal mode), the car
    # never reports a parking position, so parking_appeared can never fire and a trip
    # would stay open until the 24h force-close. Instead, treat a stalled odometer as
    # the park signal: end the trip once the odometer has been stable long enough.
    idle_end_threshold_s = max(_TRIP_IDLE_END_MIN_S, 2 * settings.poll_interval_seconds)
    odometer_idle_end = (
        _active_trip_id is not None
        and not parking_time_available
        and not odometer_moved
        and _last_odometer_move_at is not None
        and (datetime.now(timezone.utc) - _last_odometer_move_at).total_seconds() >= idle_end_threshold_s
    )

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
            _last_odometer_move_at = datetime.now(timezone.utc)
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
    if _active_trip_id is not None and (definitely_parked or parking_appeared or odometer_idle_end):
        trip = db.get(Trip, _active_trip_id)
        if trip:
            # For an odometer-idle end the car actually parked back when the odometer
            # last moved; use that timestamp so trip duration/avg speed stay accurate.
            ended_at = _last_odometer_move_at if (odometer_idle_end and not definitely_parked and not parking_appeared) else None
            _close_trip(db, trip, snap, ended_at=ended_at)
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

    # Read-only website-portal provider returns a flat snapshot dict directly.
    if getattr(_weconnect, "is_website_portal", False):
        if _portal_otp_pending:
            logger.debug("Website portal awaiting OTP — skipping poll")
            return
        try:
            raw = _weconnect.get_snapshot()
        except Exception as exc:
            logger.error("Website portal fetch failed: %s", exc)
            try:
                _weconnect.shutdown()
            except Exception:
                pass
            _weconnect = None
            return
    else:
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

    global _prev_windows_json, _prev_windows_json_at
    now = datetime.now(timezone.utc)
    if raw.get("windows_json"):
        _prev_windows_json = raw["windows_json"]
        _prev_windows_json_at = now
    elif _prev_windows_json is not None and _prev_windows_json_at is not None and now - _prev_windows_json_at < _WINDOWS_CARRY_FORWARD_MAX:
        raw["windows_json"] = _prev_windows_json

    snap = VehicleSnapshot(recorded_at=now, **raw)

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
        "window_heating_state": snap.window_heating_state,
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

    try:
        mqtt_client.publish_snapshot(payload)
    except Exception as exc:
        logger.debug("MQTT publish skipped: %s", exc)
