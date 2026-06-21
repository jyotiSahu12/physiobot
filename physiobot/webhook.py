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


def parse_incoming(payload: dict) -> list[dict]:
    """Extract inbound message events from a Meta webhook payload.

    Each event is a dict:
        phone:          sender's WhatsApp number (also the reliable contact number —
                        no need to ask the user to type it).
        text:           human-readable text: the typed message, or the title of a
                        button/list reply.
        interactive_id: the underlying option id when this was a button/list reply,
                        else None. Slot-filling uses this directly instead of
                        re-parsing the title text, since the id is unambiguous
                        (e.g. "1-3 days" as free text could be misread as a pain
                        score, but as an interactive_id it can only mean pain_duration).
        profile_name:   the sender's WhatsApp profile display name, if Meta included
                        it on this notification, else None.

    Ignores statuses, reactions, and unsupported message types.
    """
    out: list[dict] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            profile_names = {
                c.get("wa_id"): c.get("profile", {}).get("name")
                for c in value.get("contacts", [])
                if c.get("wa_id")
            }
            for msg in value.get("messages", []):
                phone = msg.get("from", "")
                if not phone:
                    continue

                msg_type = msg.get("type")
                text = None
                interactive_id = None
                if msg_type == "text":
                    text = msg.get("text", {}).get("body", "")
                elif msg_type == "interactive":
                    interactive = msg.get("interactive", {})
                    int_type = interactive.get("type")
                    reply = interactive.get(int_type, {}) if int_type else {}
                    interactive_id = reply.get("id") or None
                    text = reply.get("title") or interactive_id

                if text:
                    out.append({
                        "phone": phone,
                        "text": text,
                        "interactive_id": interactive_id,
                        "profile_name": profile_names.get(phone),
                    })
    return out
