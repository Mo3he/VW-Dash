# VW-Dash

A self-hosted dashboard for VW ID. series electric vehicles (ID.3, ID.4, ID.7, and other WeConnect-compatible models) that tracks battery state, trips, charging sessions, and more — with live WebSocket updates.

## Features

### Live status
- SoC gauge with range estimate
- Charge power, rate, and time remaining (while charging)
- Climate state, battery temperature, cabin temperature
- Door lock state and plug connection
- Live event feed — trip started/ended, charging started/ended, connector plugged/unplugged, climate changes, lock changes

### Trips
- Distance, efficiency (kWh/100 km), energy used, average speed, SoC delta
- Cost per 100 km based on your electricity rate
- Efficiency chart over time (follows selected period)
- Temperature vs efficiency breakdown
- Tap a trip card to expand an interactive route map
- Start/end address via reverse geocoding (OpenStreetMap Nominatim)
- Period filter: 7d · 30d · 90d · 1y · All · custom

### Journeys
- Trips grouped by day with combined distance and energy
- Expand a journey to see individual legs
- Most popular routes ranked by frequency
- Period filter with custom range

### Charging
- Per-session: SoC delta, kWh added, cost, peak/avg power, duration, charger name
- Inline edit for any session field (kWh actual, cost, rate, type, etc.)
- Charging stats: session count, total kWh, energy cost, range added, AC/DC split
- Battery cycle counter (total kWh ÷ usable capacity)
- Estimated vs actual kWh accuracy tracking
- Top chargers leaderboard
- Charge location map (Leaflet, OpenStreetMap) with dots sized by kWh
- Period filter: 7d · 30d · 90d · 1y · All · custom

### Battery health
- State-of-health trend based on rated range

### Settings
- VW WeConnect credentials and VIN, with **Test connection** button
- Vehicle name (shown in the top bar)
- Currency symbol and position, electricity rate, rated range, poll interval, battery capacity
- IANA timezone selector for all date/time display
- **Access token** — optional API authentication (required token shown as login gate in browser)
- **Webhook URL** — POST JSON notifications to ntfy.sh, Discord, Slack, or any HTTP endpoint on charge/trip events
- VWsFriend import — upload a backup file directly from the browser (idempotent; safe to re-run)
- Geocode missing addresses — backfills location data for imported history

### Analysis
- CO₂ saved vs petrol (7 L/100 km baseline)
- Vampire drain — average SoC loss per hour/day while parked
- Charging curve (kW over time per session)
- Period-over-period delta badges on all stat cards

## Quick start (Docker — recommended)

No clone needed. Download the compose file and start:

```bash
curl -O https://raw.githubusercontent.com/Mo3he/VW-Dash/main/docker-compose.yml
docker compose up -d
```

Open **http://localhost:3000**, go to **Settings**, and enter your VW WeConnect email and password. The app starts polling immediately — no config files to edit.

Data is persisted in a `./data/` folder next to the compose file.

> Only port **3000** needs to be exposed. The WebSocket for live status and the backend API are proxied through it automatically.

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
| VW password | — | Your VW WeConnect password (encrypted at rest with `SECRET_KEY` env var) |
| VIN | auto-detect | 17-character VIN (optional) |
| Vehicle name | ID.4 | Shown in the top bar |
| Poll interval | 300 s | How often to poll the VW API (min 60 s) |
| Electricity rate | 0.00 / kWh | Used to estimate charging cost |
| Currency symbol | $ | Displayed next to costs |
| Currency position | before | "$100" vs "100 kr" |
| Rated range | 410 km | Used for battery health (ID.4 RWD = 410, AWD = 337, Pro S = 418) |
| Battery capacity | 77 kWh | Used for cycle counting and efficiency (ID.4 77, ID.3 58, ID.7 86) |
| Timezone | UTC | IANA zone for all date/time display |
| Access token | — | If set, API and UI require this token (stored in `data/config.json`) |
| Webhook URL | — | POST JSON on charge/trip events (ntfy.sh, Discord, Slack, custom) |

### Security

Password encryption: if the `SECRET_KEY` environment variable is set (any 32-byte string), the VW password is encrypted in `data/config.json` using Fernet symmetric encryption.

API access control: set **Access token** in Settings. The dashboard will show a login gate. All API calls include `Authorization: Bearer <token>`.

```bash
# Docker — set SECRET_KEY in your compose environment
SECRET_KEY=your-32-char-secret docker compose up -d
```

## Importing from VWsFriend

Upload your VWsFriend PostgreSQL backup directly from the browser — go to **Settings → Import from VWsFriend** and select the `.vwsfrienddbbackup` file.

The import requires `pg_restore` to be installed on the machine running the backend:

```bash
# macOS
brew install libpq

# Debian/Ubuntu
apt-get install postgresql-client
```

After import, click **Geocode missing addresses** in Settings to fill in location names for trips and charging sessions. This runs at ~1 address/second in the background using OpenStreetMap Nominatim (no API key required).

## Location / geocoding

Addresses are resolved automatically when trips and charging sessions close during live polling. For historical data from VWsFriend, use the **Geocode missing addresses** button in Settings. Geocoding is rate-limited to 1 request/second per Nominatim's terms of service and deduplicates coordinates so a frequently visited location is only looked up once.

## Project structure

```
VW-Dash/
├── backend/
│   ├── main.py              # FastAPI app, migrations, auth middleware
│   ├── models.py            # SQLAlchemy models (Snapshot, Trip, TripPoint, ChargingSession, Event)
│   ├── config.py            # Settings (env + config.json overlay, Fernet password encryption)
│   ├── poller.py            # VW API polling, trip/session detection, geocoding, event emission
│   ├── geocoder.py          # Nominatim reverse geocoding helper
│   ├── webhook.py           # Fire-and-forget webhook notifications
│   ├── import_vwsfriend.py  # VWsFriend PostgreSQL backup importer
│   └── routers/
│       ├── vehicle.py       # Snapshots, history, battery health, vampire drain
│       ├── trips.py         # Trip list, stats, route, export CSV, delete
│       ├── charging.py      # Sessions, stats, curve, export CSV, delete
│       ├── events_router.py
│       ├── import_router.py
│       └── settings_router.py
├── frontend/
│   └── src/
│       ├── app/             # Next.js App Router pages (/, /trips, /charging, /journeys, /settings)
│       ├── components/      # Shared UI: SocGauge, ChargeMap, TripMap, EventsFeed, PeriodSelector, …
│       └── lib/             # API client & TypeScript types
├── data/                    # SQLite DB + config.json (git-ignored)
├── docker-compose.yml
├── start.sh
└── CLAUDE.md
```

## Tech stack

- **Backend**: FastAPI · SQLAlchemy · APScheduler · WeConnect-python
- **Frontend**: Next.js 15 · React 19 · Tailwind CSS · Recharts · Leaflet · Lucide icons
- **Database**: SQLite
- **Geocoding**: OpenStreetMap Nominatim (free, no API key)

## License

MIT
