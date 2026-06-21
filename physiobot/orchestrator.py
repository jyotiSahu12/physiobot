"""Ties the pipeline together for one inbound message:
load session -> persist user turn -> parse NLU -> run state machine -> persist + send template reply.
"""
from __future__ import annotations

import logging

from .config import Config, get_config
from .outbound import Outbound
from .parser import Parser
from .state_machine import StateMachine
from .store import Store

log = logging.getLogger("physiobot.orchestrator")

FALLBACK = "Sorry, something went wrong on my side. Please try again in a moment."


class Orchestrator:
    def __init__(
        self,
        config: Config | None = None,
        store: Store | None = None,
        parser: Parser | None = None,
        state_machine: StateMachine | None = None,
        outbound: Outbound | None = None,
    ):
        self.config = config or get_config()
        self.store = store or Store()
        self.parser = parser or Parser(self.config)
        self.state_machine = state_machine or StateMachine(self.config, self.store.db_path)
        self.outbound = outbound or Outbound(self.config)

    def handle_message(self, phone: str, text: str) -> str:
        """Process one inbound message and send the template reply.
        Returns the formatted template text (useful for tests / local simulation)."""
        self.store.touch_session(phone)
        self.store.add_message(phone, "user", text)
        
        try:
            # Get recent history to parse the intent/slots contextually
            history = self.store.history(phone)
            parsed = self.parser.parse_message(history)
            
            # Transition state and select template
            template_key, template_params = self.state_machine.process_turn(
                phone,
                parsed["intent"],
                parsed.get("slots", {}),
                parsed.get("red_flags_detected", []),
            )
            
            # Send template message
            reply = self.outbound.send_template(phone, template_key, **template_params)
            
        except Exception:
            log.exception("orchestrator turn processing failed for %s", phone)
            reply = FALLBACK
            self.outbound.send_text(phone, reply)

        self.store.add_message(phone, "assistant", reply)
        return reply
