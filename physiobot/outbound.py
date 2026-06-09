"""Send reply messages back to the patient via the Meta WhatsApp Cloud API."""
from __future__ import annotations

import logging

import httpx

from .config import Config, get_config

log = logging.getLogger("physiobot.outbound")

GRAPH_URL = "https://graph.facebook.com/v21.0"


class Outbound:
    def __init__(self, config: Config | None = None):
        self.config = config or get_config()

    def send_text(self, to: str, text: str) -> None:
        meta = self.config.meta
        if not meta.configured:
            # Dev mode: no Meta credentials yet — just log what we'd send.
            log.info("[DEV] would send to %s: %s", to, text)
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
        except httpx.HTTPError:
            log.exception("failed to send WhatsApp message to %s", to)
