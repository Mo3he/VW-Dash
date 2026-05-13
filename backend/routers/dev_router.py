from __future__ import annotations
"""
/api/dev/* endpoints — only mounted when USE_MOCK_WC=1.

Lets you inspect and control the mock WeConnect state machine without
restarting the backend.
"""
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from poller import get_mock_weconnect

router = APIRouter(prefix="/api/dev", tags=["dev"])


class ScenarioRequest(BaseModel):
    scenario: str


class StateOverrideRequest(BaseModel):
    fields: dict[str, Any]


@router.get("/status")
def dev_status():
    """Return the current mock state (scenario name, tick, live telemetry)."""
    mock = get_mock_weconnect()
    if mock is None:
        raise HTTPException(503, "Mock WeConnect is not active")
    return mock.get_status()


@router.get("/scenarios")
def dev_scenarios():
    """List all built-in scenario names."""
    from mock_weconnect import MockWeConnect
    return {"scenarios": MockWeConnect.available_scenarios()}


@router.post("/scenario")
def dev_set_scenario(body: ScenarioRequest):
    """Switch to a named scenario and reset the tick counter to 0."""
    mock = get_mock_weconnect()
    if mock is None:
        raise HTTPException(503, "Mock WeConnect is not active")
    try:
        mock.set_scenario(body.scenario)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "scenario": body.scenario}


@router.post("/state")
def dev_set_state(body: StateOverrideRequest):
    """
    Override specific state fields for the next poll tick.

    Example body: {"fields": {"soc_pct": 50, "plug_connected": true}}

    Valid field names match MockVehicleState attributes:
      soc_pct, range_km, odometer_km, charging_state, plug_connected,
      charge_power_kw, latitude, longitude, parking_time (ISO string or null),
      locked, outdoor_temp_c, cabin_temp_c, target_soc_pct
    """
    mock = get_mock_weconnect()
    if mock is None:
        raise HTTPException(503, "Mock WeConnect is not active")
    # Convert parking_time ISO string to datetime if provided
    fields = dict(body.fields)
    if "parking_time" in fields and isinstance(fields["parking_time"], str):
        from datetime import datetime, timezone
        fields["parking_time"] = datetime.fromisoformat(fields["parking_time"])
    mock.set_state_override(fields)
    return {"ok": True, "overrides_queued": list(fields.keys())}
