from __future__ import annotations
import json
import os
from pydantic_settings import BaseSettings

_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "config.json")


class Settings(BaseSettings):

    vw_username: str = ""
    vw_password: str = ""
    vw_vin: str = ""

    poll_interval_seconds: int = 300
    db_path: str = "data/vwdash.db"

    electricity_rate_per_kwh: float = 0.13
    currency_symbol: str = "$"
    currency_after: bool = False  # True = "100 kr" style, False = "$100" style
    epa_rated_range_km: float = 410.0


def _load_config_file() -> dict:
    try:
        with open(_CONFIG_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_config_file(data: dict) -> None:
    os.makedirs(os.path.dirname(_CONFIG_FILE), exist_ok=True)
    with open(_CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _build_settings() -> Settings:
    base = Settings()
    overrides = _load_config_file()
    for key, val in overrides.items():
        if hasattr(base, key):
            setattr(base, key, val)
    return base


settings = _build_settings()


def persist_settings(**kwargs) -> None:
    """Write a subset of keys to data/config.json and update the live settings object."""
    current = _load_config_file()
    current.update({k: v for k, v in kwargs.items() if v is not None})
    _save_config_file(current)
    for k, v in kwargs.items():
        if v is not None and hasattr(settings, k):
            setattr(settings, k, v)
