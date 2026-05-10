from __future__ import annotations
import json
import logging
import threading
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


def fire(event_type: str, payload: dict) -> None:
    """POST a JSON notification to the configured webhook URL (non-blocking)."""
    from config import settings
    url = settings.webhook_url
    if not url:
        return
    body = json.dumps({"event": event_type, **payload}).encode()
    def _send():
        try:
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json", "User-Agent": "VW-Dash/1.0"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10):
                pass
        except Exception as exc:
            logger.warning("Webhook delivery failed (%s): %s", url, exc)
    threading.Thread(target=_send, daemon=True).start()
