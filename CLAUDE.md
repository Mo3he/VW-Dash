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
- **`poller.py`** — APScheduler background job that calls WeConnect API and writes `VehicleSnapshot` rows. Also detects trip start/end and charging session boundaries from snapshot diffs
- **`ws.py`** — WebSocket connection manager; `poller.py` broadcasts JSON after each poll
- **`config.py`** — `Settings` class using pydantic-settings. Reads from env vars, then overlays `data/config.json` (written when user saves Settings in the UI). Config changes take effect on next poll
- **`database.py`** — SQLAlchemy async engine targeting `data/vwdash.db`
- **`models.py`** — Three core tables: `VehicleSnapshot` (every poll), `ChargingSession`, `Trip`
- **`routers/`** — Thin API routers for vehicle, trips, charging, settings, and import

Migrations are handled manually in `main.py`'s `_run_migrations()` function (raw `ALTER TABLE` statements), not via Alembic CLI despite Alembic being installed.

### Frontend (`frontend/src/`)
Next.js 15 + React 19 + TypeScript + Tailwind CSS:
- **`app/`** — App Router pages: `/` (dashboard), `/trips`, `/charging`, `/settings`
- **`app/DashboardClient.tsx`** — Main dashboard; connects to WebSocket via `useVehicleLive` hook for real-time updates
- **`hooks/useVehicleLive.ts`** — WebSocket hook that auto-reconnects and merges live data with HTTP-fetched initial state
- **`lib/api.ts`** — All HTTP fetch calls to `/api/*`
- **`lib/types.ts`** — TypeScript interfaces mirroring backend Pydantic models
- **`components/`** — Shared UI: `SocGauge`, `SocHistory` (Recharts), `StatusCard`, `Nav`

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
