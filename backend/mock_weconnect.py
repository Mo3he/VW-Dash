from __future__ import annotations
"""
Mock WeConnect provider for development/testing.

Activated by setting  USE_MOCK_WC=1  (or use_mock_weconnect=true in config.json).

How it works
------------
Each call to MockWeConnect.update() advances a state-machine by one tick.
The current scenario controls what happens on each tick.  You can change the
running scenario at any time via the /api/dev/* endpoints.

Built-in scenarios
------------------
parked          Permanently parked, plug disconnected.  SoC stable at 70 %.
charging        Plug connected, SoC climbing 1 %/tick from 40 % to 90 %.
driving         Odometer ticks up ~2 km/tick, parking_time absent.
trip_then_charge Full sequence:
                  ticks 0-1:   parked at home
                  ticks 2-10:  driving (odometer +2 km/tick)
                  ticks 11-12: parked at destination
                  ticks 13-30: charging (SoC +2 %/tick)
                  ticks 31+:   parked fully charged

Custom snapshot overrides
-------------------------
POST /api/dev/state with a partial dict to override individual fields for the
next tick.  The override is consumed after one tick.

Thread safety
-------------
The mock is read inside the poller thread (which holds _poll_lock).  The dev
router runs in an asyncio coroutine.  All access to mutable state goes through
_lock (threading.Lock) so the two never race.
"""
import threading
from datetime import datetime, timezone, timedelta
from typing import Any


# ---------------------------------------------------------------------------
# Internal attribute wrapper — mirrors how weconnect wraps values in objects
# with a .value property that _val() and _car_ts() unwrap.
# ---------------------------------------------------------------------------

class _Attr:
    """Wraps any value so that accessing .value returns it."""
    __slots__ = ("value",)

    def __init__(self, v: Any) -> None:
        self.value = v


class _Status:
    """
    Generic mock status object.  Set attributes directly; each attribute should
    either be a plain value (for _val()) or wrapped in _Attr (for _car_ts()).
    """
    pass


class _MockWindow:
    """Mimics a (patched) weconnect AccessStatus.Window for window-status reading."""

    def __init__(self, open_pct: int) -> None:
        self._open_pct = open_pct
        # Build a minimal openState chain: .enabled / .value.value
        _state_val = "closed" if open_pct == 0 else "open"

        class _OpenStateVal:
            value = _state_val

        class _OpenState:
            enabled = True
            value = _OpenStateVal()

        self.openState = _OpenState()


class _MockControl:
    """Mimics a weconnect ChangeableAttribute used for vehicle controls."""

    def __init__(self, on_set) -> None:
        self._on_set = on_set
        self.value = None

    def __setattr__(self, name, val):
        if name == "value" and not name.startswith("_") and hasattr(self, "_on_set"):
            self._on_set(val)
        object.__setattr__(self, name, val)


class _MockControls:
    """
    Mimics weconnect Controls object.  Setting .climatizationControl.value or
    .chargingControl.value updates the mock state immediately so the next poll
    reflects the command.
    """

    def __init__(self, state: "MockVehicleState") -> None:
        self._state = state

        def _set_climate(op):
            from weconnect.elements.control_operation import ControlOperation
            if op == ControlOperation.START:
                self._state.climatisation_state = "heating"
            else:
                self._state.climatisation_state = "off"

        def _set_charging(op):
            from weconnect.elements.control_operation import ControlOperation
            if op == ControlOperation.START:
                self._state.charging_state = "CHARGING"
                self._state.charge_type = "AC"
                self._state.charge_power_kw = 11.0
            else:
                self._state.charging_state = "readyForCharging"
                self._state.charge_type = ""
                self._state.charge_power_kw = None

        self.climatizationControl = _MockControl(_set_climate)
        self.chargingControl = _MockControl(_set_charging)


class _MockVehicle:
    """Mimics a weconnect vehicle object's .domains dict."""

    def __init__(self, domains: dict[str, dict[str, _Status | None]], state: "MockVehicleState | None" = None) -> None:
        self.domains = domains
        self.controls = _MockControls(state) if state is not None else None


# ---------------------------------------------------------------------------
# State snapshot — the full set of fields _extract_snapshot reads
# ---------------------------------------------------------------------------

class MockVehicleState:
    """All telemetry fields used by _extract_snapshot, with sensible defaults."""

    def __init__(self) -> None:
        # Defaults mirror a real ID.4 parked at home (Lund, Sweden)
        self.soc_pct: float = 65.0          # real value observed 2026-05-13
        self.range_km: float = 259.0
        self.charging_state: str = "NOT_READY_FOR_CHARGING"
        self.charge_power_kw: float | None = None
        self.charge_rate_kmph: float | None = None
        self.charge_type: str = ""
        self.remaining_charge_min: float | None = None
        self.target_soc_pct: float = 80.0   # real target SOC
        self.plug_connected: bool = False
        self.latitude: float | None = 55.718715   # real parking position
        self.longitude: float | None = 13.21968
        self.parking_time: datetime | None = datetime.now(timezone.utc)
        self.climatisation_state: str = "OFF"
        self.cabin_temp_c: float = 20.0
        self.locked: bool = True
        self.odometer_km: float = 54977.0   # real odometer (km)
        # Battery temp from real API (temperatureHvBatteryMax/Min_K = 283.65 → 10.5 °C)
        self.battery_temp_c: float | None = 10.5
        self.battery_temp_min_c: float | None = 10.5
        self.battery_temp_max_c: float | None = 10.5
        # Window open percentages — all closed by default (0 = fully closed)
        # Keys mirror the real API: frontLeft, frontRight, rearLeft, rearRight
        self.windows: dict[str, int] = {
            "frontLeft": 0, "frontRight": 0, "rearLeft": 0, "rearRight": 0
        }
        # outdoor_temp_c is intentionally absent — the real WeConnect API does
        # not expose an outsideTemperatureStatus domain on this vehicle.

    def to_domains(self) -> dict[str, dict[str, _Status | None]]:
        ts = _Attr(datetime.now(timezone.utc))

        battery = _Status()
        battery.carCapturedTimestamp = ts
        battery.currentSOC_pct = self.soc_pct
        battery.cruisingRangeElectric_km = self.range_km

        charging_s = _Status()
        charging_s.carCapturedTimestamp = ts
        charging_s.chargingState = self.charging_state
        charging_s.chargePower_kW = self.charge_power_kw
        charging_s.chargeRate_kmph = self.charge_rate_kmph
        charging_s.chargeType = self.charge_type
        charging_s.remainingChargingTimeToComplete_min = self.remaining_charge_min

        charging_settings = _Status()
        charging_settings.carCapturedTimestamp = ts
        charging_settings.targetSOC_pct = self.target_soc_pct

        plug = _Status()
        plug.carCapturedTimestamp = ts
        plug.plugConnectionState = "CONNECTED" if self.plug_connected else "DISCONNECTED"

        parking = _Status()
        parking.carCapturedTimestamp = ts
        parking.latitude = self.latitude
        parking.longitude = self.longitude
        parking.carCapturedTimestamp = _Attr(self.parking_time) if self.parking_time else _Attr(None)

        access = _Status()
        access.carCapturedTimestamp = ts
        access.overallStatus = "safe" if self.locked else "unsafe"
        access.windows = {name: _MockWindow(pct) for name, pct in self.windows.items()}

        odometer = _Status()
        odometer.carCapturedTimestamp = ts
        odometer.odometer = self.odometer_km

        clim = _Status()
        clim.carCapturedTimestamp = ts
        clim.climatisationState = self.climatisation_state

        clim_settings = _Status()
        clim_settings.carCapturedTimestamp = ts
        clim_settings.targetTemperature_C = self.cabin_temp_c

        # Battery temp — stored in Kelvin by the real API
        batt_temp = _Status()
        batt_temp.carCapturedTimestamp = ts
        batt_temp.temperatureHvBatteryMin_K = (self.battery_temp_min_c + 273.15) if self.battery_temp_min_c is not None else None
        batt_temp.temperatureHvBatteryMax_K = (self.battery_temp_max_c + 273.15) if self.battery_temp_max_c is not None else None

        # Note: outsideTemperatureStatus is deliberately omitted — the real
        # WeConnect API does not return this domain for this vehicle.

        return {
            "charging": {
                "batteryStatus": battery,
                "chargingStatus": charging_s,
                "chargingSettings": charging_settings,
                "plugStatus": plug,
            },
            "parking": {
                "parkingPosition": parking,
            },
            "access": {
                "accessStatus": access,
            },
            "measurements": {
                "odometerStatus": odometer,
                "temperatureBatteryStatus": batt_temp,
            },
            "climatisation": {
                "climatisationStatus": clim,
                "climatisationSettings": clim_settings,
            },
        }


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

def _scenario_parked(state: MockVehicleState, tick: int) -> None:
    """Permanently parked at home, plug out."""
    # Nothing changes — car just sits there.
    pass


def _scenario_charging(state: MockVehicleState, tick: int) -> None:
    """Plug in, SoC climbs 1 %/tick until target, then done."""
    if tick == 0:
        state.soc_pct = 40.0
        state.range_km = round(40.0 / 100 * 410, 1)
        state.plug_connected = True
        state.parking_time = datetime.now(timezone.utc)
        state.latitude = 55.718715   # real parking position
        state.longitude = 13.21968

    if state.soc_pct < state.target_soc_pct:
        state.soc_pct = min(round(state.soc_pct + 1.0, 1), state.target_soc_pct)
        state.range_km = round(state.soc_pct / 100 * 410, 1)
        state.charging_state = "CHARGING"
        state.charge_type = "AC"
        state.charge_power_kw = 11.0
        state.charge_rate_kmph = 65.0   # real API returns None when not charging
        state.remaining_charge_min = round((state.target_soc_pct - state.soc_pct) * 3.0)
    else:
        state.charging_state = "READY_FOR_CHARGING"
        state.charge_type = ""
        state.charge_power_kw = 0.0   # real API returns 0.0 when done
        state.charge_rate_kmph = None  # real API returns None
        state.remaining_charge_min = 0


def _scenario_driving(state: MockVehicleState, tick: int) -> None:
    """Car is driving: parking_time absent, odometer ticks up."""
    if tick == 0:
        state.parking_time = None
        state.plug_connected = False
        state.charging_state = "NOT_READY_FOR_CHARGING"  # real value when driving unplugged

    state.odometer_km = round(state.odometer_km + 2.0, 1)
    state.soc_pct = max(round(state.soc_pct - 0.5, 1), 5.0)
    state.range_km = round(state.soc_pct / 100 * 410, 1)
    # No GPS while driving — VW API typically returns None for parking position
    state.latitude = None
    state.longitude = None


def _scenario_trip_then_charge(state: MockVehicleState, tick: int) -> None:
    """
    Full cycle:
      0-1   parked at home (55.700013, 13.194128)
      2-10  driving north toward destination
      11-12 parked at destination (55.718715, 13.21968)
      13-30 AC charging at destination
      31+   fully charged, parked
    """
    if tick <= 1:
        # Parked at real home location
        state.parking_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        state.plug_connected = False
        state.charging_state = "NOT_READY_FOR_CHARGING"
        state.latitude = 55.700013
        state.longitude = 13.194128

    elif tick <= 10:
        # Driving
        if tick == 2:
            state.parking_time = None
            state.latitude = None
            state.longitude = None
        state.odometer_km = round(state.odometer_km + 2.0, 1)
        state.soc_pct = max(round(state.soc_pct - 0.5, 1), 5.0)
        state.range_km = round(state.soc_pct / 100 * 410, 1)

    elif tick <= 12:
        # Parked at real destination
        if tick == 11:
            state.parking_time = datetime.now(timezone.utc)
            state.latitude = 55.718715   # real parking position
            state.longitude = 13.21968
            state.plug_connected = True

    elif tick <= 30:
        # Charging
        if tick == 13:
            state.charging_state = "CHARGING"
            state.charge_type = "AC"
            state.charge_power_kw = 11.0
            state.charge_rate_kmph = 65.0
        state.soc_pct = min(round(state.soc_pct + 2.0, 1), state.target_soc_pct)
        state.range_km = round(state.soc_pct / 100 * 410, 1)
        state.remaining_charge_min = round((state.target_soc_pct - state.soc_pct) * 3.0)
        if state.soc_pct >= state.target_soc_pct:
            state.charging_state = "READY_FOR_CHARGING"
            state.charge_type = ""
            state.charge_power_kw = 0.0   # real API returns 0.0, not None
            state.charge_rate_kmph = None
            state.remaining_charge_min = 0

    else:
        # Done charging — stay parked
        state.charging_state = "READY_FOR_CHARGING"
        state.charge_power_kw = 0.0


def _scenario_dc_charging(state: MockVehicleState, tick: int) -> None:
    """DC fast-charge: SoC climbs ~3%/tick with tapered power above 80%."""
    if tick == 0:
        state.soc_pct = 20.0
        state.range_km = round(20.0 / 100 * 410, 1)
        state.plug_connected = True
        state.parking_time = datetime.now(timezone.utc)
        state.latitude = 55.718715
        state.longitude = 13.21968

    if state.soc_pct < state.target_soc_pct:
        state.soc_pct = min(round(state.soc_pct + 3.0, 1), state.target_soc_pct)
        state.range_km = round(state.soc_pct / 100 * 410, 1)
        state.charging_state = "CHARGING"
        state.charge_type = "DC"
        # Taper power above 80% SoC (realistic DC curve)
        if state.soc_pct <= 80:
            state.charge_power_kw = 100.0
        else:
            state.charge_power_kw = max(20.0, round(100.0 * (1 - (state.soc_pct - 80) / 20), 1))
        state.charge_rate_kmph = round(state.charge_power_kw * 6.0, 1)
        state.remaining_charge_min = round((state.target_soc_pct - state.soc_pct) * 1.0)
    else:
        state.charging_state = "READY_FOR_CHARGING"
        state.charge_type = ""
        state.charge_power_kw = 0.0
        state.charge_rate_kmph = None
        state.remaining_charge_min = 0


SCENARIOS: dict[str, Any] = {
    "parked": _scenario_parked,
    "charging": _scenario_charging,
    "dc_charging": _scenario_dc_charging,
    "driving": _scenario_driving,
    "trip_then_charge": _scenario_trip_then_charge,
}

_DEFAULT_SCENARIO = "trip_then_charge"


# ---------------------------------------------------------------------------
# MockWeConnect — drop-in replacement for the weconnect.WeConnect object
# ---------------------------------------------------------------------------

class MockWeConnect:
    """
    Mimics the subset of the weconnect.WeConnect interface used by poller.py.

    Thread-safe:  all state mutations go through self._lock.
    """

    MOCK_VIN = "MOCK0VIN00000001"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = MockVehicleState()
        self._scenario_name: str = _DEFAULT_SCENARIO
        self._scenario_fn = SCENARIOS[_DEFAULT_SCENARIO]
        self._tick: int = 0
        self._override: dict[str, Any] = {}
        self.vehicles: dict[str, _MockVehicle] = {
            self.MOCK_VIN: _MockVehicle(self._state.to_domains(), self._state)
        }

    # ------------------------------------------------------------------
    # weconnect interface
    # ------------------------------------------------------------------

    def login(self) -> None:
        pass

    def update(self) -> None:
        """Advance the scenario by one tick and rebuild vehicle domains."""
        with self._lock:
            self._scenario_fn(self._state, self._tick)
            self._tick += 1

            # Apply one-shot overrides
            for key, value in self._override.items():
                if hasattr(self._state, key):
                    setattr(self._state, key, value)
            self._override.clear()

            self.vehicles[self.MOCK_VIN] = _MockVehicle(self._state.to_domains(), self._state)

    # ------------------------------------------------------------------
    # Dev-control interface (called from dev_router.py)
    # ------------------------------------------------------------------

    def set_scenario(self, name: str) -> None:
        if name not in SCENARIOS:
            raise ValueError(f"Unknown scenario {name!r}. Available: {list(SCENARIOS)}")
        with self._lock:
            self._scenario_name = name
            self._scenario_fn = SCENARIOS[name]
            self._tick = 0
            self._state = MockVehicleState()   # always start from a clean baseline
            self._override.clear()

    def set_state_override(self, fields: dict[str, Any]) -> None:
        """Override specific state fields on the next tick."""
        with self._lock:
            self._override.update(fields)

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            s = self._state
            return {
                "scenario": self._scenario_name,
                "tick": self._tick,
                "soc_pct": s.soc_pct,
                "range_km": s.range_km,
                "odometer_km": s.odometer_km,
                "charging_state": s.charging_state,
                "plug_connected": s.plug_connected,
                "charge_power_kw": s.charge_power_kw,
                "parking_time": s.parking_time.isoformat() if s.parking_time else None,
                "latitude": s.latitude,
                "longitude": s.longitude,
                "locked": s.locked,
                "battery_temp_c": s.battery_temp_c,
                "windows": s.windows,
            }

    @classmethod
    def available_scenarios(cls) -> list[str]:
        return list(SCENARIOS)
