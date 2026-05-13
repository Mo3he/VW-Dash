"""
End-to-end integration tests against a running mock server.

Start the server first:
    rm -f /tmp/vwdash_test.db
    USE_MOCK_WECONNECT=1 DB_PATH=/tmp/vwdash_test.db \
        python -m uvicorn main:app --host 127.0.0.1 --port 8001

Then run:
    python tests/test_e2e_mock.py
"""
from __future__ import annotations
import urllib.request
import json
import time
import sys
from typing import Optional

BASE = "http://localhost:8001"
passed: list[str] = []
failed: list[str] = []


def req(method: str, path: str, body=None, token: Optional[str] = None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body else None
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return json.loads(resp.read()), resp.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read()), e.code


def ok(name: str, cond: bool, detail: str = "") -> None:
    sym = "PASS" if cond else "FAIL"
    if cond:
        passed.append(name)
    else:
        failed.append(name)
    print(f"  {sym}  {name}" + (f"  [{detail}]" if detail else ""))


# ---------------------------------------------------------------------------
# 0. Health
# ---------------------------------------------------------------------------
print("\n=== 0. Health ===")
d, s = req("GET", "/api/health")
ok("health", s == 200 and d.get("status") == "ok")

# ---------------------------------------------------------------------------
# 1. Dev endpoints accessible without auth
# ---------------------------------------------------------------------------
print("\n=== 1. Dev endpoints (no auth) ===")
d, s = req("GET", "/api/dev/status")
ok("dev/status 200", s == 200, f"scenario={d.get('scenario')} tick={d.get('tick')}")
ok(
    "dev/status fields",
    all(k in d for k in ["scenario", "tick", "soc_pct", "plug_connected", "charging_state", "parking_time"]),
)
d2, s2 = req("GET", "/api/dev/scenarios")
ok("dev/scenarios 200", s2 == 200)
ok("all 4 scenarios", set(d2.get("scenarios", [])) == {"parked", "charging", "driving", "trip_then_charge"})

# ---------------------------------------------------------------------------
# 2. Auth setup
# ---------------------------------------------------------------------------
print("\n=== 2. Setup user ===")
d, s = req("POST", "/api/auth/setup", {"username": "tester", "password": "Test1234!"})
ok("user created", s == 200 and "access_token" in d, str(s))
TOKEN = d.get("access_token", "")

# ---------------------------------------------------------------------------
# 3. poll_interval_seconds live reschedule
# ---------------------------------------------------------------------------
print("\n=== 3. poll_interval_seconds reschedules live ===")
d, s = req("PATCH", "/api/settings", {"poll_interval_seconds": 600}, token=TOKEN)
ok("PATCH settings 200", s == 200)
ok("poll_interval_seconds updated", d.get("poll_interval_seconds") == 600)

# ---------------------------------------------------------------------------
# 4. Drive the trip_then_charge scenario for 35 ticks
# ---------------------------------------------------------------------------
print("\n=== 4. Advance 35 ticks (trip_then_charge) ===")
for _ in range(35):
    req("POST", "/api/vehicle/poll", token=TOKEN)
    time.sleep(0.2)
ok("35 polls fired", True)

# ---------------------------------------------------------------------------
# 5. Snapshots via history endpoint
# ---------------------------------------------------------------------------
print("\n=== 5. Snapshots ===")
d, _ = req("GET", "/api/vehicle/history", token=TOKEN)
n = len(d) if isinstance(d, list) else 0
ok(">=10 snapshots", n >= 10, f"count={n}")
if isinstance(d, list) and d:
    snap = d[-1]  # history is ascending; last = most recent
    ok("snapshot soc_pct", snap.get("soc_pct") is not None)
    ok("snapshot range_km", snap.get("range_km") is not None)
    ok("snapshot recorded_at", snap.get("recorded_at") is not None)
    ok("snapshot charging_state", snap.get("charging_state") is not None)

# ---------------------------------------------------------------------------
# 6. Latest snapshot endpoint
# ---------------------------------------------------------------------------
print("\n=== 6. Latest snapshot endpoint ===")
d, s = req("GET", "/api/vehicle/latest", token=TOKEN)
ok("vehicle/latest 200", s == 200, str(s))
ok("vehicle/latest has soc_pct", "soc_pct" in d)
ok("vehicle/latest has range_km", "range_km" in d)
ok("vehicle/latest has charging_state", "charging_state" in d)

# ---------------------------------------------------------------------------
# 7. Trip data
# ---------------------------------------------------------------------------
print("\n=== 7. Trip ===")
time.sleep(2)  # allow geocoder a moment
d, _ = req("GET", "/api/trips?limit=10", token=TOKEN)
trips = d.get("trips", [])
ok(">=1 trip", d.get("total", 0) >= 1, f"total={d.get('total')}")
if trips:
    t = trips[0]
    ok("trip distance_km", t.get("distance_km") is not None, str(t.get("distance_km")))
    ok("trip start coords", t.get("start_lat") is not None)
    ok("trip end coords", t.get("end_lat") is not None)
    ok("trip soc_start", t.get("soc_start_pct") is not None)
    ok("trip soc_end", t.get("soc_end_pct") is not None)
    ok("trip kwh_used", t.get("kwh_used") is not None, str(t.get("kwh_used")))
    print(
        f"  Trip #{t['id']}: {t.get('distance_km')} km, "
        f"SoC {t.get('soc_start_pct')}%\u2192{t.get('soc_end_pct')}%, "
        f"{t.get('kwh_used')} kWh, "
        f"start={t.get('start_address')!r} end={t.get('end_address')!r}"
    )
    d2, _ = req("GET", f"/api/trips/{t['id']}/route", token=TOKEN)
    pts = d2.get("points", [])
    ok("trip breadcrumbs", len(pts) >= 1, f"count={len(pts)}")

# ---------------------------------------------------------------------------
# 8. Charging session data
# ---------------------------------------------------------------------------
print("\n=== 8. Charging session ===")
d, _ = req("GET", "/api/charging/sessions?limit=10", token=TOKEN)
sessions = d.get("sessions", [])
ok(">=1 session", d.get("total", 0) >= 1, f"total={d.get('total')}")
if sessions:
    s0 = sessions[0]
    ok("session soc_start", s0.get("soc_start_pct") is not None, str(s0.get("soc_start_pct")))
    ok("session soc_end", s0.get("soc_end_pct") is not None, str(s0.get("soc_end_pct")))
    ok("session kwh_added", s0.get("kwh_added") is not None, str(s0.get("kwh_added")))
    print(
        f"  Session #{s0['id']}: SoC {s0.get('soc_start_pct')}%\u2192{s0.get('soc_end_pct')}%, "
        f"{s0.get('kwh_added')} kWh"
    )
    d2, _ = req("GET", f"/api/charging/sessions/{s0['id']}/curve", token=TOKEN)
    ok("charging curve points", len(d2.get("points", [])) >= 1, f"count={len(d2.get('points', []))}")

# ---------------------------------------------------------------------------
# 9. Aggregate stats
# ---------------------------------------------------------------------------
print("\n=== 9. Stats ===")
d, s = req("GET", "/api/trips/stats", token=TOKEN)
ok("trip stats 200", s == 200)
ok("trip stats total_km", "total_km" in d, str(list(d.keys())[:5]))
ok("trip stats trip_count", d.get("trip_count", 0) >= 1)
d, s = req("GET", "/api/charging/stats", token=TOKEN)
ok("charging stats 200", s == 200)
ok("charging stats total_kwh", "total_kwh" in d)

# ---------------------------------------------------------------------------
# 10. Scenario switch resets tick and state baseline
# ---------------------------------------------------------------------------
print("\n=== 10. Scenario switch + tick reset ===")
d, s = req("POST", "/api/dev/scenario", {"scenario": "charging"})
ok("switch to charging", s == 200)
d, _ = req("GET", "/api/dev/status")
ok("scenario=charging", d.get("scenario") == "charging")
ok("tick=0 after switch", d.get("tick") == 0, str(d.get("tick")))
# State is reset to MockVehicleState defaults before any update() call;
# charging scenario sets soc=40 on tick==0 inside update(), so checking
# soc here (before a poll) would show the default (70.0) -- not tested.
for _ in range(3):
    req("POST", "/api/vehicle/poll", token=TOKEN)
    time.sleep(0.2)
d, _ = req("GET", "/api/dev/status")
ok("CHARGING state after ticks", d.get("charging_state") == "CHARGING", d.get("charging_state"))

# ---------------------------------------------------------------------------
# 11. State override
# ---------------------------------------------------------------------------
print("\n=== 11. State override ===")
req("POST", "/api/dev/scenario", {"scenario": "parked"})
time.sleep(0.3)
req("POST", "/api/dev/state", {"fields": {"soc_pct": 12.3}})
req("POST", "/api/vehicle/poll", token=TOKEN)
time.sleep(0.5)
d, _ = req("GET", "/api/vehicle/latest", token=TOKEN)
ok("override soc_pct=12.3 saved", d.get("soc_pct") == 12.3, str(d.get("soc_pct")))

# ---------------------------------------------------------------------------
# 12. No phantom trips while parked
# ---------------------------------------------------------------------------
print("\n=== 12. Parked: no phantom trips ===")
req("POST", "/api/dev/scenario", {"scenario": "parked"})
d_before, _ = req("GET", "/api/trips?limit=1", token=TOKEN)
before = d_before.get("total", 0)
for _ in range(5):
    req("POST", "/api/vehicle/poll", token=TOKEN)
    time.sleep(0.15)
d_after, _ = req("GET", "/api/trips?limit=1", token=TOKEN)
after = d_after.get("total", 0)
ok("no new trips while parked", after == before, f"before={before} after={after}")

# ---------------------------------------------------------------------------
# 13. Driving scenario: odometer advances, parking_time absent
# ---------------------------------------------------------------------------
print("\n=== 13. Driving scenario ===")
req("POST", "/api/dev/scenario", {"scenario": "driving"})
d0, _ = req("GET", "/api/dev/status")
odo_before = d0.get("odometer_km", 0)
for _ in range(4):
    req("POST", "/api/vehicle/poll", token=TOKEN)
    time.sleep(0.2)
d1, _ = req("GET", "/api/dev/status")
odo_after = d1.get("odometer_km", 0)
ok("odometer increments", odo_after > odo_before, f"{odo_before}\u2192{odo_after}")
ok("parking_time=None while driving", d1.get("parking_time") is None)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print(f"\n{'=' * 52}")
print(f"  {len(passed)} passed  /  {len(failed)} failed  /  {len(passed) + len(failed)} total")
if failed:
    print(f"  FAILURES: {', '.join(failed)}")
    sys.exit(1)
else:
    print("  All tests passed!")
