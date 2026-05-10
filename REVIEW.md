# VW-Dash — Project Review

> Original snapshot: 2026-05-10. Re-audited 2026-05-10 after the fix pass.
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

### 5. ❌ SoC quantization on short trips
Not addressed. Still uses snapshot-to-snapshot whole-percent SoC, so a 4-mile trip can show 0 kWh. Worth deferring until users complain — the plumbing for `cruisingRangeElectric_km` deltas is straightforward but not implemented.

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
Access token + frontend login gate:
- [backend/main.py:85-96](backend/main.py#L85-L96) — auth middleware (exempts `/api/health` and `/ws`)
- [frontend/src/lib/auth.ts](frontend/src/lib/auth.ts) + [frontend/src/components/AuthGate.tsx](frontend/src/components/AuthGate.tsx) — token storage in `localStorage`, login form on 401

### 9. ✅ Nominatim user-agent
[backend/geocoder.py:17](backend/geocoder.py#L17) — `VW-Dash/1.0 (self-hosted EV dashboard; https://github.com/Mo3he/VW-Dash)`.

### 10. ✅ Configurable CORS
[backend/config.py:66](backend/config.py#L66) — `cors_origins` setting; main.py splits on commas. Defaults still cover localhost dev.

---

## 🟡 Reliability / correctness

### 11. ❌ Migrations are ad-hoc raw SQL
Still in [backend/main.py:29-53](backend/main.py#L29-L53). Alembic is in `requirements.txt` but unused; `backend/migrations/` is empty. Error handling **was** improved (#13), but the broader Alembic conversion did not happen.

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

### Not done
- ⚠️ **Manual entry** — delete is in; "add a trip I forgot to log" / "add a charging session by hand" UI was not built. Inline edit on existing rows already worked before this pass.
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
- ✅ Frontend `connected` from `useVehicleLive` is now used — Offline pill on the dashboard ([DashboardClient.tsx:108-111](frontend/src/app/DashboardClient.tsx#L108-L111)).
- ✅ `websockets==14.1` already absent from `backend/requirements.txt`.

### Not done
- ❌ `viewport.maximumScale: 1` is still set in [layout.tsx:15](frontend/src/app/layout.tsx#L15) — pinch-zoom remains blocked. Accessibility nit, easy to drop later.
- ❌ No tests anywhere.
- ❌ No backend lint/type config (ruff/black/mypy).
- ❌ Empty `backend/migrations/` directory still present.
- ❌ Distance/efficiency calc still duplicated across `poller.py`, `recover_trips.py`, and `import_vwsfriend.py` — not extracted to `utils.py`.
- ❌ Dockerfile still installs `postgresql-client` (~70 MB) into the runtime image.
- ❌ [CLAUDE.md:60](CLAUDE.md#L60) still says "not via Alembic CLI despite Alembic being installed" — accurate today, but the Alembic dep itself ought to be removed if we're sticking with raw ALTERs.

---

## Summary

| Bucket | Done | Partial | Not done |
|---|---|---|---|
| Critical bugs (1–6) | 5 | 0 | 1 (#5 SoC quantization) |
| Security & privacy (7–10) | 3 | 1 (#7 — encryption done, no `_file` variant, manual rotation still required) | 0 |
| Reliability (11–20) | 8 | 0 | 2 (#11 Alembic, #15 naive-datetime) |
| Features | 8 | 1 (manual entry) | 2 (SoH, multi-vehicle) |
| Polish | 7 | 0 | 7 (a11y nit, tests, lint, empty migrations dir, dedup, Docker slimming, stale Alembic note) |

**Operator follow-ups still required:**
1. Rotate the VW WeConnect password that was committed in plaintext history.
2. Set a `SECRET_KEY` env var so the rotated password is encrypted on disk.
3. Set an `access_token` in Settings if exposing beyond a trusted LAN.
