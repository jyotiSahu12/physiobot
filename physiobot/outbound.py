"""Send reply messages back to the patient via the Meta WhatsApp Cloud API.
Supports text and template-based messaging.
"""
from __future__ import annotations

import logging

import httpx

from .config import Config, get_config
from .templates import (
    TEMPLATES,
    build_whatsapp_interactive_payload,
    build_whatsapp_payload,
    format_template_text,
)

log = logging.getLogger("physiobot.outbound")


class Outbound:
    def __init__(self, config: Config | None = None):
        self.config = config or get_config()

    def _messages_url(self) -> str:
        """Graph API send-messages endpoint, with the API version pulled from
        config (env: META_GRAPH_API_VERSION) so a Meta deprecation is a config
        bump, not a code change."""
        meta = self.config.meta
        return f"https://graph.facebook.com/{meta.api_version}/{meta.phone_number_id}/messages"

    def send_text(self, to: str, text: str) -> None:
        """Send a standard free-text WhatsApp message."""
        meta = self.config.meta
        if not meta.configured:
            log.info("[DEV] would send text to %s: %s", to, text)
            return
        url = self._messages_url()
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
        If the template is defined as interactive, it sends it as a native WhatsApp interactive button/list.
        If use_templates is False, sends the template fallback text as a regular text message."""
        fallback_text = format_template_text(template_key, **kwargs)

        meta = self.config.meta
        if not meta.configured:
            log.info("[DEV] [TEMPLATE: %s] would send to %s: %s", template_key, to, fallback_text)
            return fallback_text

        template_cfg = TEMPLATES.get(template_key, TEMPLATES["generic_fallback"])
        is_interactive = "interactive_type" in template_cfg

        url = self._messages_url()
        headers = {"Authorization": f"Bearer {meta.token}"}

        if is_interactive:
            payload = build_whatsapp_interactive_payload(template_key, to, **kwargs)
        elif not meta.use_templates:
            # Fall back to sending as regular free-form text message (for development/testing)
            self.send_text(to, fallback_text)
            return fallback_text
        else:
            payload = build_whatsapp_payload(template_key, to, **kwargs)

        try:
            resp = httpx.post(url, json=payload, headers=headers, timeout=15)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            log.error("failed to send WhatsApp template message (%s) to %s: Status %s, Response: %s", template_key, to, e.response.status_code, e.response.text)
        except httpx.HTTPError:
            log.exception("failed to send WhatsApp template message (%s) to %s", template_key, to)
        
        return fallback_text
