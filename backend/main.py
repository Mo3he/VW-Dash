import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

# Ensure pg_restore is findable on macOS when libpq is keg-only
_LIBPQ_BIN = "/opt/homebrew/opt/libpq/bin"
if os.path.isdir(_LIBPQ_BIN) and _LIBPQ_BIN not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _LIBPQ_BIN + ":" + os.environ.get("PATH", "")

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings
from database import Base, engine
from sqlalchemy import text
from poller import init_weconnect, init_state_from_db, poll
from jose import jwt as _jwt, JWTError
from routers import charging, trips, vehicle, settings_router, import_router, events_router, chargers as chargers_router, auth as auth_router, stats as stats_router, geocoder_router
from ws import connect, disconnect

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def _run_migrations() -> None:
    """Add columns that may be missing from older databases."""
    with engine.connect() as conn:
        for stmt in [
            "ALTER TABLE vehicle_snapshots ADD COLUMN battery_temp_c FLOAT",
            "ALTER TABLE charging_sessions ADD COLUMN cost_per_kwh FLOAT",
            "ALTER TABLE charging_sessions ADD COLUMN kwh_added_real FLOAT",
            "ALTER TABLE charging_sessions ADD COLUMN avg_power_kw FLOAT",
            "ALTER TABLE charging_sessions ADD COLUMN latitude FLOAT",
            "ALTER TABLE charging_sessions ADD COLUMN longitude FLOAT",
            "ALTER TABLE charging_sessions ADD COLUMN location_name TEXT",
            "ALTER TABLE trips ADD COLUMN start_address TEXT",
            "ALTER TABLE trips ADD COLUMN end_address TEXT",
            "ALTER TABLE trips ADD COLUMN range_km_start FLOAT",
            "ALTER TABLE vehicle_snapshots ADD COLUMN car_captured_at DATETIME",
            "ALTER TABLE charging_sessions ADD COLUMN charger_id INTEGER",
            "ALTER TABLE vehicle_snapshots ADD COLUMN battery_temp_min_c FLOAT",
            "ALTER TABLE vehicle_snapshots ADD COLUMN battery_temp_max_c FLOAT",
            "ALTER TABLE vehicle_snapshots ADD COLUMN windows_json TEXT",
        ]:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception as exc:
                msg = str(exc).lower()
                if "duplicate column" in msg or "already exists" in msg:
                    pass  # column already present — safe to ignore
                else:
                    logger.error("Migration failed: %s — %s", stmt, exc)
                    raise


def _backfill_avg_power() -> None:
    """Compute avg_power_kw for sessions where it is NULL.

    Tries snapshot-based averaging first (for natively recorded sessions).
    Falls back to kwh_added / duration_h for imported sessions that have no snapshots.
    """
    from sqlalchemy.orm import Session as OrmSession
    from models import ChargingSession, VehicleSnapshot
    from sqlalchemy import select, func

    with OrmSession(engine) as db:
        sessions = db.scalars(
            select(ChargingSession).where(
                ChargingSession.avg_power_kw.is_(None),
                ChargingSession.ended_at.is_not(None),
            )
        ).all()
        updated = 0
        for s in sessions:
            # Try snapshot average first
            avg = db.scalar(
                select(func.avg(VehicleSnapshot.charge_power_kw)).where(
                    VehicleSnapshot.recorded_at >= s.started_at,
                    VehicleSnapshot.recorded_at <= s.ended_at,
                    VehicleSnapshot.charge_power_kw.is_not(None),
                    VehicleSnapshot.charge_power_kw > 0,
                )
            )
            if avg is not None:
                s.avg_power_kw = round(float(avg), 2)
                updated += 1
            elif s.kwh_added and s.kwh_added > 0 and s.started_at and s.ended_at:
                # Fall back: derive from energy / duration
                duration_h = (s.ended_at - s.started_at).total_seconds() / 3600
                if duration_h > 0:
                    s.avg_power_kw = round(s.kwh_added / duration_h, 2)
                    updated += 1
        if updated:
            db.commit()
            logger.info("Backfilled avg_power_kw for %d charging sessions", updated)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _run_migrations()
    _backfill_avg_power()
    init_state_from_db()
    init_weconnect()
    # Capture the running event loop so poller threads can broadcast via WS
    from poller import set_event_loop as _set_poller_loop
    _set_poller_loop(asyncio.get_event_loop())
    scheduler.add_job(
        poll,
        "interval",
        seconds=settings.poll_interval_seconds,
        id="poller",
        next_run_time=datetime.now(timezone.utc),  # run immediately on startup
    )
    scheduler.start()
    logger.info("Scheduler started — polling every %ds", settings.poll_interval_seconds)
    # Give the settings router a reference so poll_interval_seconds PATCH takes live effect
    from routers.settings_router import set_scheduler as _set_scheduler
    _set_scheduler(scheduler)
    yield
    scheduler.shutdown()


app = FastAPI(title="VW Dash", lifespan=lifespan, redirect_slashes=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


_AUTH_EXEMPT = {"/api/auth/login", "/api/auth/setup", "/api/health", "/api/version"}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path

    # Always-public paths
    if path in _AUTH_EXEMPT or path == "/ws":
        return await call_next(request)

    # Dev endpoints are local-only and only exist in mock mode — no auth needed
    if settings.use_mock_weconnect and path.startswith("/api/dev"):
        return await call_next(request)

    # Settings GET is public so the Next.js server-side layout render can read UI prefs
    if request.method == "GET" and path == "/api/settings":
        return await call_next(request)

    # No-auth mode: if no users exist yet, allow everything (first-run / setup)
    with engine.connect() as conn:
        user_count = conn.execute(text("SELECT COUNT(*) FROM users")).scalar() or 0
    if user_count == 0:
        return await call_next(request)

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    try:
        payload = _jwt.decode(auth[7:], settings.jwt_secret, algorithms=["HS256"])
        request.state.jwt_payload = payload
    except JWTError:
        return JSONResponse(status_code=401, content={"detail": "Invalid or expired token"})

    return await call_next(request)

app.include_router(auth_router.router)
app.include_router(vehicle.router)
app.include_router(charging.router)
app.include_router(chargers_router.router)
app.include_router(trips.router)
app.include_router(settings_router.router)
app.include_router(import_router.router)
app.include_router(events_router.router)
app.include_router(stats_router.router)
app.include_router(geocoder_router.router)

if settings.use_mock_weconnect:
    from routers.dev_router import router as dev_router
    app.include_router(dev_router)
    logger.info("Dev router mounted at /api/dev (mock mode active)")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await connect(ws)
    try:
        while True:
            await ws.receive_text()  # keep connection alive; we only push server→client
    except WebSocketDisconnect:
        await disconnect(ws)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/version")
def version():
    import json as _json
    import urllib.request as _req
    pkg = os.path.join(os.path.dirname(__file__), "..", "frontend", "package.json")
    current = "unknown"
    try:
        with open(pkg) as f:
            current = _json.load(f).get("version", "unknown")
    except Exception:
        pass
    latest = None
    try:
        with _req.urlopen(
            "https://api.github.com/repos/Mo3he/VW-Dash/releases/latest",
            timeout=5,
        ) as resp:
            data = _json.loads(resp.read())
            tag = data.get("tag_name", "")
            latest = tag.lstrip("v") if tag else None
    except Exception:
        pass
    return {"version": current, "latest_version": latest}
