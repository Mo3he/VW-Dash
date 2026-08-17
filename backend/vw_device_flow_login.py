from __future__ import annotations
"""
OAuth 2.0 Device Authorization Grant login for VW's WeConnect identity provider.

Why this exists
----------------
Since ~August 2026, VW's identity WAF started blocking the classic scripted
POST-to-HTML-login-form flow (``VWWebSession.do_web_auth`` in
carconnectivity-connector-volkswagen) with 403. The open-source community
(robinostlund/volkswagencarnet PR #340) found that identity.vwgroup.io also
exposes a standard OAuth 2.0 Device Authorization Grant (RFC 8628) under a
different, less-restricted client id. A client "approves" its own device code
by walking the same login pages a real browser would — reading state out of a
``window._IDK`` object VW injects into each page — then polls the token
endpoint. This module is a sync/requests port of that approach, wired in by
``patches/we_connect_session.patch``.

While the persisted SSO cookie is valid, login skips straight to the
device-confirmation step (no password submitted); a full email+password
login is only needed roughly once a day, same as VW's own apps.
"""
import json
import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any
from urllib.parse import parse_qs, urlparse

import json5
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_DATA_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data"))
_COOKIE_FILE = os.path.join(_DATA_DIR, "vw_device_flow_cookies.json")

IDENTITY = "https://identity.vwgroup.io"
DEVICE_AUTHORIZATION_URL = f"{IDENTITY}/oidc/v1/device_authorization"
TOKEN_URL = f"{IDENTITY}/oidc/v1/token"
LOGIN_IDENTIFIER_URL = IDENTITY + "/signin-service/v1/{client_id}/login/identifier"
LOGIN_AUTHENTICATE_URL = IDENTITY + "/signin-service/v1/{client_id}/login/authenticate"

DEVICE_FLOW_CLIENT_ID = "650d46ca-2475-4384-85c2-6af3bf3d52f1@apps_vw-dilab_com"
DEVICE_FLOW_SCOPE = "openid profile badge cars dealers vin offline_access"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")

_TRANSIENT_POLL_STATUSES = {429, 500, 502, 503, 504}
_TRANSIENT_POLL_ERRORS = {"temporarily_unavailable", "server_error"}

_VW_AUTH_ERROR_MESSAGES: dict[str, str] = {
    "login.errors.password_invalid": "Incorrect password.",
    "login.error.throttled": "Too many failed login attempts — please wait before trying again.",
    "login.error.locked": "Account has been locked due to too many failed attempts.",
    "login.error.blocked": "Login blocked by VW identity service.",
}


class DeviceFlowLoginError(Exception):
    """Raised when the VW device-flow login fails or VW's page shape changes."""


class IdKitStage(str, Enum):
    IDENTIFIER = "loginIdentifier"
    PASSWORD = "loginAuthenticate"
    CONFIRM = "codeConfirmation"
    SUCCESS = "verificationSuccess"


FULL_ROUTE = [IdKitStage.IDENTIFIER, IdKitStage.PASSWORD, IdKitStage.CONFIRM, IdKitStage.SUCCESS]
QUICK_ROUTE = [IdKitStage.CONFIRM, IdKitStage.SUCCESS]


def _extract_object_literal(text: str, start: int) -> str | None:
    """Return the balanced ``{...}`` substring beginning at/after `start`, string-aware."""
    open_idx = text.find("{", start)
    if open_idx < 0:
        return None
    depth = 0
    in_string: str | None = None
    escaped = False
    for i in range(open_idx, len(text)):
        ch = text[i]
        if in_string is not None:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == in_string:
                in_string = None
            continue
        if ch in ("'", '"'):
            in_string = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[open_idx:i + 1]
    return None


@dataclass
class _IdkPage:
    """Parsed ``window._IDK`` object plus the handful of fields we need."""

    stage: IdKitStage
    csrf_token: str | None
    client_id: str | None
    relay_state: str | None
    hmac: str | None
    # Raw "url" field from templateModel — for the confirm stage this is the
    # exact (pre-built, correctly query-stringed) form-action path VW expects;
    # hand-reconstructing it from relayState/hmac/user_code individually
    # produces a 400, so it's kept verbatim rather than decomposed.
    raw_url: str | None
    client_identity_name: str | None

    @classmethod
    def from_html(cls, html: str) -> "_IdkPage":
        soup = BeautifulSoup(html, "html.parser")
        for script in soup.find_all("script"):
            text = script.string or script.get_text() or ""
            idx = text.find("window._IDK")
            if idx < 0:
                continue
            eq = text.find("=", idx)
            if eq < 0:
                raise DeviceFlowLoginError("Found window._IDK but no assignment")
            literal = _extract_object_literal(text, eq + 1)
            if literal is None:
                raise DeviceFlowLoginError("Found window._IDK but no object literal")
            try:
                obj = json5.loads(literal)
            except ValueError as exc:
                raise DeviceFlowLoginError(f"Failed to parse window._IDK: {exc}") from exc
            if not isinstance(obj, dict):
                raise DeviceFlowLoginError("window._IDK is not an object")
            return cls._from_obj(obj)
        raise DeviceFlowLoginError(
            "window._IDK not found on page — VW's login page shape may have changed"
        )

    @classmethod
    def _from_obj(cls, obj: dict[str, Any]) -> "_IdkPage":
        template_model = obj.get("templateModel")
        if not isinstance(template_model, dict):
            raise DeviceFlowLoginError("window._IDK missing templateModel")
        raw_stage = template_model.get("template")
        try:
            stage = IdKitStage(raw_stage)
        except ValueError as exc:
            raise DeviceFlowLoginError(f"Unknown VW login stage {raw_stage!r}") from exc

        raw_url = template_model.get("url")
        raw_url = str(raw_url) if raw_url else None
        query = parse_qs(urlparse(raw_url).query) if raw_url else {}

        client_id = None
        client_model = template_model.get("clientLegalEntityModel")
        if isinstance(client_model, dict) and client_model.get("clientId"):
            client_id = client_model["clientId"]

        return cls(
            stage=stage,
            csrf_token=obj.get("csrf_token"),
            client_id=client_id,
            relay_state=template_model.get("relayState") or query.get("relayState", [None])[0],
            hmac=template_model.get("hmac") or query.get("hmac", [None])[0],
            raw_url=raw_url,
            client_identity_name=template_model.get("clientIdentityName"),
        )


def device_flow_login(username: str, password: str, cookie_file: str = _COOKIE_FILE) -> dict:
    """Run the OAuth device-authorization-grant login and return the raw token dict."""
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.5"})
    _load_cookies(session, cookie_file)

    device = _start_device_flow(session)
    device_code = device.get("device_code")
    verification_uri = device.get("verification_uri_complete") or device.get("verification_uri")
    if not device_code or not verification_uri:
        raise DeviceFlowLoginError("Device-authorization response missing device_code/verification_uri")
    interval = int(device.get("interval") or 5)
    expires_in = int(device.get("expires_in") or 330)

    _run_browser_route(session, verification_uri, username, password)
    _save_cookies(session, cookie_file)

    return _poll_token(session, device_code, interval, max_wait_seconds=max(expires_in - 5, 30))


def _start_device_flow(session: requests.Session) -> dict:
    resp = session.post(
        DEVICE_AUTHORIZATION_URL,
        data={"client_id": DEVICE_FLOW_CLIENT_ID, "scope": DEVICE_FLOW_SCOPE},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _run_browser_route(session: requests.Session, verification_uri: str, username: str, password: str) -> None:
    resp = session.get(verification_uri, timeout=30)
    page = _IdkPage.from_html(resp.text)

    route = QUICK_ROUTE if page.stage == IdKitStage.CONFIRM else FULL_ROUTE
    logger.info(
        "VW device-flow login: starting at stage=%s (route=%s)",
        page.stage.value, [s.value for s in route],
    )

    for expected_stage in route[:-1]:
        if page.stage != expected_stage:
            raise DeviceFlowLoginError(
                f"VW login flow changed: expected stage {expected_stage.value!r}, got {page.stage.value!r}"
            )
        url, payload = _build_request(expected_stage, page, username, password)
        resp = session.post(url, data=payload, timeout=30)
        _check_url_for_error(str(resp.url))
        if resp.status_code >= 400:
            raise DeviceFlowLoginError(
                f"HTTP {resp.status_code} while submitting VW login stage {expected_stage.value}"
            )
        page = _IdkPage.from_html(resp.text)

    if page.stage != route[-1]:
        raise DeviceFlowLoginError(f"VW login did not reach {route[-1].value!r} (got {page.stage.value!r})")
    logger.info("VW device-flow login: device code approved")


def _build_request(stage: IdKitStage, page: _IdkPage, username: str, password: str) -> tuple[str, dict[str, str]]:
    if page.csrf_token is None:
        raise DeviceFlowLoginError(f"VW login page for stage {stage.value!r} missing csrf token")

    if stage is IdKitStage.CONFIRM:
        # The confirm-stage form action is a fully pre-built path+querystring
        # (client_id/user_code/relayState/user_id/hmac already assembled by
        # VW); reconstructing it from the individual pieces returns HTTP 400.
        if not page.raw_url:
            raise DeviceFlowLoginError("VW confirm page missing form-action url")
        return (
            IDENTITY + "/signin-service/v1" + page.raw_url,
            {
                "_csrf": page.csrf_token, "client_identity_name": page.client_identity_name or "",
                # Mirrors the page's "Allow"/"Deny" submit buttons (name=value);
                # an empty "allow" approves the device code.
                "allow": "",
            },
        )

    client_id = page.client_id or DEVICE_FLOW_CLIENT_ID
    if page.relay_state is None or page.hmac is None:
        raise DeviceFlowLoginError(f"VW login page for stage {stage.value!r} missing relayState/hmac")

    if stage is IdKitStage.IDENTIFIER:
        return (
            LOGIN_IDENTIFIER_URL.format(client_id=client_id),
            {"_csrf": page.csrf_token, "relayState": page.relay_state, "hmac": page.hmac, "email": username},
        )
    if stage is IdKitStage.PASSWORD:
        return (
            LOGIN_AUTHENTICATE_URL.format(client_id=client_id),
            {
                "_csrf": page.csrf_token, "relayState": page.relay_state, "hmac": page.hmac,
                "email": username, "password": password,
            },
        )
    raise DeviceFlowLoginError(f"No request builder for stage {stage.value!r}")


def _check_url_for_error(url: str) -> None:
    error_val = parse_qs(urlparse(url).query).get("error", [None])[0]
    if not error_val:
        return
    message = _VW_AUTH_ERROR_MESSAGES.get(error_val) or f"Authentication rejected by VW: {error_val!r}"
    raise DeviceFlowLoginError(message)


def _poll_token(session: requests.Session, device_code: str, interval: int, max_wait_seconds: int) -> dict:
    deadline = time.monotonic() + max_wait_seconds
    poll_interval = max(interval, 1)
    while time.monotonic() < deadline:
        time.sleep(poll_interval)
        resp = session.post(
            TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device_code,
                "client_id": DEVICE_FLOW_CLIENT_ID,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in _TRANSIENT_POLL_STATUSES:
            continue
        try:
            body = resp.json()
        except ValueError:
            body = {}
        error = body.get("error", "")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            poll_interval += 5
            continue
        if error in _TRANSIENT_POLL_ERRORS:
            continue
        raise DeviceFlowLoginError(f"VW device-flow token polling failed: {error!r}")
    raise DeviceFlowLoginError("VW device-flow token polling timed out")


def _load_cookies(session: requests.Session, cookie_file: str) -> None:
    try:
        with open(cookie_file) as f:
            data = json.load(f)
        for c in data.get("cookies", []):
            session.cookies.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/"))
        logger.debug("Loaded %d VW device-flow cookies from disk", len(data.get("cookies", [])))
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass


def _save_cookies(session: requests.Session, cookie_file: str) -> None:
    try:
        os.makedirs(os.path.dirname(cookie_file), exist_ok=True)
        cookies = [
            {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
            for c in session.cookies
        ]
        with open(cookie_file, "w") as f:
            json.dump({"cookies": cookies}, f)
    except Exception as exc:
        logger.debug("Could not persist VW device-flow cookies: %s", exc)
