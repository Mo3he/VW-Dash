from __future__ import annotations
import base64
import json
import os
from pydantic_settings import BaseSettings

_DATA_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data"))
_CONFIG_FILE = os.path.join(_DATA_DIR, "config.json")

_PASSWORD_FIELD = "vw_password"
_PASSWORD_ENC_FIELD = "vw_password_enc"


def _fernet(key: str):
    """Return a Fernet instance from a secret key string, or None if key is empty/invalid."""
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet
        # Accept raw 32-byte keys or already-encoded 44-char Fernet keys
        raw = key.encode() if isinstance(key, str) else key
        if len(raw) == 32:
            raw = base64.urlsafe_b64encode(raw)
        return Fernet(raw)
    except Exception:
        return None


def _encrypt_password(password: str, key: str) -> str | None:
    f = _fernet(key)
    if f is None or not password:
        return None
    return f.encrypt(password.encode()).decode()


def _decrypt_password(token: str, key: str) -> str | None:
    f = _fernet(key)
    if f is None or not token:
        return None
    try:
        return f.decrypt(token.encode()).decode()
    except Exception:
        return None


class Settings(BaseSettings):

    vw_username: str = ""
    vw_password: str = ""
    vw_vin: str = ""

    poll_interval_seconds: int = 300
    db_path: str = os.path.join(_DATA_DIR, "vwdash.db")

    electricity_rate_per_kwh: float = 0.0
    currency_symbol: str = "$"
    currency_after: bool = False  # True = "100 kr" style, False = "$100" style
    epa_rated_range_km: float = 410.0
    vehicle_name: str = "ID.4"
    battery_capacity_kwh: float = 77.0
    timezone: str = "UTC"

    # Security
    secret_key: str = ""        # used to encrypt vw_password in config.json; set via SECRET_KEY env var
    access_token: str = ""      # if set, API requires Authorization: Bearer <token>
    cors_origins: str = "http://localhost:3000,http://localhost:3001"  # comma-separated

    # Notifications
    webhook_url: str = ""       # POST JSON to this URL on key events (charge/trip start/end)


def _load_config_file() -> dict:
    try:
        with open(_CONFIG_FILE) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    # Decrypt password if stored encrypted
    if _PASSWORD_ENC_FIELD in data and _PASSWORD_FIELD not in data:
        secret_key = os.environ.get("SECRET_KEY", data.get("secret_key", ""))
        decrypted = _decrypt_password(data[_PASSWORD_ENC_FIELD], secret_key)
        if decrypted is not None:
            data[_PASSWORD_FIELD] = decrypted
        del data[_PASSWORD_ENC_FIELD]
    return data


def _save_config_file(data: dict) -> None:
    os.makedirs(os.path.dirname(_CONFIG_FILE), exist_ok=True)
    out = dict(data)
    secret_key = os.environ.get("SECRET_KEY", out.get("secret_key", ""))
    if secret_key and _PASSWORD_FIELD in out and out[_PASSWORD_FIELD]:
        encrypted = _encrypt_password(out[_PASSWORD_FIELD], secret_key)
        if encrypted:
            out[_PASSWORD_ENC_FIELD] = encrypted
            del out[_PASSWORD_FIELD]
    with open(_CONFIG_FILE, "w") as f:
        json.dump(out, f, indent=2)


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
