# CarConnectivity Migration Notes

> Researched 2026-05-14. `weconnect-python` is EOL; replacement is `carconnectivity` + `carconnectivity-connector-volkswagen`. This document captures everything learned so the migration can be done later.

---

## Packages

| Old | New |
|---|---|
| `weconnect[Images]==0.60.11` | `carconnectivity` + `carconnectivity-connector-volkswagen` |

Install:
```bash
pip install carconnectivity carconnectivity-connector-volkswagen
```

Known non-fatal conflict: `weconnect` (if still present) requires `oauthlib~=3.2.2`; carconnectivity pulls in `3.3.1`. The warning can be ignored once weconnect is removed.

---

## Initialisation

### Old (weconnect-python)
```python
from weconnect import weconnect as wc
_weconnect = wc.WeConnect(username, password, tokenfile=tokenfile, ...)
_weconnect.login()
_weconnect.update()
```

### New (carconnectivity)
```python
from carconnectivity import carconnectivity

config = {
    "carConnectivity": {
        "connectors": [{
            "type": "volkswagen",
            "config": {"username": username, "password": password}
        }]
    }
}
cc = carconnectivity.CarConnectivity(config=config, tokenstore_file=tokenfile)
cc.startup()
cc.fetch_all()
```

For periodic polling, call `cc.fetch_all()` each interval (no need to reconnect).  
For shutdown/reset: `cc.shutdown()`.

---

## Vehicle access

### Old
```python
vehicle = _weconnect.vehicles[vin]
```

### New
```python
garage = cc.get_garage()
vehicle = garage.get_vehicle(vin)          # by VIN
# or
vehicle = garage.list_vehicles()[0]        # first vehicle
```

Vehicle type: `VolkswagenElectricVehicle` (subclass of `ElectricVehicle` from carconnectivity).

---

## Field mapping

All fields validated against a real ID.4 Pro Performance (VIN `WVGZZZE2ZMP016456`) on 2026-05-14.

### State / basic

| Old path | New path | Notes |
|---|---|---|
| `_domain(v, "access", "accessStatus").overallStatus.value` | `vehicle.state.value` | e.g. `State.PARKED` |
| `_domain(v, "measurements", "odometerStatus").odometer.value` | `vehicle.odometer.value` | km float |
| `vehicle.domains["access"]["accessStatus"].carCapturedTimestamp.value` | `vehicle.position.latitude.last_updated` | Use `.last_updated` on any attribute as the data-freshness timestamp; it's a `datetime` with tzinfo |

### Position

| Old path | New path |
|---|---|
| `_domain(v, "parking", "parkingPosition").latitude.value` | `vehicle.position.latitude.value` |
| `_domain(v, "parking", "parkingPosition").longitude.value` | `vehicle.position.longitude.value` |
| `parkingPosition.carCapturedTimestamp.value` | `vehicle.position.latitude.last_updated` |
| `parkingPosition.positionType.value` | `vehicle.position.position_type.value` (e.g. `PositionType.PARKING`) |

### SoC / electric drive

```python
from carconnectivity.vehicle import ElectricVehicle
assert isinstance(vehicle, ElectricVehicle)
drive = vehicle.get_electric_drive()   # may return None if not electric
```

| Old path | New path | Notes |
|---|---|---|
| `batteryStatus.currentSOC_pct.value` | `drive.level.value` | float, e.g. `76.0` |
| `batteryStatus.cruisingRangeElectric_km.value` | `drive.range.value` | float, km |
| `batteryStatus.carCapturedTimestamp` | `drive.level.last_updated` | |
| `climatisation.climatisationStatus.temperatureOutside_K.value` | `vehicle.outside_temperature.value` | Already in **°C**, not Kelvin! Check `.enabled` first; was `None` when parked |
| battery temp min | `drive.battery.temperature_min.value` | **Kelvin** - subtract 273.15 for °C |
| battery temp max | `drive.battery.temperature_max.value` | **Kelvin** |

### Charging

| Old path | New path | Notes |
|---|---|---|
| `chargingStatus.chargingState.value` | `vehicle.charging.state.value` | e.g. `ChargingState.OFF`, `.CHARGING`, `.READY_FOR_CHARGING` |
| `chargingStatus.chargeType.value` | `vehicle.charging.type.value` | `ChargingType.AC`, `.DC`, `.INVALID`, `.OFF` |
| `chargingStatus.chargePower_kW.value` | `vehicle.charging.power.value` | float kW |
| `chargingStatus.chargeRate_kmph.value` | `vehicle.charging.rate.value` | disabled when not charging |
| `chargingStatus.remainingChargingTimeToComplete_min.value` | computed: `(vehicle.charging.estimated_date_reached.value - datetime.now(tz=timezone.utc)).seconds // 60` | `estimated_date_reached` is a `datetime`; subtract now for remaining minutes |
| `chargingStatus.targetSOC_pct.value` | `vehicle.charging.settings.target_level.value` | float |
| plug connected state | `vehicle.charging.connector.connection_state.value` | `ChargingConnectorConnectionState.DISCONNECTED` / `.CONNECTED` |

### Climatisation

| Old path | New path |
|---|---|
| `climatisationStatus.climatisationState.value` | `vehicle.climatization.state.value` |
| `climatisationSettings.targetTemperature_C.value` | `vehicle.climatization.settings.target_temperature.value` (°C) |

### Doors / lock

| Old path | New path | Notes |
|---|---|---|
| `accessStatus.overallStatus.value` | `vehicle.doors.lock_state.value` | overall locked state; was `None` (disabled) in test |
| per-door lock/open | `vehicle.doors.doors[door_id].lock_state.value` / `.open_state.value` | |

### Windows

**Window open percentage is no longer available.** CarConnectivity only exposes `open_state` (OPEN / CLOSED), not a percentage. The `_patch_weconnect_window()` monkey-patch in `poller.py` should be removed and `windows_json` storage adapted accordingly.

| Old path | New path |
|---|---|
| `windowOpen_pct` (monkey-patched `_open_pct`) | not available |
| open/closed state | `vehicle.windows.windows[win_id].open_state.value` |

---

## Data timestamp

Replace all `carCapturedTimestamp.value` usage with `.last_updated` on any attribute that best represents "when was this data fresh". All `last_updated` values are timezone-aware `datetime` objects.

Suggested approach in `_extract_snapshot`:
```python
candidates = [
    drive.level.last_updated,
    vehicle.position.latitude.last_updated,
    vehicle.charging.state.last_updated,
]
car_captured_at = max(t for t in candidates if t is not None)
```

---

## Control commands

### Old
```python
from weconnect.elements.control_operation import ControlOperation
vehicle.controls.climatizationControl.value = ControlOperation.START
vehicle.controls.chargingControl.value = ControlOperation.START
```

### New
```python
from carconnectivity.command_impl import ChargingStartStopCommand, ClimatizationStartStopCommand

# Climatisation
cl_cmd = vehicle.climatization.commands.get(ClimatizationStartStopCommand)
cl_cmd.command.value = ClimatizationStartStopCommand.Command.START  # or .STOP
cl_cmd.send()

# Charging
ch_cmd = vehicle.charging.commands.get(ChargingStartStopCommand)
ch_cmd.command.value = ChargingStartStopCommand.Command.START  # or .STOP
ch_cmd.send()
```

> Note: exact command send pattern (`cl_cmd.send()` vs direct assignment) should be confirmed against carconnectivity source or docs when implementing — only the import path and enum names were confirmed in research.

---

## Files that need changing

| File | What changes |
|---|---|
| `backend/requirements.txt` | Remove `weconnect[Images]==0.60.11`; add `carconnectivity` and `carconnectivity-connector-volkswagen` |
| `backend/poller.py` | Replace `init_weconnect()`, `_get_vehicle()`, `_extract_snapshot()`, `_domain()`, `_val()`, `_car_ts()`, `_patch_weconnect_window()` |
| `backend/routers/vehicle.py` | Replace `ControlOperation` import and climate/charging control logic |
| `backend/mock_weconnect.py` | Rewrite to implement CarConnectivity-compatible interface (`get_garage()`, `fetch_all()`, `startup()`, `shutdown()`) |

---

## Gotchas

1. **Battery temperature is in Kelvin** (`284.15 K` = `11 °C`). The existing `- 273.15` conversion stays.
2. **Outside temperature is already in °C** (unlike the old lib which returned Kelvin). Remove any `- 273.15` for that field.
3. **No window open percentage** - drop `_patch_weconnect_window()` entirely. The `windows_json` DB column will need to store only OPEN/CLOSED.
4. **`ChargingType.INVALID`** is what the API returns when the car is not charging (not an error - treat as `None`/unknown).
5. **Many fields have `.enabled = False`** when the car is parked/disconnected. Always guard with `if attr.enabled` before reading `.value`.
6. **`estimated_date_reached`** can be stale (it reflects the last charge session's estimate, not live). Compute remaining minutes from it only when `charging.state.value == ChargingState.CHARGING`.
7. **Token file** path is `tokenstore_file` kwarg (not `tokenfile`).
