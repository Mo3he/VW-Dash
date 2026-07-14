from __future__ import annotations
"""
Optional MQTT publisher for Home Assistant integration.

When enabled in Settings, every poll cycle publishes the latest vehicle snapshot
to an MQTT broker. Home Assistant MQTT discovery config messages are published
(retained) on each connect so the vehicle and all its sensors appear automatically.

The module is entirely self-contained: if MQTT is disabled or paho-mqtt is not
installed, all functions become no-ops and never raise into the poller.
"""
import json
import logging
import re
import threading
from typing import Any

logger = logging.getLogger(__name__)

_client: Any = None
_lock = threading.Lock()
# Snapshot of the settings used to build the current client. When settings change
# we tear down and rebuild on next publish.
_active_config: tuple | None = None

# Sensor / binary_sensor definitions exposed to Home Assistant.
# id           -> object_id used in unique_id and discovery topic
# name         -> friendly name shown in HA
# component    -> "sensor" or "binary_sensor"
# tpl          -> value_template evaluated against the JSON state payload
# unit         -> unit_of_measurement (optional)
# device_class -> HA device_class (optional)
# state_class  -> HA state_class (optional)
# icon         -> mdi icon (optional)
_ENTITIES: list[dict[str, str]] = [
    {"id": "soc", "name": "State of Charge", "component": "sensor",
     "tpl": "{{ value_json.soc_pct }}", "unit": "%", "device_class": "battery", "state_class": "measurement"},
    {"id": "range", "name": "Range", "component": "sensor",
     "tpl": "{{ value_json.range_km }}", "unit": "km", "device_class": "distance", "state_class": "measurement",
     "icon": "mdi:map-marker-distance"},
    {"id": "charging_state", "name": "Charging State", "component": "sensor",
     "tpl": "{{ value_json.charging_state }}", "icon": "mdi:ev-station"},
    {"id": "charge_power", "name": "Charge Power", "component": "sensor",
     "tpl": "{{ value_json.charge_power_kw }}", "unit": "kW", "device_class": "power", "state_class": "measurement"},
    {"id": "charge_rate", "name": "Charge Rate", "component": "sensor",
     "tpl": "{{ value_json.charge_rate_km_h }}", "unit": "km/h", "icon": "mdi:speedometer"},
    {"id": "charge_type", "name": "Charge Type", "component": "sensor",
     "tpl": "{{ value_json.charge_type }}", "icon": "mdi:ev-plug-type2"},
    {"id": "remaining_charge_time", "name": "Remaining Charge Time", "component": "sensor",
     "tpl": "{{ value_json.remaining_charge_time_min }}", "unit": "min", "device_class": "duration",
     "icon": "mdi:timer-sand"},
    {"id": "target_soc", "name": "Target SoC", "component": "sensor",
     "tpl": "{{ value_json.target_soc_pct }}", "unit": "%", "icon": "mdi:battery-charging-high"},
    {"id": "outdoor_temp", "name": "Outdoor Temperature", "component": "sensor",
     "tpl": "{{ value_json.outdoor_temp_c }}", "unit": "°C", "device_class": "temperature", "state_class": "measurement"},
    {"id": "battery_temp", "name": "Battery Temperature", "component": "sensor",
     "tpl": "{{ value_json.battery_temp_c }}", "unit": "°C", "device_class": "temperature", "state_class": "measurement"},
    {"id": "cabin_temp", "name": "Cabin Temperature", "component": "sensor",
     "tpl": "{{ value_json.cabin_temp_c }}", "unit": "°C", "device_class": "temperature", "state_class": "measurement"},
    {"id": "climatisation_state", "name": "Climatisation State", "component": "sensor",
     "tpl": "{{ value_json.climatisation_state }}", "icon": "mdi:air-conditioner"},
    # binary sensors — plug: ON = connected; lock: for device_class "lock" ON means unlocked.
    {"id": "plug", "name": "Plug", "component": "binary_sensor",
     "tpl": "{{ 'ON' if value_json.plug_connected else 'OFF' }}", "device_class": "plug"},
    {"id": "locked", "name": "Lock", "component": "binary_sensor",
     "tpl": "{{ 'OFF' if value_json.locked else 'ON' }}", "device_class": "lock"},
]


def _config_tuple(s) -> tuple:
    return (
        s.mqtt_enabled, s.mqtt_host, s.mqtt_port, s.mqtt_username, s.mqtt_password,
        s.mqtt_base_topic, s.mqtt_discovery, s.mqtt_discovery_prefix, s.vw_vin, s.vehicle_name,
    )


def _node_id(s) -> str:
    vin = (s.vw_vin or "vwdash").strip()
    return "vwdash_" + re.sub(r"[^a-zA-Z0-9_-]", "", vin)


def _base_topic(s) -> str:
    return (s.mqtt_base_topic or "vwdash").strip().strip("/")


def _state_topic(s) -> str:
    return f"{_base_topic(s)}/state"


def _availability_topic(s) -> str:
    return f"{_base_topic(s)}/availability"


def _publish_discovery(client, s) -> None:
    node_id = _node_id(s)
    device = {
        "identifiers": [node_id],
        "name": s.vehicle_name or "VW-Dash",
        "manufacturer": "Volkswagen",
        "model": s.vehicle_name or "ID. series",
    }
    state_topic = _state_topic(s)
    avail_topic = _availability_topic(s)
    prefix = (s.mqtt_discovery_prefix or "homeassistant").strip().strip("/")

    for e in _ENTITIES:
        object_id = e["id"]
        cfg: dict[str, Any] = {
            "name": e["name"],
            "unique_id": f"{node_id}_{object_id}",
            "state_topic": state_topic,
            "value_template": e["tpl"],
            "availability_topic": avail_topic,
            "device": device,
        }
        if e.get("unit"):
            cfg["unit_of_measurement"] = e["unit"]
        for key in ("device_class", "state_class", "icon"):
            if e.get(key):
                cfg[key] = e[key]
        topic = f"{prefix}/{e['component']}/{node_id}/{object_id}/config"
        client.publish(topic, json.dumps(cfg), qos=1, retain=True)
    logger.info("MQTT: published Home Assistant discovery for %d entities", len(_ENTITIES))


def _build_client(s):
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        logger.warning("MQTT enabled but paho-mqtt is not installed — skipping")
        return None

    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=_node_id(s))
    except (AttributeError, TypeError):
        # paho-mqtt < 2.0 fallback
        client = mqtt.Client(client_id=_node_id(s))

    if s.mqtt_username:
        client.username_pw_set(s.mqtt_username, s.mqtt_password or None)

    avail_topic = _availability_topic(s)
    client.will_set(avail_topic, "offline", qos=1, retain=True)

    def _on_connect(cl, userdata, flags, reason_code, properties=None):
        rc = getattr(reason_code, "value", reason_code)
        if rc not in (0, None):
            logger.warning("MQTT connect failed (rc=%s)", rc)
            return
        logger.info("MQTT connected to %s:%s", s.mqtt_host, s.mqtt_port)
        cl.publish(avail_topic, "online", qos=1, retain=True)
        if s.mqtt_discovery:
            _publish_discovery(cl, s)

    client.on_connect = _on_connect

    try:
        client.connect_async(s.mqtt_host, int(s.mqtt_port or 1883), keepalive=60)
        client.loop_start()
    except Exception as exc:
        logger.error("MQTT connection to %s:%s failed: %s", s.mqtt_host, s.mqtt_port, exc)
        try:
            client.loop_stop()
        except Exception:
            pass
        return None
    return client


def _ensure_client():
    """Return a connected client for the current settings, (re)building if needed."""
    global _client, _active_config
    from config import settings as s

    if not s.mqtt_enabled or not s.mqtt_host:
        if _client is not None:
            _teardown_client()
        return None

    desired = _config_tuple(s)
    if _client is not None and _active_config == desired:
        return _client

    # Settings changed (or first use) — rebuild.
    if _client is not None:
        _teardown_client()
    _client = _build_client(s)
    _active_config = desired if _client is not None else None
    return _client


def _teardown_client() -> None:
    global _client
    if _client is None:
        return
    try:
        from config import settings as s
        _client.publish(_availability_topic(s), "offline", qos=1, retain=True)
    except Exception:
        pass
    try:
        _client.loop_stop()
        _client.disconnect()
    except Exception:
        pass
    _client = None


def publish_snapshot(payload: dict) -> None:
    """Publish the latest vehicle snapshot to MQTT. No-op when disabled."""
    from config import settings as s
    if not s.mqtt_enabled or not s.mqtt_host:
        return
    with _lock:
        client = _ensure_client()
        if client is None:
            return
        try:
            client.publish(_state_topic(s), json.dumps(payload), qos=0, retain=True)
        except Exception as exc:
            logger.warning("MQTT publish failed: %s", exc)


def init() -> None:
    """Connect at startup if MQTT is enabled."""
    from config import settings as s
    if not s.mqtt_enabled or not s.mqtt_host:
        return
    with _lock:
        _ensure_client()


def reset() -> None:
    """Force a rebuild on next publish (call after settings change)."""
    global _active_config
    with _lock:
        _teardown_client()
        _active_config = None
    # Reconnect immediately so discovery is refreshed without waiting for a poll.
    init()


def shutdown() -> None:
    """Publish offline + disconnect (called on app shutdown)."""
    with _lock:
        _teardown_client()
