from __future__ import annotations
"""
Read-only telemetry provider backed by the volkswagen.<country> website session
(the "authproxy" confidential OAuth client).

Why this exists
---------------
In May/June 2026 Volkswagen put the WeConnect *app* token exchange behind app
attestation (Play Integrity / client assertion), which open-source clients cannot
satisfy. The CARIAD BFF now returns ``400 invalid assertion headers`` for the app
client, breaking the carconnectivity/WeConnect path.

The volkswagen.<country> website logs in through a *server-side* confidential
client (``authproxy``) that does NOT require attestation, so its data is reachable
once you authenticate with your Volkswagen ID. This module reuses that website
session to read battery/charging/odometer telemetry.

Limitations
-----------
- Read-only. No remote control (lock/climate/charge).
- No live GPS / lock / window / door status (those sit behind VW's secured-operations
  tier that only the attestation-backed mobile app can read).

Auth flow (verified against a Swedish ID.4)
------------------------------------------
1. GET  /app/authproxy/login            -> Auth0 universal login (or silent SSO)
2. POST identity.vwgroup.io/u/login     -> credentials
3. (first time) auto-accept the consent screen
4. (sometimes) an email-OTP challenge -> submit_otp(code)
The resulting cookies are persisted; while the SSO cookie is valid, ``refresh()``
re-establishes the short-lived portal session silently (no credentials, no OTP).
"""
import json
import logging
import os
import re
import uuid
from typing import Any, Optional
from urllib.parse import parse_qs, urljoin, urlparse

import requests

logger = logging.getLogger(__name__)

_DATA_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data"))
_COOKIE_FILE = os.path.join(_DATA_DIR, "portal_session.json")

IDENTITY = "https://identity.vwgroup.io"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")

# Per-country portal configuration. Verified: se, de. Others follow the same
# pattern (host www.volkswagen.<cc>, feature-access group vw-<cc>) but their
# my-pages redirect path may differ; add/adjust as confirmed.
_COUNTRY_PROFILES: dict[str, dict[str, str]] = {
    "se": {"host": "https://www.volkswagen.se", "mypage": "/sv/aga-en-vw/myvolkswagen.html", "lang": "sv-SE"},
    "de": {"host": "https://www.volkswagen.de", "mypage": "/de/besitzer-und-nutzer/myvolkswagen.html", "lang": "de-DE"},
}

_SCOPE_VW = "profile,address,phone,carConfigurations,dealers,cars,vin,profession"


class WebsitePortalError(Exception):
    """Base error."""


class WebsitePortalAuthError(WebsitePortalError):
    """Login/refresh failed; full re-auth (incl. OTP) needed."""


class OTPRequired(WebsitePortalError):
    """Login reached an email-OTP challenge; call submit_otp(code) to continue."""


def _profile(country: str) -> dict[str, str]:
    cc = (country or "se").strip().lower()
    if cc in _COUNTRY_PROFILES:
        return _COUNTRY_PROFILES[cc]
    # Generic fallback for untested countries; my-pages path is a best guess.
    return {"host": f"https://www.volkswagen.{cc}", "mypage": "/", "lang": f"{cc}-{cc.upper()}"}


class WebsitePortalProvider:
    """volkswagen.<country> website-session telemetry provider (read-only)."""

    # Lets the poller distinguish this from a carconnectivity instance.
    is_website_portal = True

    def __init__(self, email: str, password: str, country: str = "se", vin: str | None = None) -> None:
        self._email = email
        self._password = password
        self._country = (country or "se").strip().lower()
        prof = _profile(self._country)
        self.portal = prof["host"]
        self.mypage = self.portal + prof["mypage"]
        self.lang = prof["lang"]
        self.fag_base = f"vw-{self._country}"
        self._vin = vin or None
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": UA})
        self._pending_otp: dict[str, Any] | None = None
        self._load_cookies()

    # -- cookie persistence -------------------------------------------------

    def _load_cookies(self) -> None:
        try:
            with open(_COOKIE_FILE) as f:
                data = json.load(f)
            if data.get("country") != self._country:
                return  # cookies belong to a different portal
            for c in data.get("cookies", []):
                self._session.cookies.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/"))
            logger.info("Loaded %d portal cookies from disk", len(data.get("cookies", [])))
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass

    def _save_cookies(self) -> None:
        try:
            os.makedirs(_DATA_DIR, exist_ok=True)
            cookies = [
                {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
                for c in self._session.cookies
            ]
            with open(_COOKIE_FILE, "w") as f:
                json.dump({"country": self._country, "cookies": cookies}, f)
        except Exception as exc:
            logger.debug("Could not persist portal cookies: %s", exc)

    def _csrf(self) -> str | None:
        for c in self._session.cookies:
            if c.name == "csrf_token":
                return c.value
        return None

    @property
    def _authproxy_login_url(self) -> str:
        return (
            self.portal + "/app/authproxy/login"
            f"?fag={self.fag_base},vwag-weconnect"
            f"&scope-{self.fag_base}={_SCOPE_VW}"
            "&scope-vwag-weconnect=openid,mbb&prompt-vwag-weconnect=none"
            f"&redirectUrl={self.mypage}&sessionTimeout=1800"
        )

    # -- login --------------------------------------------------------------

    def _on_portal(self, url: str) -> bool:
        host = urlparse(url).hostname or ""
        return host.endswith(urlparse(self.portal).hostname or "") and "/app/authproxy/login" not in url

    def _follow(self, url: str, max_hops: int = 25):
        """Follow redirects. Returns ('portal'|'otp'|'page'|'stop', url[, html])."""
        for _ in range(max_hops):
            if self._on_portal(url):
                return ("portal", url)
            r = self._session.get(url, allow_redirects=False)
            loc = r.headers.get("Location")
            cur = str(r.url)
            if "/u/mfa-email-challenge" in cur and r.status_code == 200:
                return ("otp", cur, r.text)
            if r.status_code == 200 and not loc:
                return ("page", cur, r.text)
            if not loc:
                return ("stop", cur)
            url = urljoin(url, loc)
        return ("stop", url)

    def _handle_consent(self, html: str) -> tuple[str, ...]:
        """Auto-accept the one-time Auth0 consent screen. Returns _follow() result."""
        m = re.search(r"window\._IDK\s*=\s*(\{.*?\});", html, re.S)
        if not m:
            raise WebsitePortalAuthError("consent page without _IDK payload")
        data = json.loads(m.group(1))["Data"]
        relay = data["relayStateToken"]
        cstate = data["state"]
        scope_ids = [sc["id"] for sc in data.get("scopes", [])]
        cr = self._session.post(
            f"{IDENTITY}/v2/login/ui/consent",
            data={"relayState": relay, "state": cstate,
                  "consentedScopes": ",".join(scope_ids), "decision": "allow"},
            allow_redirects=False,
        )
        loc = cr.headers.get("Location")
        if not loc:
            raise WebsitePortalAuthError("consent POST did not redirect")
        return self._follow(urljoin(f"{IDENTITY}/v2/login/ui/consent", loc))

    def login(self) -> str:
        """Full login. Returns 'ok' (logged in) or 'otp_required'."""
        r = self._session.get(self._authproxy_login_url, allow_redirects=True)
        page_url = str(r.url)

        # Already authenticated via SSO cookie?
        if self._on_portal(page_url):
            self._save_cookies()
            return "ok"

        if "/u/login" not in page_url:
            raise WebsitePortalAuthError(f"unexpected authorize landing: {page_url[:160]}")

        state = parse_qs(urlparse(page_url).query).get("state", [None])[0]
        if not state:
            raise WebsitePortalAuthError("no login state token")

        r = self._session.post(
            f"{IDENTITY}/u/login?state={state}",
            data={"state": state, "username": self._email, "password": self._password},
            allow_redirects=False,
        )
        loc = r.headers.get("Location")
        if not loc:
            raise WebsitePortalAuthError("login rejected (wrong credentials?)")

        res = self._follow(urljoin(str(r.url), loc))
        return self._resolve(res)

    def _resolve(self, res: tuple) -> str:
        """Turn a _follow() result into 'ok'/'otp_required', handling consent."""
        kind = res[0]
        if kind == "portal":
            self._pending_otp = None
            self._save_cookies()
            return "ok"
        if kind == "otp":
            self._pending_otp = {"page_url": res[1], "html": res[2] if len(res) > 2 else ""}
            return "otp_required"
        if kind == "page":
            html = res[2] if len(res) > 2 else ""
            if '"page":"consent"' in html or "consent" in (urlparse(res[1]).path or ""):
                return self._resolve(self._handle_consent(html))
            raise WebsitePortalAuthError(f"login stopped on unexpected page: {res[1][:160]}")
        raise WebsitePortalAuthError(f"login did not reach portal: {res[1][:160]}")

    def submit_otp(self, code: str) -> str:
        """Submit an email-OTP code to continue a pending login. Returns 'ok'."""
        if not self._pending_otp:
            raise WebsitePortalError("no OTP challenge pending")
        page_url = self._pending_otp["page_url"]
        html = self._pending_otp.get("html", "")
        state = parse_qs(urlparse(page_url).query).get("state", [None])[0]
        fields: dict[str, str] = {}
        action = page_url
        m = re.search(r"window\._IDK\s*=\s*(\{.*?\});", html, re.S)
        if m:
            try:
                data = json.loads(m.group(1)).get("Data", {})
                if data.get("state"):
                    state = data["state"]
            except (ValueError, KeyError):
                pass
        if state:
            fields["state"] = state
        fields["code"] = code
        r = self._session.post(action, data=fields, allow_redirects=False)
        loc = r.headers.get("Location")
        if not loc:
            raise WebsitePortalAuthError("OTP rejected")
        res = self._follow(urljoin(action, loc))
        return self._resolve(res)

    def refresh(self) -> None:
        """Silently re-establish the portal session via the SSO cookie."""
        r = self._session.get(self._authproxy_login_url, allow_redirects=True)
        url = str(r.url)
        if self._on_portal(url):
            self._save_cookies()
            return
        # SSO cookie expired -> need a full re-auth (may require OTP).
        result = self.login()
        if result != "ok":
            raise WebsitePortalAuthError("SSO session expired; re-auth required (OTP?)")

    def shutdown(self) -> None:
        self._save_cookies()
        try:
            self._session.close()
        except Exception:
            pass

    # -- data ---------------------------------------------------------------

    def _get(self, path: str, accept: str = "application/json", _retried: bool = False) -> tuple[int, str]:
        headers = {
            "User-Agent": UA,
            "Accept": accept,
            "Accept-Language": self.lang,
            "x-csrf-token": self._csrf() or "",
            "user-id": "__userId__",
            "traceId": uuid.uuid4().hex,
            "Referer": self.mypage,
        }
        r = self._session.get(self.portal + path, headers=headers, allow_redirects=False)
        status = r.status_code
        location = r.headers.get("Location", "")
        body = r.text
        login_redirect = status in (301, 302, 303, 307, 308) and any(
            s in location for s in ("/u/login", "/signin-service", "/authorize")
        )
        if not _retried and (status in (401, 403) or login_redirect or (status >= 500 and body[:1] == "<")):
            self.refresh()
            return self._get(path, accept, _retried=True)
        return status, body

    def _proxy(self, fag: str, path: str, accept: str = "*/*") -> tuple[int, str]:
        return self._get(f"/app/authproxy/{fag}/proxy{path}", accept=accept)

    def get_first_vin(self) -> str | None:
        if self._vin:
            return self._vin
        st, body = self._proxy(self.fag_base, "/v2/users/me/relations?resourceHost=myvw-vum-prod",
                               accept="application/json")
        if st != 200:
            return None
        vins = re.findall(r'"vin"\s*:\s*"([A-Z0-9]{17})"', body)
        return vins[0] if vins else None

    def get_charging(self, vin: str) -> dict[str, Any]:
        st, body = self._proxy(
            "vwag-weconnect",
            f"/vehicles/{vin}/charging/status?gdc=myvw-wcar-prod&resourceHost=myvw-vcf-prod",
        )
        if st != 200:
            logger.debug("portal charging %s -> %s", vin, st)
            return {}
        try:
            d = json.loads(body).get("data", {})
        except ValueError:
            return {}
        bs = d.get("batteryStatus") or {}
        cs = d.get("chargingStatus") or {}
        ps = d.get("plugStatus") or {}
        out: dict[str, Any] = {}

        def put(k: str, v: Any) -> None:
            if v is not None:
                out[k] = v

        put("soc_pct", bs.get("currentSOC_pct"))
        rng = bs.get("cruisingRangeElectric_km")
        if rng is not None:
            out["range_km"] = rng
            out["range_miles"] = round(rng * 0.621371, 1)
        put("target_soc_pct", bs.get("navigationTargetSOC_pct"))
        temp_k = bs.get("temperatureHvBattery_K")
        if temp_k is not None:
            out["battery_temp_c"] = round(temp_k - 273.15, 1)
        put("charging_state", cs.get("chargingState"))
        put("charge_power_kw", cs.get("chargePower_kW"))
        put("charge_rate_km_h", cs.get("chargeRate_kmph"))
        put("remaining_charge_time_min", cs.get("remainingChargingTimeToComplete_min"))
        put("charge_type", cs.get("chargeType") or cs.get("chargeMode"))
        plug = ps.get("plugConnectionState")
        if plug is not None:
            out["plug_connected"] = (plug == "connected")
        ts = bs.get("carCapturedTimestamp") or cs.get("carCapturedTimestamp")
        if ts:
            out["car_captured_at"] = _parse_ts(ts)
        return out

    def get_maintenance(self, vin: str) -> dict[str, Any]:
        st, body = self._proxy(
            self.fag_base,
            f"/vehicles/{vin}/maintenance/status?gdc=myvw-wcar-prod&resourceHost=myvw-vcf-prod",
        )
        if st != 200:
            logger.debug("portal maintenance %s -> %s", vin, st)
            return {}
        try:
            d = json.loads(body).get("data", {})
        except ValueError:
            return {}
        out: dict[str, Any] = {}
        if d.get("mileage_km") is not None:
            out["odometer_km"] = float(d["mileage_km"])
        ts = d.get("carCapturedTimestamp")
        if ts:
            out["car_captured_at"] = _parse_ts(ts)
        return out

    def get_snapshot(self) -> dict[str, Any]:
        """Return a flat dict of telemetry mapped to VehicleSnapshot fields."""
        vin = self.get_first_vin()
        if not vin:
            raise WebsitePortalError("no vehicle (VIN) available from portal")
        self._vin = vin
        data: dict[str, Any] = {}
        data.update(self.get_charging(vin))
        maint = self.get_maintenance(vin)
        # Prefer the freshest car_captured_at across sources.
        cap = data.get("car_captured_at")
        if maint.get("car_captured_at") and (cap is None or maint["car_captured_at"] > cap):
            cap = maint["car_captured_at"]
        data.update({k: v for k, v in maint.items() if k != "car_captured_at"})
        if cap is not None:
            data["car_captured_at"] = cap
        return data

    # carconnectivity-compatibility shims (so the poller can call uniformly) ---

    def fetch_all(self) -> None:  # noqa: D401 - portal fetches lazily in get_snapshot
        """No-op: the portal is queried directly in get_snapshot()."""


def _parse_ts(ts: str):
    from datetime import datetime, timezone
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, AttributeError):
        return None
