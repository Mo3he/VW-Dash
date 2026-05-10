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
from routers import charging, trips, vehicle, settings_router, import_router, events_router
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
            "ALTER TABLE vehicle_snapshots ADD COLUMN car_captured_at DATETIME",
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _run_migrations()
    init_state_from_db()
    init_weconnect()
    scheduler.add_job(
        poll,
        "interval",
        seconds=settings.poll_interval_seconds,
        id="poller",
        next_run_time=datetime.now(timezone.utc),  # run immediately on startup
    )
    scheduler.start()
    logger.info("Scheduler started — polling every %ds", settings.poll_interval_seconds)
    yield
    scheduler.shutdown()


app = FastAPI(title="VW Dash", lifespan=lifespan, redirect_slashes=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    token = settings.access_token
    if not token:
        return await call_next(request)
    # Health check and WebSocket are exempt
    if request.url.path in ("/api/health", "/ws"):
        return await call_next(request)
    auth = request.headers.get("Authorization", "")
    if auth == f"Bearer {token}":
        return await call_next(request)
    return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

app.include_router(vehicle.router)
app.include_router(charging.router)
app.include_router(trips.router)
app.include_router(settings_router.router)
app.include_router(import_router.router)
app.include_router(events_router.router)


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
    pkg = os.path.join(os.path.dirname(__file__), "..", "frontend", "package.json")
    try:
        with open(pkg) as f:
            return {"version": _json.load(f).get("version", "unknown")}
    except Exception:
        return {"version": "unknown"}
