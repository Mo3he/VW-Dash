# VW-Dash vs VWsFriend — Gap Analysis

Reference: https://github.com/tillsteinbach/VWsFriend/tree/main/vwsfriend

This document inventories what VWsFriend tracks/exposes that VW-Dash currently does not, plus places where VW-Dash's existing implementation could be improved by adopting VWsFriend's approach. It's scoped to features that are realistic to port given our SQLite + FastAPI + Next.js stack.

---

## 1. Side-by-side feature matrix

### Data domains

| Domain | VWsFriend | VW-Dash | Gap |
|---|---|---|---|
| Per-poll telemetry | `battery`, `range`, `battery_temperature`, `climatization`, `online` tables (one row per change) | Single denormalised [`VehicleSnapshot`](backend/models.py) row per poll | Different model — see §3.1 |
| Charging sessions | `charging_session` with `connected`/`locked`/`started`/`ended`/`unlocked`/`disconnected` lifecycle | `ChargingSession` with only `started_at`/`ended_at` | Missing lifecycle granularity (see §2.1) |
| Trips | `trip` (PARKING_POSITION or READINESS_STATUS mode) | `Trip` + `TripPoint` breadcrumbs (PARKING_POSITION) | Roughly parity; we have GPS breadcrumbs VWsFriend doesn't |
| Journeys | `journey` — user-defined grouping of trips with `title`/`description`/`tags` | `journeys/` page exists in [frontend/src/app/journeys](frontend/src/app/journeys/) | Need to verify backend support for user-defined journey grouping |
| Maintenance | `maintenance` — inspection + oil service, due_in_days/due_in_km | ❌ Nothing | **Missing** (see §2.2) |
| Warning lights | `warning_light` — messageId, text, category, priority, start/end, serviceLead, customerRelevance | ❌ Nothing | **Missing** (see §2.3) |
| Geofences | `geofence` — named zones with lat/lon/radius, linked to chargers/locations | ❌ Nothing | **Missing** (see §2.4) |
| Chargers | `charger` — id, name, max_power, operator, num_spots; `charging_session.charger_id` FK | Free-text `location_name` only | **Missing structured charger data** (see §2.5) |
| Geocoded locations | `location` table with osm_id, road, city, postcode, county, state, country, raw JSON | Single string column on Trip/ChargingSession | **Flat strings instead of structured addresses** (see §2.6) |
| Tags | `tag` with `use_trips`/`use_charges`/`use_refueling`/`use_journey` flags, M2M to all four | ❌ Nothing | **Missing** (see §2.7) |
| Online/offline | `online` table with onlineTime/offlineTime per session | ❌ Nothing | **Missing** (see §2.8) |
| Refuel sessions | `refuel_session` — for hybrids/ICE | ❌ Nothing | Skip — we target ID. series BEVs |
| WeConnect errors | `weconnect_error` log | ❌ Nothing (only Python logger) | **Missing** (see §2.9) |
| API response times | `weconnect_responsetime` | ❌ Nothing | Low priority — useful for diagnostics |
| Multi-vehicle | All tables FK `vehicle_vin`, supports many vehicles per install | Hard-wired to one `vw_vin` setting | **Missing** (see §2.10) |
| Settings | Per-vehicle DB-stored settings (`vehicle_settings`) | Global `data/config.json` | Adequate for single-vehicle |

### Integrations

| Integration | VWsFriend | VW-Dash | Gap |
|---|---|---|---|
| ABRP (A Better Route Planner) | Live telemetry feed: soc, range, lat/lon, is_parked, odometer, batt_temp, ext_temp, is_charging, power, is_dcfc | ❌ Nothing | **Missing** (see §2.11) |
| MQTT | Full broker integration with locale, TLS, topic filtering | ❌ Nothing | **Missing** (see §2.12) |
| Apple HomeKit | Battery, battery temp, charging, climatization, flashing (find car), locking, plug | ❌ Nothing | **Missing** (see §2.13) |
| Email/SMTP error alerts | Log-to-email handler with TLS, dedup | ❌ Nothing | Lower priority — webhook covers most |
| Webhook | ❌ Nothing | [`backend/webhook.py`](backend/webhook.py) | **VW-Dash advantage** |
| Grafana | First-class via docker-compose | ❌ Nothing | We have our own Recharts UI |
| HomeAssistant | Indirect via MQTT | ❌ Nothing | Subsumed by §2.12 |

### Controls

| Capability | VWsFriend (via HomeKit) | VW-Dash |
|---|---|---|
| Start/stop climatisation | ✅ | ✅ ([`/api/vehicle/climate`](backend/routers/vehicle.py)) |
| Lock/unlock | ✅ | ❌ |
| Flash/honk ("find my car") | ✅ | ❌ |
| Charging start/stop | ✅ | ❌ |
| Set target SoC | ✅ (via WeConnect-MQTT pass-through) | ❌ |
| Set max AC charge current | ✅ | ❌ |

### Privacy & UX

| Feature | VWsFriend | VW-Dash | Gap |
|---|---|---|---|
| `--privacy no-locations` flag | Drops GPS from trips/charging/refuel | ❌ All location data always recorded | **Missing** (see §4.1) |
| Locale / unit toggle | MQTT-only locale flag | UI hard-codes conversion at render time | Acceptable but could be a setting (see §4.2) |
| Timezone | Settings field | Settings field | Parity |

---

## 2. Missing features worth porting

### 2.1 Charging session lifecycle states
VWsFriend records six distinct timestamps per session: `connected → locked → started → ended → unlocked → disconnected`. We collapse this to `started_at`/`ended_at`.

**Why it matters:** lets you separate "time plugged in" from "time charging" — useful for spotting slow charger handshakes, paused sessions (battery hot/full), or scheduled-departure delays.

**Suggested change:** add `connected_at`, `unlocked_at`, `disconnected_at` columns to [`ChargingSession`](backend/models.py); detect transitions in [`poller.py`](backend/poller.py) by watching `plug_connected` + `chargingState` + lock state.

### 2.2 Maintenance tracking
VWsFriend has a `maintenance` table tracking `INSPECTION` and `OIL_SERVICE` events with `due_in_days` and `due_in_km`. The WeConnect `vehicleHealthInspection` domain exposes this; their `maintenance_agent` writes a row whenever the threshold is crossed (= service completed).

**Why it matters:** a dashboard for "next inspection due in 1,200 km / 47 days" is one of the most common asks for an EV companion app, and we already poll the data — we just throw it away.

**Suggested change:**
- Add `Maintenance` model with `kind` ('inspection' | 'oil_service'), `recorded_at`, `mileage_km`, `due_in_days`, `due_in_km`.
- In [`poller.py`](backend/poller.py) read `vehicle.domains["vehicleHealthInspection"]` and write a snapshot row per poll (or only on change). Add a "Maintenance" card to the dashboard.

### 2.3 Warning lights
VWsFriend logs every dashboard warning light with `messageId`, `text`, `category`, `priority`, `serviceLead`, `customerRelevance`, plus start/end mileage. WeConnect exposes these via the `vehicleHealthWarnings` domain.

**Why it matters:** silent recording of "low tire pressure", "service required", "12V battery low" — useful for diagnostics and history if dealer asks "when did this start?".

**Suggested change:** add `WarningLight` model; check the `vehicleHealthWarnings` domain each poll; emit an `Event` row on new lights (which the existing EventsFeed will pick up for free).

### 2.4 Geofences
Named zones (lat/lon/radius) that let you label "Home", "Work", "Mom's house". VWsFriend uses these to enrich session/trip location names without re-geocoding.

**Why it matters:** privacy-friendly alternative to reverse geocoding for places you know. Also unlocks "trips to/from Home" stats.

**Suggested change:** add a `Geofence` model + simple CRUD UI on a new `/settings/places` page. Update the geocoder fallback in [`poller.py`](backend/poller.py) to check geofences before calling Nominatim.

### 2.5 Structured chargers
VWsFriend has a `charger` table with `id`, `name`, `max_power`, `operator`, `num_spots`. Each `charging_session` has `charger_id` FK. Once a charger is identified by GPS proximity, all future sessions there get the same charger record — no more duplicate "Tesla Supercharger - 1234 Main St" strings.

**Why it matters:** charger-level stats ("avg session at Ionity München-Süd", "total kWh at Home charger"), and cleaner UI grouping.

**Suggested change:** add `Charger` model; assign a charger to a session by proximity (geofence-style lookup within ~50m). Use existing geocoder result for initial naming; allow user to rename.

### 2.6 Structured geocoded locations
We store the result of Nominatim reverse-geocoding as a single string. VWsFriend persists the full address breakdown (`road`, `city`, `postcode`, `state`, `country`, plus `raw` JSON).

**Why it matters:** filter trips by city/state, group charging by country, render addresses more flexibly on the frontend. Also avoids re-geocoding when we want a different presentation.

**Suggested change:** add a `Location` model keyed by `osm_id` (or rounded lat/lon for non-OSM hits); have `Trip`/`ChargingSession`/`TripPoint` reference it by FK. Migrate existing string addresses in a one-shot script.

### 2.7 Tags
User-defined labels with per-table opt-in (`use_trips`/`use_charges`/etc.).

**Why it matters:** "commute", "road trip", "errand", "DCFC", "free charging" — lets users slice their own history. Low-effort feature with high perceived value.

**Suggested change:** add `Tag` + association tables; tag pickers on the trip/session detail views.

### 2.8 Online/offline session tracking
A dedicated table for when the vehicle is reachable vs not. VWsFriend's `state_agent` watches `carCapturedTimestamp` staleness to decide.

**Why it matters:** distinguish "we couldn't reach the car" from "the car didn't change". Helps when debugging missing data or vampire-drain anomalies (currently we'd misattribute them).

**Suggested change:** add `Online` model; track via `carCapturedTimestamp` not advancing for >30 min. Surface as a small indicator on the dashboard.

### 2.9 Persisted WeConnect errors
VWsFriend stores API errors in `weconnect_error` (not just to logs). Useful when investigating "why was the data gap there".

**Why it matters:** Right now [`poller.py`](backend/poller.py) has retry/backoff logic but the only record of failures is in Python stderr — gone after the container restarts.

**Suggested change:** add a `WeconnectError` model logging each exception with timestamp + category. Expose under `/settings` → diagnostics. Useful complement to existing `EventsFeed`.

### 2.10 Multi-vehicle support
VWsFriend keys every table on `vehicle_vin`. We hardcode `settings.vw_vin`.

**Why it matters:** households with multiple ID.* cars (ID.3 + ID.4, ID.4 + ID.5, EV + plug-in hybrid) need separate dashboards today. Also useful for the VWsFriend importer when a backup contains two vehicles.

**Suggested change:** add `vehicle_vin` column to all snapshot/session/trip tables (nullable initially for back-compat); a `Vehicle` table for per-VIN metadata (name, capacity, EPA range, color); a vehicle selector in the nav. Caveat: this is the largest single migration in this doc — fine to defer until there's a second car in play.

### 2.11 ABRP integration
VWsFriend POSTs telemetry to `https://api.iternio.com/1/tlm/send` with: `utc, soc, est_battery_range, lat, lon, is_parked, odometer, batt_temp, ext_temp, is_charging, power, is_dcfc`.

**Why it matters:** A Better Route Planner is the standard EV trip-planning tool; live SoC feed makes its plans dramatically more accurate during a road trip.

**Suggested change:** add an optional ABRP module triggered from [`poller.py`](backend/poller.py) after each successful poll. New settings: `abrp_token`, `abrp_user_token`, `abrp_enabled`.

### 2.12 MQTT broker integration
VWsFriend has extensive MQTT support, which is the lingua franca for self-hosted home automation (Home Assistant, ioBroker, FHEM, Node-RED).

**Why it matters:** unlocks Home Assistant integration "for free" — many users will care about this more than the dashboard itself.

**Suggested change:** add an optional `paho-mqtt` publisher that broadcasts the same dict the WebSocket sends, with a configurable topic prefix. Make it opt-in via a settings toggle so non-MQTT users have no overhead.

### 2.13 HomeKit / vehicle controls
VWsFriend exposes lock, unlock, flash, climate, plug, charging as HomeKit accessories.

**Why it matters:** Siri "lock my car", "is the car charging", "where's my car" via Find My… plus iOS Home app widgets.

**Suggested change (low-effort first):** add the underlying control endpoints we're missing — `/api/vehicle/lock`, `/api/vehicle/unlock`, `/api/vehicle/flash`, `/api/vehicle/charging/start|stop`, `/api/vehicle/target-soc`. HomeKit bridge itself is a separate, larger project (HAP-python integration) and could be deferred.

---

## 3. Improvements to existing implementations

### 3.1 Snapshot schema is wide and lossy
[`VehicleSnapshot`](backend/models.py) is one row per poll containing ~20 nullable columns. VWsFriend normalises into `battery`, `range`, `climatization`, `battery_temperature`, `online` and only inserts when a value changes — much smaller DB footprint over years.

**Trade-off:** our denormalised schema is simpler to query and the SQLite file is small enough that growth probably isn't a real problem yet. But if you ever export a 5-year history or run the importer for a long-running VWsFriend instance, the difference is meaningful. Worth measuring DB size growth first before refactoring.

### 3.2 Trip detection mode
We already mirror VWsFriend's PARKING_POSITION mode (good — that's per the recent commit `b608190`). VWsFriend also has READINESS_STATUS as a fallback for when GPS isn't available. We do not. If a poll lands with no GPS fix at start/end, we currently fall through with no trip recorded.

**Suggested change:** add a `readinessStatus`-based fallback path in [`poller.py`](backend/poller.py) trip detection.

### 3.3 Trip distance — odometer vs GPS-summed
We currently use start/end odometer (good, more accurate than summing GPS). VWsFriend does the same. No change — calling this out so it isn't accidentally "improved" the wrong way.

### 3.4 Battery health metric
Our [`/api/vehicle/battery-health`](backend/routers/vehicle.py) extrapolates range-at-current-SoC to 100%. VWsFriend has no equivalent — this is one place we're ahead. Consider adding a kWh-based health metric too: integrate `kwh_added` per charging session vs SoC-delta over the same span, plot the implied usable pack capacity over time.

### 3.5 Geocoder uses Nominatim without storing OSM IDs
We call Nominatim and store the resulting display string. VWsFriend stores `osm_id` + `osm_type` so the same place always dedupes. We will re-geocode if the user clears the column or runs the importer twice.

**Suggested change:** when refactoring per §2.6, capture `osm_id`/`osm_type` from the Nominatim response.

### 3.6 Settings encryption
We already encrypt `vw_password` with Fernet (good — VWsFriend stores credentials in plaintext via CLI args or env vars). No change; calling this out as a VW-Dash advantage.

### 3.7 No webhook / event dispatcher abstraction
We have [`webhook.py`](backend/webhook.py) that POSTs to one URL. VWsFriend has none, but MQTT serves the same purpose more flexibly. If §2.12 is adopted, consider unifying: a single dispatcher fans out to webhook, MQTT, and future targets (Pushover, ntfy, Slack) instead of bolting each one onto [`poller.py`](backend/poller.py).

### 3.8 Importer covers a subset of VWsFriend tables
[`import_vwsfriend.py`](backend/import_vwsfriend.py) handles snapshots, charging sessions, and trips. Doesn't import: warning lights, maintenance history, online sessions, refuel sessions, chargers, locations, journeys, tags. Once any of §2.2/§2.3/§2.4/§2.5/§2.6/§2.7 land, extend the importer accordingly so existing VWsFriend users don't lose data on migration.

---

## 4. UX and polish gaps

### 4.1 No privacy toggle
VWsFriend's `--privacy no-locations` skips writing GPS to all trip/charging records. We have nothing equivalent.

**Suggested change:** add `record_locations: bool = True` to [`config.py`](backend/config.py); gate all `latitude`/`longitude` writes in [`poller.py`](backend/poller.py) on it.

### 4.2 Unit system is implicit
We store km internally and convert at render time. There's no per-user "I want miles everywhere" setting — every component decides independently. This works because the user is one person who knows what they want, but if multi-user or sharing screenshots becomes a thing, a single `units: 'metric' | 'imperial'` setting routed through context would be cleaner. Low priority.

### 4.3 No "versions" or "about" page
VWsFriend exposes a `/versions` page showing installed package versions of weconnect-cli, vwsfriend, etc. Helpful for filing bugs. We have nothing similar.

**Suggested change:** add `GET /api/health` returning git SHA + `weconnect` lib version + Python version, and render it under Settings.

### 4.4 No restart/reload UX
VWsFriend has a `/restart` template. We require docker/process restart for some config changes (anything not picked up live by [`config.py`](backend/config.py)'s next-poll overlay). Low priority since most settings *are* picked up on next poll.

---

## 5. Prioritised roadmap

Ranked by **(value to ID.* owners) × (effort to implement)**. Rough effort: S = under a day, M = 1–3 days, L = a week+.

### Tier 1 — high value, mostly small
1. **Warning lights tracking** (§2.3) — S. We already poll the data.
2. **Maintenance tracking** (§2.2) — S. Same as above.
3. **Vehicle controls — lock/unlock/flash/charge start-stop/target SoC** (§2.13 backend half) — S. Mirror the existing climate endpoint pattern.
4. **Privacy toggle** (§4.1) — S.
5. **Persisted WeConnect errors** (§2.9) — S.
6. **Charging session lifecycle states** (§2.1) — M. Schema migration + new state machine in poller.

### Tier 2 — moderate effort, high payoff
7. **ABRP integration** (§2.11) — M. Single new module, low blast radius.
8. **Tags** (§2.7) — M. Schema + UI work.
9. **Structured chargers** (§2.5) — M. Needs proximity-matching logic.
10. **Geofences** (§2.4) — M. CRUD UI + lookup integration.
11. **MQTT publisher** (§2.12) — M. Optional, opt-in.

### Tier 3 — larger refactors
12. **Multi-vehicle support** (§2.10) — L. Schema-wide change; defer until needed.
13. **Structured locations** (§2.6) — L. Migration of existing data is the bulk of the work.
14. **HomeKit bridge** (§2.13 frontend half) — L. Whole new daemon.
15. **Normalised snapshot schema** (§3.1) — L. Only worth it if DB growth becomes a real problem.

### Skip / defer indefinitely
- Refuel sessions (VW-Dash targets BEVs; hybrids don't have an ID. badge).
- Grafana integration (we have our own Next.js UI).
- WeConnect response-time metrics (low value, low effort, but no one will look at it).
