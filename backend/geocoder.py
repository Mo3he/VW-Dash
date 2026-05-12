from __future__ import annotations
"""
Reverse geocoding via Nominatim (OpenStreetMap).
Respects the 1 req/sec rate limit required by the Nominatim ToS.
No API key needed.
"""
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
_NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
_USER_AGENT = "VW-Dash/1.0 (self-hosted EV dashboard; https://github.com/Mo3he/VW-Dash)"
_last_request_at: float = 0.0


def reverse_geocode(lat: float, lon: float) -> str | None:
    """Return a short human-readable address for the given coordinates, or None on failure."""
    global _last_request_at

    if lat is None or lon is None:
        return None

    # Nominatim ToS: max 1 req/sec
    elapsed = time.monotonic() - _last_request_at
    if elapsed < 1.1:
        time.sleep(1.1 - elapsed)

    try:
        params = urllib.parse.urlencode({
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "format": "json",
            "addressdetails": 1,
            "zoom": 16,
        })
        req = urllib.request.Request(
            f"{_NOMINATIM_URL}?{params}",
            headers={"User-Agent": _USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        _last_request_at = time.monotonic()

        addr = data.get("address", {})
        road = (
            addr.get("road")
            or addr.get("pedestrian")
            or addr.get("path")
            or addr.get("footway")
        )
        house = addr.get("house_number", "")
        city = (
            addr.get("city")
            or addr.get("town")
            or addr.get("village")
            or addr.get("municipality")
            or addr.get("county")
            or ""
        )

        parts: list[str] = []
        if road:
            parts.append(f"{road} {house}".strip() if house else road)
        if city:
            parts.append(city)

        return ", ".join(parts) if parts else data.get("display_name")

    except urllib.error.HTTPError as exc:
        _last_request_at = time.monotonic()
        if exc.code == 429:
            # Back off for 60s when rate-limited
            logger.warning("Nominatim rate-limited (429) — backing off 60s")
            time.sleep(60)
        else:
            logger.warning("Geocoding failed for (%.5f, %.5f): %s", lat, lon, exc)
        return None
    except Exception as exc:
        logger.warning("Geocoding failed for (%.5f, %.5f): %s", lat, lon, exc)
        return None


def forward_search(q: str, limit: int = 5) -> list[dict]:
    """Forward geocoding: returns up to `limit` location candidates for the query string."""
    global _last_request_at

    if not q or len(q.strip()) < 3:
        return []

    # Nominatim ToS: max 1 req/sec (shared rate-limit counter with reverse_geocode)
    elapsed = time.monotonic() - _last_request_at
    if elapsed < 1.1:
        time.sleep(1.1 - elapsed)

    try:
        params = urllib.parse.urlencode({
            "q": q,
            "format": "json",
            "limit": limit,
            "addressdetails": 0,
        })
        req = urllib.request.Request(
            f"{_NOMINATIM_SEARCH_URL}?{params}",
            headers={"User-Agent": _USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        _last_request_at = time.monotonic()
        return [
            {
                "display_name": r.get("display_name", ""),
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
            }
            for r in data
        ]
    except urllib.error.HTTPError as exc:
        _last_request_at = time.monotonic()
        if exc.code == 429:
            logger.warning("Nominatim rate-limited (429) during forward search")
        else:
            logger.warning("Forward geocode failed for %r: %s", q, exc)
        return []
    except Exception as exc:
        logger.warning("Forward geocode failed for %r: %s", q, exc)
        return []
