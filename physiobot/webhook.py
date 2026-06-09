"""Pure helpers for the Meta WhatsApp webhook: verification, signature check,
and parsing inbound payloads. Kept free of FastAPI so they are easy to test.
"""
from __future__ import annotations

import hashlib
import hmac


def verify_subscription(mode: str, token: str, expected_token: str) -> bool:
    """GET /webhook handshake check."""
    return mode == "subscribe" and token == expected_token


def verify_signature(body: bytes, signature_header: str, app_secret: str) -> bool:
    """Validate Meta's X-Hub-Signature-256 header. If no app secret is
    configured (local dev), accept everything."""
    if not app_secret:
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.split("=", 1)[1])


def parse_incoming(payload: dict) -> list[tuple[str, str]]:
    """Extract [(from_phone, text), ...] text messages from a Meta webhook
    payload. Ignores statuses, reactions, and non-text message types."""
    out: list[tuple[str, str]] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                if msg.get("type") == "text":
                    phone = msg.get("from", "")
                    text = msg.get("text", {}).get("body", "")
                    if phone and text:
                        out.append((phone, text))
    return out
