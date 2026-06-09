"""Ties the pipeline together for one inbound message:
load session -> persist user turn -> ask the agent -> persist + send reply.
"""
from __future__ import annotations

import logging

from .agent import Agent
from .config import Config, get_config
from .outbound import Outbound
from .store import Store

log = logging.getLogger("physiobot.orchestrator")

FALLBACK = "Sorry, something went wrong on my side. Please try again in a moment."


class Orchestrator:
    def __init__(
        self,
        config: Config | None = None,
        store: Store | None = None,
        agent: Agent | None = None,
        outbound: Outbound | None = None,
    ):
        self.config = config or get_config()
        self.store = store or Store()
        self.agent = agent or Agent(self.config)
        self.outbound = outbound or Outbound(self.config)

    def handle_message(self, phone: str, text: str) -> str:
        """Process one inbound message and send the reply. Returns the reply
        text (useful for tests / local simulation)."""
        self.store.touch_session(phone)
        self.store.add_message(phone, "user", text)
        try:
            reply = self.agent.respond(self.store.history(phone))
            if not reply:
                reply = (
                    "I'm here to help — could you tell me a bit more? You can also "
                    f"reach the clinic at {self.config.clinic.contact_number}."
                )
        except Exception:
            log.exception("agent failed for %s", phone)
            reply = FALLBACK
        self.store.add_message(phone, "assistant", reply)
        self.outbound.send_text(phone, reply)
        return reply
