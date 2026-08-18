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
# Entity ids (from _ENTITIES) whose "hide_until_seen" discovery config has been
# published because we've observed at least one non-null value for them. Some
# vehicles simply never report a field (e.g. outdoor temperature) — publishing
# a discovery config for it would leave a permanently "Unknown" entity in HA,
# so those entities are only announced once real data shows up.
_seen_fields: set[str] = set()
# Most recent full state payload published, kept so an optimistic update (see
# _publish_optimistic_update) can patch just the one field a command affects without
# clobbering everything else in the retained state topic.
_last_payload: dict[str, Any] | None = None

# Sensor / binary_sensor / switch definitions exposed to Home Assistant.
# id            -> object_id used in unique_id and discovery topic
# name          -> friendly name shown in HA
# component     -> "sensor", "binary_sensor", or "switch"
# tpl           -> value_template evaluated against the JSON state payload
# unit          -> unit_of_measurement (optional)
# device_class  -> HA device_class (optional)
# state_class   -> HA state_class (optional)
# icon          -> mdi icon (optional)
# payload_key   -> key in the state payload used to gate hide_until_seen entities
# hide_until_seen -> don't publish discovery config until payload_key has been non-null once
# command_topic -> suffix (under the base topic) switches subscribe to for ON/OFF commands
_ENTITIES: list[dict[str, Any]] = [
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
     "tpl": "{{ value_json.outdoor_temp_c }}", "unit": "°C", "device_class": "temperature", "state_class": "measurement",
     "payload_key": "outdoor_temp_c", "hide_until_seen": True},
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
    # switches — command_topic is subscribed to on connect; payload ON/OFF triggers
    # the same start/stop control used by the /api/vehicle/climate and
    # /api/vehicle/charging-control REST endpoints. State reflects actual vehicle
    # state (not just the last command sent), so it self-corrects on the next poll.
    {"id": "climate", "name": "Climate Control", "component": "switch",
     "tpl": "{{ 'ON' if value_json.climatisation_state in ['heating', 'cooling', 'ventilation'] else 'OFF' }}",
     "icon": "mdi:air-conditioner", "command_topic": "climate/set"},
    {"id": "charging", "name": "Charging", "component": "switch",
     "tpl": "{{ 'ON' if value_json.charging_state == 'charging' else 'OFF' }}",
     "icon": "mdi:ev-station", "command_topic": "charging/set"},
    {"id": "window_heating", "name": "Window Heating", "component": "switch",
     "tpl": "{{ 'ON' if value_json.window_heating_state == 'on' else 'OFF' }}",
     "icon": "mdi:car-defrost-rear", "command_topic": "window_heating/set"},
    # button — momentary trigger, no on/off state to track. Forces VW to refresh the
    # vehicle's data; see poller.wake_vehicle().
    {"id": "wake", "name": "Wake Vehicle", "component": "button",
     "icon": "mdi:sleep-off", "command_topic": "wake/set"},
]

# command_topic suffix -> control action dispatched via the matching poller.set_*/wake_vehicle
_COMMANDS: dict[str, str] = {
    "climate/set": "climate",
    "charging/set": "charging",
    "window_heating/set": "window_heating",
    "wake/set": "wake",
}

# action_name -> (state payload field, assumed value once started, assumed value once stopped),
# used to optimistically flip the HA switch the instant a command is sent — see
# publish_optimistic_update(). Values match what the entities' own value_template checks for.
_OPTIMISTIC_STATE: dict[str, tuple[str, str, str]] = {
    "climate": ("climatisation_state", "heating", "off"),
    "charging": ("charging_state", "charging", "off"),
    "window_heating": ("window_heating_state", "on", "off"),
}


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


def _publish_entity_discovery(client, s, e: dict[str, Any]) -> None:
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

    object_id = e["id"]
    cfg: dict[str, Any] = {
        "name": e["name"],
        "unique_id": f"{node_id}_{object_id}",
        "availability_topic": avail_topic,
        "device": device,
    }
    if e.get("tpl"):
        cfg["state_topic"] = state_topic
        cfg["value_template"] = e["tpl"]
    if e.get("unit"):
        cfg["unit_of_measurement"] = e["unit"]
    for key in ("device_class", "state_class", "icon"):
        if e.get(key):
            cfg[key] = e[key]
    if e.get("command_topic"):
        cfg["command_topic"] = f"{_base_topic(s)}/{e['command_topic']}"
    topic = f"{prefix}/{e['component']}/{node_id}/{object_id}/config"
    client.publish(topic, json.dumps(cfg), qos=1, retain=True)


def _publish_discovery(client, s) -> None:
    count = 0
    for e in _ENTITIES:
        if e.get("hide_until_seen") and e["id"] not in _seen_fields:
            continue
        _publish_entity_discovery(client, s, e)
        count += 1
    logger.info("MQTT: published Home Assistant discovery for %d entities", count)


def _publish_late_discovery(client, s, payload: dict) -> None:
    """Announce entities gated by hide_until_seen the first time real data appears."""
    for e in _ENTITIES:
        if not e.get("hide_until_seen") or e["id"] in _seen_fields:
            continue
        if payload.get(e.get("payload_key")) is not None:
            _seen_fields.add(e["id"])
            _publish_entity_discovery(client, s, e)
            logger.info("MQTT: late-published discovery for %s (data now available)", e["id"])


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
        base = _base_topic(s)
        for suffix in _COMMANDS:
            cl.subscribe(f"{base}/{suffix}", qos=1)

    def _on_message(cl, userdata, msg):
        suffix = msg.topic[len(_base_topic(s)) + 1:]
        action_name = _COMMANDS.get(suffix)
        if action_name is None:
            return
        import poller

        if action_name == "wake":
            # Button — momentary trigger, any payload (HA sends "PRESS") fires it.
            ok, message = poller.wake_vehicle()
            if not ok:
                logger.warning("MQTT: wake command failed: %s", message)
            else:
                logger.info("MQTT: wake command sent")
            return

        try:
            command = msg.payload.decode().strip().upper()
        except Exception:
            return
        if command not in ("ON", "OFF"):
            logger.warning("MQTT: ignoring unrecognised payload %r on %s", command, msg.topic)
            return
        action = "start" if command == "ON" else "stop"
        control_fn = {
            "climate": poller.set_climate,
            "charging": poller.set_charging,
            "window_heating": poller.set_window_heating,
        }[action_name]
        ok, message = control_fn(action)
        if not ok:
            logger.warning("MQTT: %s %s command failed: %s", action_name, action, message)
        else:
            logger.info("MQTT: %s %s command sent", action_name, action)
            field, on_value, off_value = _OPTIMISTIC_STATE[action_name]
            publish_optimistic_update(field, on_value if action == "start" else off_value)

    client.on_connect = _on_connect
    client.on_message = _on_message

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
    global _last_payload
    from config import settings as s
    if not s.mqtt_enabled or not s.mqtt_host:
        return
    with _lock:
        client = _ensure_client()
        if client is None:
            return
        try:
            client.publish(_state_topic(s), json.dumps(payload), qos=0, retain=True)
            _last_payload = payload
            if s.mqtt_discovery:
                _publish_late_discovery(client, s, payload)
        except Exception as exc:
            logger.warning("MQTT publish failed: %s", exc)


def publish_optimistic_update(field: str, value: Any) -> None:
    """Patch one field of the last published state and republish immediately.

    Used right after an MQTT-triggered command succeeds: HA switches are expected to flip
    instantly rather than wait for the real confirmation, which — thanks to the volkswagen
    connector's own status cache — can take a few minutes (see poller._schedule_confirmation_polls).
    The real poll that eventually lands corrects this automatically via the normal
    publish_snapshot() call above, whatever it turns out to say.
    """
    global _last_payload
    from config import settings as s
    if not s.mqtt_enabled or not s.mqtt_host or _last_payload is None:
        return
    with _lock:
        client = _ensure_client()
        if client is None:
            return
        try:
            optimistic = {**_last_payload, field: value}
            client.publish(_state_topic(s), json.dumps(optimistic), qos=0, retain=True)
            _last_payload = optimistic
        except Exception as exc:
            logger.warning("MQTT optimistic publish failed: %s", exc)


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
