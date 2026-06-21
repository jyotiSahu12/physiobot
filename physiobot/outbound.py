"""Send reply messages back to the patient via the Meta WhatsApp Cloud API.
Supports text and template-based messaging.
"""
from __future__ import annotations

import logging

import httpx

from .config import Config, get_config
from .templates import build_whatsapp_payload, format_template_text

log = logging.getLogger("physiobot.outbound")

GRAPH_URL = "https://graph.facebook.com/v21.0"


class Outbound:
    def __init__(self, config: Config | None = None):
        self.config = config or get_config()

    def send_text(self, to: str, text: str) -> None:
        """Send a standard free-text WhatsApp message."""
        meta = self.config.meta
        if not meta.configured:
            log.info("[DEV] would send text to %s: %s", to, text)
            return
        url = f"{GRAPH_URL}/{meta.phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
        headers = {"Authorization": f"Bearer {meta.token}"}
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=15)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            log.error("failed to send WhatsApp message to %s: Status %s, Response: %s", to, e.response.status_code, e.response.text)
        except httpx.HTTPError:
            log.exception("failed to send WhatsApp message to %s", to)

    def send_template(self, to: str, template_key: str, **kwargs) -> str:
        """Send a pre-registered WhatsApp template message.
        Returns the text response (used for local simulation / test replies)."""
        # Resolve text fallback first for dev log or simulation return value
        fallback_text = format_template_text(template_key, **kwargs)

        meta = self.config.meta
        if not meta.configured:
            log.info("[DEV] [TEMPLATE: %s] would send to %s: %s", template_key, to, fallback_text)
            return fallback_text

        url = f"{GRAPH_URL}/{meta.phone_number_id}/messages"
        payload = build_whatsapp_payload(template_key, to, **kwargs)
        headers = {"Authorization": f"Bearer {meta.token}"}
        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=15)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            log.error("failed to send WhatsApp template message (%s) to %s: Status %s, Response: %s", template_key, to, e.response.status_code, e.response.text)
        except httpx.HTTPError:
            log.exception("failed to send WhatsApp template message (%s) to %s", template_key, to)
        
        return fallback_text
