# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Git Rules

- **Never** add `Co-Authored-By` or any Claude/AI attribution lines to commit messages.

## What This Is

VW-Dash is a self-hosted dashboard for Volkswagen ID. series electric vehicles. It polls the VW WeConnect API on a configurable interval, stores telemetry in a local SQLite database, and serves a Next.js frontend with live WebSocket updates.

## Development Commands

### Local Development (Recommended)
```bash
./start.sh          # Starts both backend (port 8000) and frontend (port 3000) with hot reload
```

Backend only:
```bash
cd backend
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Frontend only:
```bash
cd frontend
npm run dev         # Dev server on port 3000
npm run build       # Production build
npm run lint        # ESLint
```

### Mock server (no real VW credentials needed)

A built-in mock WeConnect provider lets you develop and test without a real car.
Set `USE_MOCK_WECONNECT=1` to activate it:

```bash
# Terminal 1 — backend with mock
cd backend && source .venv/bin/activate
USE_MOCK_WECONNECT=1 DB_PATH=/tmp/vwdash_test.db \
  python -m uvicorn main:app --host 127.0.0.1 --port 8001

# Terminal 2 — frontend pointing at mock backend
cd frontend
# Create frontend/.env.local (git-ignored):
# BACKEND_URL=http://127.0.0.1:8001
# NEXT_PUBLIC_WS_URL=ws://127.0.0.1:8001/ws
npm run dev -- --port 3000
```

Built-in scenarios (advance with `POST /api/vehicle/poll`):

| Scenario | Behaviour |
|---|---|
| `parked` | Permanently parked, plug disconnected, SoC 70% |
| `charging` | Plug connected, SoC climbing 1%/tick from 40% to 90% |
| `driving` | Odometer ticks up ~2 km/tick |
| `trip_then_charge` | Full sequence: parked → driving → parked → charging → parked |

Override individual state fields mid-run:
```bash
curl -X POST http://127.0.0.1:8001/api/dev/state \
  -H 'Content-Type: application/json' \
  -d '{"fields": {"climatisation_state": "ventilation", "windows": {"frontLeft": 45}}}'
```

### Running tests
```bash
cd backend && source .venv/bin/activate
lsof -ti:8001 | xargs kill -9 2>/dev/null
rm -f /tmp/vwdash_test.db
USE_MOCK_WECONNECT=1 DB_PATH=/tmp/vwdash_test.db \
  python -m uvicorn main:app --host 127.0.0.1 --port 8001 &
sleep 2
python tests/test_e2e_mock.py
```

### Docker
```bash
docker compose -f docker-compose.build.yml up -d   # Build & run locally
docker compose up -d                                 # Run pre-built image from GHCR
```

### Backend API Docs
When running locally: http://localhost:8000/docs (FastAPI auto-generated Swagger UI)

## Architecture

### Request Flow
- All external traffic enters on **port 3000** (Next.js)
- Next.js proxies `/api/*` and `/ws` to the FastAPI backend on **port 8000** (internal only)
- The frontend never directly exposes the Python backend

### Backend (`backend/`)
Python 3.11 + FastAPI application:
- **`main.py`** — App setup, lifespan context manager (starts scheduler + WeConnect), mounts all routers
- **`poller.py`** — APScheduler background job that calls WeConnect API and writes `VehicleSnapshot` rows. Also detects trip start/end and charging session boundaries from snapshot diffs. Monkey-patches `AccessStatus.Window.update` to capture `windowOpen_pct` without log warnings
- **`mock_weconnect.py`** — Drop-in WeConnect replacement for dev/testing. Activated by `USE_MOCK_WECONNECT=1`. Runs a state-machine through built-in scenarios (parked/charging/driving/trip_then_charge). Thread-safe; state can be overridden via `/api/dev/*`
- **`ws.py`** — WebSocket connection manager; `poller.py` broadcasts JSON after each poll
- **`config.py`** — `Settings` class using pydantic-settings. Reads from env vars, then overlays `data/config.json` (written when user saves Settings in the UI). Config changes take effect on next poll
- **`database.py`** — SQLAlchemy async engine targeting `data/vwdash.db`
- **`models.py`** — Three core tables: `VehicleSnapshot` (every poll), `ChargingSession`, `Trip`. `VehicleSnapshot` includes `windows_json` (JSON-encoded per-window open state/percentage)
- **`routers/`** — Thin API routers for vehicle, trips, charging, settings, and import
  - **`vehicle.py`** — includes `POST /climate?action=start|stop` and `POST /charging-control?action=start|stop`
  - **`dev_router.py`** — dev-only endpoints (`/api/dev/state`, `/api/dev/scenario`) for mock state overrides; only mounted when `USE_MOCK_WECONNECT=1`

Migrations are handled manually in `main.py`'s `_run_migrations()` function (raw `ALTER TABLE` statements), not via Alembic CLI despite Alembic being installed.

### Frontend (`frontend/src/`)
Next.js 15 + React 19 + TypeScript + Tailwind CSS:
- **`app/`** — App Router pages: `/` (dashboard), `/trips`, `/charging`, `/settings`
- **`app/DashboardClient.tsx`** — Main dashboard; connects to WebSocket via `useVehicleLive` hook for real-time updates. Contains Climate control and Charging control toggle cards
- **`hooks/useVehicleLive.ts`** — WebSocket hook that auto-reconnects and merges live data with HTTP-fetched initial state. WS URL resolved from `NEXT_PUBLIC_WS_URL` env var (falls back to relative `ws://{host}/ws` for production)
- **`lib/api.ts`** — All HTTP fetch calls to `/api/*`
- **`lib/types.ts`** — TypeScript interfaces mirroring backend Pydantic models
- **`components/`** — Shared UI: `SocGauge`, `SocHistory` (Recharts), `StatusCard`, `Nav`, `WindowStatus`

#### Local dev env vars (`frontend/.env.local`, git-ignored)
```
BACKEND_URL=http://127.0.0.1:8001        # proxied by Next.js for /api/* SSR calls
NEXT_PUBLIC_WS_URL=ws://127.0.0.1:8001/ws  # WebSocket URL baked into the client bundle
```

### Data Storage
- **`data/vwdash.db`** — SQLite database (all telemetry)
- **`data/config.json`** — User settings (credentials, currency, rates). This file is git-ignored. If missing, defaults from `config.py` apply

### Unit System
The backend stores distances in **km** internally. The UI displays miles or km based on a conversion at render time — there is no per-user unit preference stored; conversion happens in frontend components.

## Key Design Decisions

- **Single SQLite file** — no external database needed; `data/` is a Docker volume mount
- **Polling, not push** — WeConnect has no webhook support; APScheduler drives all data freshness
- **Trip/session detection is stateful** — `poller.py` infers trip and charging session boundaries by comparing consecutive snapshots (SoC changes, plug state, speed). Edge cases around incomplete sessions at startup are handled by checking for open records on boot
- **Settings UI is the config system** — There is no `.env` file workflow for end users; credentials are entered in the Settings page and written to `data/config.json`
- **VWsFriend importer** — `backend/import_vwsfriend.py` is a standalone script to migrate data from VWsFriend PostgreSQL backups into the local SQLite DB
- **Window open percentage** — `windowOpen_pct` is not a standard WeConnect field; `poller.py` monkey-patches `AccessStatus.Window.update` to stash it as `_open_pct` before the library processes the dict (which would otherwise emit a WARNING for unknown keys)
- **Mock server** — `mock_weconnect.py` implements the same interface as the real `weconnect` library. `poller.py` checks `USE_MOCK_WECONNECT` and calls `get_mock_weconnect()` instead of initialising the real client. This keeps mock code entirely out of the production path
