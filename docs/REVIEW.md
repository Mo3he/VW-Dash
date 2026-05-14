# VW-Dash — Project Review

> Original snapshot: 2026-05-10. Re-audited 2026-05-10 after the fix pass. Re-audited 2026-05-11 after the UI/auth/theming pass. Re-audited 2026-05-12 after the charge detection fix pass.
> **Legend:** ✅ done · ⚠️ partial · ❌ not done · ➖ won't-fix / out of scope

> **Heads-up:** the original review flagged plaintext password storage. The repo now supports Fernet-at-rest, but **rotating the leaked credential is still a manual step the operator must do** — the encryption only protects newly written passwords. See item #7.

---

## 🔴 Critical bugs

### 1. ✅ `battery_capacity_kwh` setting is silently ignored
Fixed. All hardcoded `77.0` references in the live math are gone:
- [backend/poller.py:398](backend/poller.py#L398) — `delta_soc / 100 * settings.battery_capacity_kwh`
- [backend/poller.py:439](backend/poller.py#L439) — same in `_close_trip`
- [backend/recover_trips.py:133](backend/recover_trips.py#L133) — uses `_settings.battery_capacity_kwh`
- [backend/import_vwsfriend.py](backend/import_vwsfriend.py) keeps `77.0` only as a default function parameter; the import endpoint passes the live setting in.

### 2. ✅ `outdoor_temp_c` extraction
Added at [backend/poller.py:344-350](backend/poller.py#L344-L350). Reads `measurements.outsideTemperatureStatus.temperatureOutside_K` and converts to °C. The temperature-vs-efficiency chart is no longer empty for new data.

### 3. ✅ Trip-never-ends without odometer
[backend/poller.py:495-499](backend/poller.py#L495-L499) now always calls `_close_trip(...)` when not-moving fires; odometer is only used inside `_close_trip` to compute distance — its absence no longer prevents the trip from closing. A 24h force-close (`_TRIP_MAX_DURATION_H`) is also in place.

### 4. ✅ Race conditions on shared poller state
`threading.Lock` at [backend/poller.py:33](backend/poller.py#L33); `poll()` acquires non-blocking and skips overlapping ticks ([poller.py:534-540](backend/poller.py#L534-L540)). Module-level globals are now only mutated under that lock.

### 5. ✅ SoC quantization on short trips
`_close_trip` tries SoC delta first, then falls back to a `cruisingRangeElectric_km` delta when SoC didn't drop a full percent ([backend/poller.py](backend/poller.py) — `range_drop / settings.epa_rated_range_km * settings.battery_capacity_kwh`). Requires `epa_rated_range_km` to be configured. For trips so short that neither SoC nor range changes, 0 kWh is the correct result — the API provides no finer-grained energy signal.

### 6. ✅ ChargeMap cleanup leak
[frontend/src/components/ChargeMap.tsx:8,17-21,67-71](frontend/src/components/ChargeMap.tsx#L8) — Leaflet instance is held in a `useRef`, removed on cleanup, and reset before re-init.

---

## 🟠 Security & privacy

### 7. ⚠️ Password storage
Encryption at rest is implemented:
- [backend/config.py:14-43](backend/config.py#L14-L43) — Fernet helpers
- `_save_config_file` encrypts to `vw_password_enc` when `SECRET_KEY` is present; `_load_config_file` decrypts transparently.
- README documents the `SECRET_KEY` env var with a Docker example.

Caveats: if `SECRET_KEY` is *not* set, the password still lands in `config.json` plaintext (matches today's deploys, but worth a docs nudge). `vw_password_file` / Docker-secret support is **not** done.

### 8. ✅ Authentication
Full JWT-based multi-user auth:
- [backend/main.py:85-96](backend/main.py#L85-L96) — auth middleware (exempts `/api/health`, `/api/auth/setup`, `/api/auth/login`, `/ws`, and GET `/api/settings`)
- [backend/routers/auth.py](backend/routers/auth.py) — setup, login, user management (create, delete, change password), admin gate
- [frontend/src/lib/auth.ts](frontend/src/lib/auth.ts) + [frontend/src/components/AuthGate.tsx](frontend/src/components/AuthGate.tsx) — token storage in `localStorage`, login/setup forms
- [frontend/src/app/settings/SettingsForm.tsx](frontend/src/app/settings/SettingsForm.tsx) — Users section with add, remove, and change-password UI

Resolved: `passlib`+`bcrypt>=4.0` incompatibility (`ValueError: password cannot be longer than 72 bytes`) fixed by pinning `bcrypt<4.0.0` in `requirements.txt`.

### 9. ✅ Nominatim user-agent
[backend/geocoder.py:17](backend/geocoder.py#L17) — `VW-Dash/1.0 (self-hosted EV dashboard; https://github.com/Mo3he/VW-Dash)`.

### 10. ✅ Configurable CORS
[backend/config.py:66](backend/config.py#L66) — `cors_origins` setting; main.py splits on commas. Defaults still cover localhost dev.

---

## 🟡 Reliability / correctness

### 11. ❌ Migrations are ad-hoc raw SQL
Still in [backend/main.py:29-53](backend/main.py#L29-L53). Alembic is in `requirements.txt` but unused (no `backend/migrations/` directory exists — it was never created). Error handling **was** improved (#13), but the broader Alembic conversion did not happen.

### 12. ✅ Geocoding moved off the polling path
Background queue + daemon worker thread at [backend/poller.py:54-98](backend/poller.py#L54-L98); `_close_trip` and the charging-end path call `_queue_geocode(...)` instead of `reverse_geocode(...)` inline.

### 13. ✅ `_run_migrations()` error handling
[backend/main.py:46-53](backend/main.py#L46-L53) — only swallows "duplicate column" / "already exists"; logs and re-raises everything else.

### 14. ✅ `datetime.utcnow()` removed
[backend/models.py:15](backend/models.py#L15) and [models.py:113](backend/models.py#L113) now use `lambda: datetime.now(timezone.utc)`.

### 15. ❌ SQLite naive-datetime mismatch
Not addressed. Storage is still naive-UTC by convention; no chokepoint coercion. Acceptable as long as nothing inserts local-time values, but remains a latent bug.

### 16. ✅ WeConnect login backoff
Exponential backoff (30s → 600s cap) at [backend/poller.py:157-159](backend/poller.py#L157-L159) and [poller.py:184-189](backend/poller.py#L184-L189). `init_weconnect()` honors `_wc_next_retry`.

### 17. ✅ Idempotent VWsFriend import
[backend/import_vwsfriend.py](backend/import_vwsfriend.py) — each of the three import functions checks for an existing row by primary timestamp (`recorded_at` / `started_at`) before inserting. Re-running no longer duplicates.

### 18. ✅ WebSocket thread-safe
[backend/ws.py](backend/ws.py) — `set` + `asyncio.Lock`; `broadcast()` snapshots under the lock before iterating, then prunes dead sockets under the lock.

### 19. ✅ Pydantic validation on settings PATCH
[backend/routers/settings_router.py:22-25](backend/routers/settings_router.py#L22-L25) — `poll_interval_seconds: int | None = Field(default=None, ge=60)`, plus `ge=0`/`gt=0` on rate, range, and capacity.

### 20. ✅ Long open trips bounded
[backend/poller.py:48-51](backend/poller.py#L48-L51) — `_TRIP_POINT_CAP = 500` breadcrumb cap and `_TRIP_MAX_DURATION_H = 24` force-close. Both enforced in `_update_trip`.

### 21. ✅ Charging session split on API glitch
Added `_charging_glitch_polls` debounce counter in `_update_charging_session`. A session is only closed after **2 consecutive non-CHARGING polls**, so a single stale or missing `chargingState` response no longer splits one real charge into two records.

### 22. ✅ Negative `kwh_added` on stale SoC
Added `if delta_soc > 0:` guard before computing `kwh_added`, `cost`, and `range_added_km` in `_update_charging_session`. A stale/out-of-order SoC from the API can no longer write a negative energy figure.

### 23. ✅ Invalid JSON in event `detail` column
Replaced all `f'{{"key": {value}}}'` f-strings in `_update_charging_session` and `_close_trip` with `json.dumps({...})`. `None` values now serialize as JSON `null` instead of the Python literal `None`, which was unparseable as JSON.

---

## 🟢 Missing features

### Done
- ✅ **Charging curve graph** — `GET /api/charging/sessions/{id}/curve` + [frontend/src/components/ChargingCurve.tsx](frontend/src/components/ChargingCurve.tsx); rendered in the expandable session card.
- ✅ **Delete** — `DELETE /api/trips/{id}` and `DELETE /api/charging/sessions/{id}`, wired into the UI lists with a trash icon.
- ✅ **CSV export** — `GET /api/trips/export.csv` and `GET /api/charging/sessions/export.csv`, with download buttons on each page.
- ✅ **Webhook notifications** — [backend/webhook.py](backend/webhook.py) (daemon-thread fire-and-forget) called from `_update_charging_session` and `_update_trip` on charge/trip start/end. URL configurable in Settings.
- ✅ **Period-over-period deltas** — `prev` block on `/api/trips/stats` and `/api/charging/stats`; `StatusCard` renders ▲/▼ badges with `deltaInvert` for "lower is better" metrics.
- ✅ **CO₂ saved** — computed on the trips page (7 L/100km petrol baseline × 2.31 kg/L).
- ✅ **Vampire drain** — `GET /api/vehicle/vampire-drain` + [frontend/src/components/VampireDrainCard.tsx](frontend/src/components/VampireDrainCard.tsx).
- ✅ **Test-connection button** — `POST /api/settings/test-connection` + UI in Settings.
- ✅ **Force poll button** — `POST /api/vehicle/poll` ([backend/routers/vehicle.py](backend/routers/vehicle.py)) + refresh icon button in dashboard header; spins while in-flight, result arrives via WebSocket.
- ✅ **Light/dark mode** — `ThemeProvider` applies a `light` class to `<html>`; CSS overrides cascade through all Tailwind arbitrary-value classes. Toggle button (Sun/Moon) in nav bar. Preference persisted in `localStorage`.
- ✅ **Custom theme colors** — Appearance section at the bottom of Settings; color pickers for accent, page background, and card background, separately for dark and light modes. Applied instantly via CSS variables. Per-theme Reset buttons.
- ✅ **Change password UI** — inline form per user row in the Users section of Settings (calls `POST /api/auth/users/{id}/password`).

### Not done
- ✅ **Manual entry** — `POST /api/trips` and `POST /api/charging/sessions` endpoints added; "+" button on both pages opens a modal form. kWh/efficiency/cost are auto-computed from SoC delta if not provided explicitly.
- ❌ **Battery SoH from charge curves** — still uses rated-range delta in [routers/vehicle.py](backend/routers/vehicle.py). The charging-curve data is now stored, so this is unblocked but unimplemented.
- ❌ **Multi-vehicle UI** — VIN setting is honored by the poller, but the UI still assumes a single car.

---

## ⚪ Polish / cleanup

### Done
- ✅ Timezone field — `<datalist>` of ~70 IANA zones with autocomplete ([SettingsForm.tsx](frontend/src/app/settings/SettingsForm.tsx)).
- ✅ Version number in nav header — fetched from `/api/version` (reads `frontend/package.json`).
- ✅ Broken `docs/preview.png` reference removed from README.
- ✅ `metadata.viewport` → `export const viewport: Viewport` ([layout.tsx:12-16](frontend/src/app/layout.tsx#L12-L16)).
- ✅ `devIndicators` switched to the object form (no deprecation warning).
- ✅ Nav uses `useVehicleName()` from `SettingsProvider` instead of fetching `/api/settings` itself.
- ✅ Frontend `connected` from `useVehicleLive` is now used — Offline pill on the dashboard.
- ✅ `websockets==14.1` already absent from `backend/requirements.txt`.
- ✅ Nav redesigned — frosted-glass header, consistent icon-button style for all actions, vehicle name / version shown inline.
- ✅ Dashboard SSR auth bug fixed — `page.tsx` no longer calls authenticated API endpoints server-side (token is in `localStorage`, unavailable to SSR). Data is fetched client-side on mount.

### Not done
- ❌ `viewport.maximumScale: 1` is still set in [layout.tsx:15](frontend/src/app/layout.tsx#L15) — pinch-zoom remains blocked. Accessibility nit, easy to drop later.
- ❌ No tests anywhere.
- ❌ No backend lint/type config (ruff/black/mypy).
- ❌ Distance/efficiency calc still duplicated across `poller.py`, `recover_trips.py`, and `import_vwsfriend.py` — not extracted to `utils.py`.
- ❌ Alembic still in `requirements.txt` but unused — should be removed if staying with raw `ALTER TABLE` migrations.
- ℹ️ Dockerfile installs `postgresql-client` — this is intentional; `pg_restore` is required for the file-based VWsFriend import path (UI + API). Not a candidate for removal.

---

## Summary

| Bucket | Done | Partial | Not done |
|---|---|---|---|
| Critical bugs (1–6) | 6 | 0 | 0 |
| Security & privacy (7–10) | 3 | 1 (#7 — encryption done, no `_file` variant, manual rotation still required) | 0 |
| Reliability (11–23) | 11 | 0 | 2 (#11 Alembic, #15 naive-datetime) |
| Features | 12 | 0 | 2 (SoH, multi-vehicle) |
| Polish | 9 | 0 | 5 (a11y nit, tests, lint, dedup, stale Alembic dep) |

**Operator follow-ups still required:**
1. Rotate the VW WeConnect password that was committed in plaintext history.
2. Set a `SECRET_KEY` env var so the rotated password is encrypted on disk.
3. Set an `access_token` in Settings if exposing beyond a trusted LAN.

---

## Roadmap

### 🔴 CarConnectivity migration (blocked on weconnect-python EOL)

`weconnect-python` is deprecated and unmaintained. The replacement is `carconnectivity` + `carconnectivity-connector-volkswagen`. Full research and field-mapping notes are in [CARCONNECTIVITY_MIGRATION.md](CARCONNECTIVITY_MIGRATION.md).

**Scope of change:**

| File | Change needed |
|---|---|
| `backend/requirements.txt` | Remove `weconnect[Images]`; add `carconnectivity` + `carconnectivity-connector-volkswagen` |
| `backend/poller.py` | Replace init, vehicle access, `_extract_snapshot()`, remove `_patch_weconnect_window()` |
| `backend/routers/vehicle.py` | Replace climate/charging control commands |
| `backend/mock_weconnect.py` | Rewrite to implement CarConnectivity interface |

**Known breaking change:** window open percentage is not available in CarConnectivity — only OPEN/CLOSED state. `windows_json` storage and the `WindowStatus` UI component will need to be adapted.

**Status:** Research complete (2026-05-14). API tested against real vehicle. Ready to implement.

---

## VWsFriend Gap Analysis — cross-reference

Full analysis: [VWSFRIEND_GAP_ANALYSIS.md](VWSFRIEND_GAP_ANALYSIS.md)

### §2 / §2.13 — Missing data domains & integrations

| Item | Status | Notes |
|---|---|---|
| §2.1 Charging session lifecycle (connected→locked→started→ended→unlocked→disconnected) | ❌ | `started_at`/`ended_at` only |
| §2.2 Maintenance tracking (inspection, oil service due dates) | ❌ | WeConnect exposes it; we discard it |
| §2.3 Warning lights (dashboard lights with history) | ❌ | WeConnect exposes it; we discard it |
| §2.4 Geofences (named zones) | ❌ | No model or UI |
| §2.5 Structured chargers | ✅ | `Charger` model + proximity matching in `chargers.py`; `charger_id` FK on `ChargingSession` |
| §2.6 Structured geocoded locations (OSM breakdown) | ❌ | Still a single string column |
| §2.7 Tags on trips/charges | ❌ | No model or UI |
| §2.8 Online/offline session tracking | ❌ | No model; connectivity gaps invisible |
| §2.9 Persisted WeConnect errors | ❌ | Errors logged to stderr only, lost on container restart |
| §2.10 Multi-vehicle support | ❌ | Hard-wired to one `vw_vin` setting |
| §2.11 ABRP integration | ❌ | Not started |
| §2.12 MQTT publisher | ❌ | Not started |
| §2.13 Vehicle controls — lock/unlock/flash/charge start-stop/target SoC | ❌ | Only climate start/stop is implemented |

### §3 — Improvements to existing implementations

| Item | Status | Notes |
|---|---|---|
| §3.1 Normalised snapshot schema | ❌ | One wide denormalised row per poll; acceptable while DB is small |
| §3.2 READINESS_STATUS trip detection fallback | ❌ | No GPS → no trip |
| §3.4 kWh-based battery health metric | ❌ | Range-extrapolation only today |
| §3.5 Store OSM IDs in geocoder | ❌ | Nominatim result stored as display string only |
| §3.7 Unified event dispatcher (webhook → MQTT → future) | ❌ | `webhook.py` is hard-wired |
| §3.8 Importer covers subset of VWsFriend tables | ⚠️ | Snapshots, trips, charging sessions only — warning lights, maintenance, chargers, locations, journeys not imported |

### §4 — UX / privacy gaps

| Item | Status | Notes |
|---|---|---|
| §4.1 Privacy toggle (`record_locations: bool`) | ❌ | All GPS always written |
| §4.2 Implicit unit system | ⚠️ | `distance_unit` km/miles setting exists; no single "metric/imperial" toggle for all units |
| §4.3 Versions / about page | ❌ | Version shown in nav; no full diagnostics endpoint with lib versions |
| §4.4 Restart/reload UX | ❌ | Most settings pick up on next poll; no explicit restart button |

### Gap analysis Tier 1 roadmap (highest value, lowest effort)

| # | Item | Status |
|---|---|---|
| 1 | Warning lights tracking (§2.3) | ❌ |
| 2 | Maintenance tracking (§2.2) | ❌ |
| 3 | Vehicle controls backend — lock/unlock/flash/charge/target SoC (§2.13) | ❌ |
| 4 | Privacy toggle (§4.1) | ❌ |
| 5 | Persisted WeConnect errors (§2.9) | ❌ |
| 6 | Charging session lifecycle states (§2.1) | ❌ |
