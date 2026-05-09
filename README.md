# VW-Dash

> **⚠️ Work in progress — not ready for use**
> This project is under active development. Expect missing features, breaking changes, and rough edges. Do not rely on it for anything important.

A self-hosted dashboard for VW ID.4 (and other WeConnect-compatible vehicles) that tracks battery state, trips, and charging sessions.

![Dashboard preview](docs/preview.png)

## Features

- **Live status** — SoC gauge, range, climate state, door locks, last updated time
- **Trip history** — distance, efficiency, energy used, cost per 100 km
- **Charging sessions** — kWh added, SoC delta, AC/DC type, estimated cost
- **Battery health** — SoH trend based on rated range
- **Settings UI** — credentials, currency, electricity rate, poll interval
- **VWsFriend importer** — bulk-import historical data from a VWsFriend PostgreSQL backup

## Quick start (Docker — recommended)

No clone needed. Download the compose file and start:

```bash
curl -O https://raw.githubusercontent.com/Mo3he/VW-Dash/main/docker-compose.yml
docker compose up -d
```

Open **http://localhost:3000**, go to **Settings**, and enter your VW WeConnect email and password. The app starts polling immediately — no config files to edit.

Data is persisted in a `./data/` folder next to the compose file.

> Only port **3000** needs to be exposed. The WebSocket for live status is proxied through it automatically.

## Quick start (local dev)

### Prerequisites

- Python 3.9+
- Node 18+

```bash
git clone https://github.com/Mo3he/VW-Dash.git
cd VW-Dash
./start.sh
```

Open **http://localhost:3000**, then configure via **Settings**.

To build and run the Docker image locally from source:

```bash
docker compose -f docker-compose.build.yml up -d
```

## Configuration

Everything is managed through the **Settings page** in the UI — no `.env` file needed. Settings are persisted to `data/config.json` (git-ignored).

| Setting | Default | Description |
|---|---|---|
| VW email | — | Your VW WeConnect email |
| VW password | — | Your VW WeConnect password |
| VIN | auto-detect | 17-character VIN (optional) |
| Poll interval | 300 s | How often to poll the VW API (min 60 s) |
| Electricity rate | 0.13 / kWh | Used to estimate charging cost |
| Currency symbol | kr | Displayed next to costs |
| Currency position | after | "100 kr" vs "$100" |
| Rated range | 410 km | Used for battery health (ID.4 RWD = 410, AWD = 337, Pro S = 418) |

## Importing from VWsFriend

If you have a VWsFriend PostgreSQL backup you can bulk-import its history:

```bash
# 1. Spin up a temporary Postgres container and restore the backup
docker run -d --name vwsfriend-tmp \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  postgres:13-alpine

docker cp /path/to/your.vwsfrienddbbackup vwsfriend-tmp:/tmp/backup
docker exec vwsfriend-tmp pg_restore -U postgres -d postgres \
  --create -F c /tmp/backup

# 2. Run the importer (from the backend/ directory)
cd backend
python import_vwsfriend.py --docker vwsfriend-tmp --db ../data/vwdash.db

# 3. Clean up
docker stop vwsfriend-tmp && docker rm vwsfriend-tmp
```

Options:

| Flag | Default | Description |
|---|---|---|
| `--docker` | `vwsfriend-tmp` | Docker container name |
| `--db` | `data/vwdash.db` | SQLite database path |
| `--battery-kwh` | `77.0` | Usable battery capacity for kWh estimation |
| `--wipe` | off | Delete existing data before importing |

## Project structure

```
VW-Dash/
├── backend/
│   ├── main.py              # FastAPI app
│   ├── models.py            # SQLAlchemy models
│   ├── config.py            # Settings (env + config.json)
│   ├── poller.py            # Background VW API polling
│   ├── import_vwsfriend.py  # VWsFriend migration script
│   └── routers/
│       ├── vehicle.py
│       ├── trips.py
│       ├── charging.py
│       └── settings_router.py
├── frontend/
│   └── src/
│       ├── app/             # Next.js pages
│       ├── components/      # Shared UI components
│       └── lib/             # API client & types
├── data/                    # SQLite DB + config.json (git-ignored)
├── docker-compose.yml
├── start.sh
└── .env.example
```

## Tech stack

- **Backend**: FastAPI · SQLAlchemy · APScheduler · WeConnect-python
- **Frontend**: Next.js 14 · Tailwind CSS · Recharts · Lucide icons
- **Database**: SQLite

## License

MIT
