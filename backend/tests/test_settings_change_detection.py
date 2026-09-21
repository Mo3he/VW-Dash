"""
Tests that PATCH /api/settings only reconnects WeConnect / MQTT when values really change.

Calls update_settings directly with persistence and side effects stubbed out, so the
real data/config.json is never touched.
"""
import pytest

from routers import settings_router
from routers.settings_router import SettingsUpdate, update_settings


@pytest.fixture()
def calls(monkeypatch):
    log = {"reset_weconnect": 0, "poll": 0, "mqtt_reset": 0}

    monkeypatch.setattr(settings_router, "persist_settings", lambda **kw: None)
    monkeypatch.setattr(settings_router.poller, "reset_weconnect", lambda: log.__setitem__("reset_weconnect", log["reset_weconnect"] + 1))

    class _Exec:
        def submit(self, fn, *a, **kw):
            name = getattr(fn, "__name__", "")
            if name == "poll":
                log["poll"] += 1
            elif name == "reset":
                log["mqtt_reset"] += 1

    monkeypatch.setattr(settings_router, "_executor", _Exec())

    s = settings_router.settings
    monkeypatch.setattr(s, "vw_username", "user@example.com")
    monkeypatch.setattr(s, "vw_vin", "VIN123")
    monkeypatch.setattr(s, "vw_provider", "carconnectivity")
    monkeypatch.setattr(s, "vw_country", "se")
    monkeypatch.setattr(s, "mqtt_enabled", True)
    monkeypatch.setattr(s, "mqtt_host", "broker")
    monkeypatch.setattr(s, "mqtt_port", 1883)
    monkeypatch.setattr(s, "mqtt_username", "mq")
    monkeypatch.setattr(s, "mqtt_base_topic", "vwdash")
    monkeypatch.setattr(s, "mqtt_discovery", True)
    monkeypatch.setattr(s, "mqtt_discovery_prefix", "homeassistant")
    return log


def _patch(**fields):
    update_settings(SettingsUpdate(**fields))


def test_resending_unchanged_values_does_nothing(calls):
    _patch(
        vw_username="user@example.com", vw_vin="VIN123", vw_provider="carconnectivity",
        vw_country="se", vw_password="", mqtt_enabled=True, mqtt_host="broker",
        mqtt_port=1883, mqtt_username="mq", mqtt_password="", mqtt_base_topic="vwdash",
        mqtt_discovery=True, mqtt_discovery_prefix="homeassistant",
    )
    assert calls == {"reset_weconnect": 0, "poll": 0, "mqtt_reset": 0}


def test_changed_username_reconnects_weconnect_only(calls):
    _patch(vw_username="other@example.com")
    assert calls["reset_weconnect"] == 1
    assert calls["poll"] == 1
    assert calls["mqtt_reset"] == 0


def test_new_vw_password_reconnects(calls):
    _patch(vw_password="secret")
    assert calls["reset_weconnect"] == 1


def test_changed_mqtt_host_resets_mqtt_only(calls):
    _patch(mqtt_host="other-broker")
    assert calls["mqtt_reset"] == 1
    assert calls["reset_weconnect"] == 0


def test_new_mqtt_password_resets_mqtt(calls):
    _patch(mqtt_password="secret")
    assert calls["mqtt_reset"] == 1


def test_unrelated_setting_does_nothing(calls):
    _patch(electricity_rate_per_kwh=0.5)
    assert calls == {"reset_weconnect": 0, "poll": 0, "mqtt_reset": 0}
