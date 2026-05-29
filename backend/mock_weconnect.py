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
# Attribute wrappers matching the carconnectivity interface used by poller.py
# ---------------------------------------------------------------------------

class _Attr:
    """Read-only attribute with .value and .last_updated."""
    __slots__ = ("value", "last_updated")

    def __init__(self, value: Any = None) -> None:
        self.value = value
        self.last_updated = datetime.now(timezone.utc)


class _Cmd:
    """Command attribute: assigning .value triggers the callback."""

    def __init__(self, callback) -> None:
        object.__setattr__(self, '_cb', callback)
        object.__setattr__(self, 'value', None)

    def __setattr__(self, name: str, val: Any) -> None:
        object.__setattr__(self, name, val)
        if name == 'value' and val is not None:
            try:
                object.__getattribute__(self, '_cb')(val)
            except Exception:
                pass


class _Cmds:
    """Commands container with a .commands dict, matching carconnectivity.Commands."""

    def __init__(self, **cmds) -> None:
        self.commands: dict = cmds


# ---------------------------------------------------------------------------
# Mock vehicle sub-objects matching carconnectivity attribute structure
# ---------------------------------------------------------------------------

class _MockBattery:
    def __init__(self, state: "MockVehicleState") -> None:
        k = 273.15
        self.temperature = _Attr((state.battery_temp_c + k) if state.battery_temp_c is not None else None)
        self.temperature_min = _Attr((state.battery_temp_min_c + k) if state.battery_temp_min_c is not None else None)
        self.temperature_max = _Attr((state.battery_temp_max_c + k) if state.battery_temp_max_c is not None else None)


class _MockElectricDrive:
    def __init__(self, state: "MockVehicleState") -> None:
        self.level = _Attr(state.soc_pct)
        self.range = _Attr(state.range_km)
        self.battery = _MockBattery(state)


class _MockDrives:
    def __init__(self, state: "MockVehicleState") -> None:
        self.drives: dict = {"primary": _MockElectricDrive(state)}


class _MockPosition:
    def __init__(self, state: "MockVehicleState") -> None:
        self.latitude = _Attr(state.latitude)
        self.longitude = _Attr(state.longitude)


class _MockConnector:
    def __init__(self, state: "MockVehicleState") -> None:
        from carconnectivity.charging_connector import ChargingConnector
        cs = (ChargingConnector.ChargingConnectorConnectionState.CONNECTED
              if state.plug_connected
              else ChargingConnector.ChargingConnectorConnectionState.DISCONNECTED)
        self.connection_state = _Attr(cs)


class _MockChargingSettings:
    def __init__(self, state: "MockVehicleState") -> None:
        self.target_level = _Attr(state.target_soc_pct)


class _MockCharging:
    def __init__(self, state: "MockVehicleState", state_ref: "MockVehicleState") -> None:
        from carconnectivity.charging import Charging
        _cs_map = {
            "CHARGING": Charging.ChargingState.CHARGING,
            "charging": Charging.ChargingState.CHARGING,
            "READY_FOR_CHARGING": Charging.ChargingState.READY_FOR_CHARGING,
            "readyForCharging": Charging.ChargingState.READY_FOR_CHARGING,
        }
        cs = _cs_map.get(state.charging_state, Charging.ChargingState.OFF)
        self.state = _Attr(cs)
        self.power = _Attr(state.charge_power_kw)
        self.rate = _Attr(state.charge_rate_kmph)
        _ct_map = {
            "AC": Charging.ChargingType.AC, "ac": Charging.ChargingType.AC,
            "DC": Charging.ChargingType.DC, "dc": Charging.ChargingType.DC,
        }
        ct = _ct_map.get(state.charge_type, Charging.ChargingType.OFF)
        self.type = _Attr(ct)
        est = None
        if state.remaining_charge_min is not None and state.remaining_charge_min > 0:
            est = datetime.now(timezone.utc) + timedelta(minutes=state.remaining_charge_min)
        self.estimated_date_reached = _Attr(est)
        self.settings = _MockChargingSettings(state)
        self.connector = _MockConnector(state)

        def _on_charge_cmd(cmd):
            from carconnectivity.command_impl import ChargingStartStopCommand
            if cmd == ChargingStartStopCommand.Command.START:
                state_ref.charging_state = "CHARGING"
                state_ref.charge_type = "AC"
                state_ref.charge_power_kw = 11.0
            else:
                state_ref.charging_state = "READY_FOR_CHARGING"
                state_ref.charge_type = ""
                state_ref.charge_power_kw = None

        self.commands = _Cmds(**{"start-stop": _Cmd(_on_charge_cmd)})


class _MockClimatizationSettings:
    def __init__(self, state: "MockVehicleState") -> None:
        self.target_temperature = _Attr(state.cabin_temp_c)


class _MockClimatization:
    def __init__(self, state: "MockVehicleState", state_ref: "MockVehicleState") -> None:
        from carconnectivity.climatization import Climatization
        _cm_map = {
            "heating": Climatization.ClimatizationState.HEATING,
            "HEATING": Climatization.ClimatizationState.HEATING,
            "cooling": Climatization.ClimatizationState.COOLING,
            "ventilation": Climatization.ClimatizationState.VENTILATION,
            "VENTILATION": Climatization.ClimatizationState.VENTILATION,
        }
        cs = _cm_map.get(state.climatisation_state, Climatization.ClimatizationState.OFF)
        self.state = _Attr(cs)
        self.settings = _MockClimatizationSettings(state)

        def _on_clim_cmd(cmd):
            from carconnectivity.command_impl import ClimatizationStartStopCommand
            if cmd == ClimatizationStartStopCommand.Command.START:
                state_ref.climatisation_state = "heating"
            else:
                state_ref.climatisation_state = "off"

        self.commands = _Cmds(**{"start-stop": _Cmd(_on_clim_cmd)})


class _MockDoors:
    def __init__(self, state: "MockVehicleState") -> None:
        from carconnectivity.doors import Doors
        ls = Doors.LockState.LOCKED if state.locked else Doors.LockState.UNLOCKED
        self.lock_state = _Attr(ls)


class _MockVin:
    def __init__(self, vin: str) -> None:
        self.value = vin


class _MockVehicle:
    """Mimics a carconnectivity vehicle object with all attributes used by _extract_snapshot."""

    def __init__(self, state: "MockVehicleState", vin: str) -> None:
        self.vin = _MockVin(vin)
        self.drives = _MockDrives(state)
        self.position = _MockPosition(state)
        self.charging = _MockCharging(state, state)
        self.climatization = _MockClimatization(state, state)
        self.doors = _MockDoors(state)
        self.odometer = _Attr(state.odometer_km)
        self.outside_temperature = _Attr(None)  # not provided in mock
        # windows not modelled (no open_pct in carconnectivity either)
        self.windows = None


class _MockGarage:
    """Mimics a carconnectivity garage with list_vehicles / get_vehicle."""

    def __init__(self, vehicle: _MockVehicle, vin: str) -> None:
        self._vehicle = vehicle
        self._vin = vin

    def list_vehicles(self) -> list:
        return [self._vehicle]

    def get_vehicle(self, vin: str):
        return self._vehicle if vin == self._vin else None


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

    def to_vehicle(self) -> _MockVehicle:
        """Build a mock vehicle reflecting the current state."""
        return _MockVehicle(self, MockWeConnect.MOCK_VIN)


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
# MockWeConnect — drop-in replacement for a carconnectivity.CarConnectivity object
# ---------------------------------------------------------------------------

class MockWeConnect:
    """
    Mimics the subset of the carconnectivity.CarConnectivity interface used by poller.py.

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
        self._vehicle: _MockVehicle = self._state.to_vehicle()
        self._garage: _MockGarage = _MockGarage(self._vehicle, self.MOCK_VIN)

    # ------------------------------------------------------------------
    # carconnectivity interface
    # ------------------------------------------------------------------

    def startup(self) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def fetch_all(self) -> None:
        """Advance the scenario by one tick and rebuild the mock vehicle."""
        with self._lock:
            self._scenario_fn(self._state, self._tick)
            self._tick += 1

            # Apply one-shot overrides
            for key, value in self._override.items():
                if hasattr(self._state, key):
                    setattr(self._state, key, value)
            self._override.clear()

            self._vehicle = self._state.to_vehicle()
            self._garage = _MockGarage(self._vehicle, self.MOCK_VIN)

    def get_garage(self) -> _MockGarage:
        return self._garage

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
            self._vehicle = self._state.to_vehicle()
            self._garage = _MockGarage(self._vehicle, self.MOCK_VIN)

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
