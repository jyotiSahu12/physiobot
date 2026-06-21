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

    def handle_message(
        self,
        phone: str,
        text: str,
        interactive_id: str | None = None,
        profile_name: str | None = None,
        message_id: str | None = None,
    ) -> str:
        """Process one inbound message and send the template reply.
        Returns the formatted template text (useful for tests / local simulation).

        This runs as a FastAPI BackgroundTask, whose exceptions are logged but
        otherwise swallowed — if anything here raises uncaught, the patient gets
        no reply at all and we'd never know. So the entire turn, including the
        initial DB writes, is wrapped: any failure still results in a fallback
        message being sent, and a failure persisting that fallback never prevents
        it from being returned/sent."""
        reply = FALLBACK
        try:
            # Drop duplicate webhook deliveries: Meta retries until it gets a
            # 200, so the same message can arrive several times. Claiming the id
            # before doing any work prevents a double reply or double booking.
            # (No-op for /simulate, which passes no message_id.)
            if not self.store.mark_processed(message_id):
                log.info("skipping duplicate message %s for %s", message_id, phone)
                return reply

            self.store.touch_session(phone)
            self.store.add_message(phone, "user", text)

            if interactive_id is not None:
                # Button/list replies carry an unambiguous option id — skip NLU
                # entirely so the LLM/regex parser can't misread it (e.g. "1-3 days"
                # as a pain score) and silently fill the wrong slot.
                intent, slots, red_flags = "interactive_reply", {}, []
            else:
                history = self.store.history(phone)
                parsed = self.parser.parse_message(history)
                intent = parsed["intent"]
                slots = parsed.get("slots", {})
                red_flags = parsed.get("red_flags_detected", [])

            # Transition state and select template
            template_key, template_params = self.state_machine.process_turn(
                phone,
                intent,
                slots,
                red_flags,
                interactive_id=interactive_id,
                profile_name=profile_name,
            )

            # Send template message
            reply = self.outbound.send_template(phone, template_key, **template_params)

        except Exception:
            log.exception("orchestrator turn processing failed for %s", phone)
            reply = FALLBACK
            try:
                self.outbound.send_text(phone, reply)
            except Exception:
                log.exception("failed to send fallback text to %s", phone)

        try:
            self.store.add_message(phone, "assistant", reply)
        except Exception:
            log.exception("failed to persist assistant reply for %s", phone)

        return reply
