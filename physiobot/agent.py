"""The conversational agent: a bounded Ollama tool-calling loop.

`respond(history)` takes the conversation so far (oldest -> newest, the last
turn being the user's latest message) and returns the assistant's reply text.
The model may call tools (save patient info, list slots, book) which are
executed here and fed back until the model produces a final text reply.
"""
from __future__ import annotations

import datetime as dt
import logging
from zoneinfo import ZoneInfo

from .config import Config, get_config
from .llm import get_provider
from .tools.calendar import CalendarClient
from .tools.sheets import SheetsClient

log = logging.getLogger("physiobot.agent")

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "save_patient_info",
            "description": "Save a patient's details to the clinic records. Call this "
            "once you have collected the patient's name, phone, and what problem "
            "they are facing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Patient full name"},
                    "phone": {"type": "string", "description": "Patient phone number"},
                    "complaint": {"type": "string", "description": "The problem/pain/issue"},
                    "notes": {"type": "string", "description": "Any extra notes (optional)"},
                },
                "required": ["name", "phone", "complaint"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_free_slots",
            "description": "Get available appointment start times for a given date. "
            "Use this before offering times to a patient.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date as YYYY-MM-DD"},
                },
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_booking",
            "description": "Book an appointment for the patient at a specific slot. "
            "Only call this after confirming the exact date and time with the patient "
            "and after the slot was shown as free.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "phone": {"type": "string"},
                    "complaint": {"type": "string"},
                    "slot_datetime": {
                        "type": "string",
                        "description": "Appointment start as YYYY-MM-DDTHH:MM (24h)",
                    },
                },
                "required": ["name", "phone", "complaint", "slot_datetime"],
            },
        },
    },
]


_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def build_system_prompt(config: Config) -> str:
    tz = ZoneInfo(config.clinic.timezone)
    today = dt.datetime.now(tz)
    hours = config.hours
    closed = sorted(hours.closed_weekdays)
    open_days = [d for d in range(7) if d not in closed]
    open_text = ", ".join(_WEEKDAYS[d] for d in open_days) or "no days"
    closed_text = ", ".join(_WEEKDAYS[d] for d in closed) if closed else "none"
    return (
        f"You are the friendly receptionist for {config.clinic.name}, a "
        f"physiotherapy clinic. Today is {today:%A, %Y-%m-%d} ({config.clinic.timezone}).\n"
        f"The clinic is OPEN on: {open_text}, from {hours.open} to {hours.close}. "
        f"CLOSED on: {closed_text}. Appointments are {hours.slot_minutes} minutes.\n"
        "You DO know the clinic's hours and open days (stated above) — answer "
        "questions about them directly and confidently. Never say you are an AI, "
        "a language model, or that you lack the clinic's information.\n\n"
        "Your jobs:\n"
        "1. Greet warmly and understand the patient's problem.\n"
        "2. Collect their name, phone number, AND a short description of their "
        "issue. Only once you have all three, call save_patient_info — exactly "
        "ONCE per patient. Never call it again later in the same conversation.\n"
        "3. If they want an appointment, ask for a preferred date, call "
        "get_free_slots for that date, offer the available times, confirm one, "
        "then call create_booking.\n"
        "4. Resolve relative dates (\"tomorrow\", \"Monday\") to YYYY-MM-DD "
        "yourself using today's date.\n"
        "5. Keep replies short and warm — this is WhatsApp. Never invent slots; "
        "only offer times returned by get_free_slots.\n"
        f"6. If the patient needs a human or something you cannot do, share the "
        f"clinic number: {config.clinic.contact_number}.\n"
        "Do not ask for information you already have."
    )


class Agent:
    def __init__(
        self,
        config: Config | None = None,
        sheets: SheetsClient | None = None,
        calendar: CalendarClient | None = None,
        provider=None,
    ):
        self.config = config or get_config()
        self.sheets = sheets or SheetsClient(self.config)
        self.calendar = calendar or CalendarClient(self.config)
        self.provider = provider or get_provider(self.config)

    # --- tool dispatch -----------------------------------------------------
    @staticmethod
    def _normalize_args(args: dict) -> dict:
        """Models sometimes wrap a string value in a single-key dict
        (e.g. complaint={"complaint": "knee pain"}) or pass a list/dict where a
        string is expected. Flatten those so tools get clean scalars."""
        clean = {}
        for key, val in args.items():
            if isinstance(val, dict):
                if len(val) == 1:
                    val = next(iter(val.values()))
                else:
                    val = ", ".join(str(v) for v in val.values())
            elif isinstance(val, list):
                val = ", ".join(str(v) for v in val)
            clean[key] = val
        return clean

    def _run_tool(self, name: str, args: dict) -> str:
        args = self._normalize_args(args)
        try:
            if name == "save_patient_info":
                return self.sheets.save_patient_info(
                    args["name"], args["phone"], args["complaint"], args.get("notes", "")
                )
            if name == "get_free_slots":
                slots = self.calendar.get_free_slots(args["date"])
                if not slots:
                    return "No free slots on that date (clinic closed or fully booked)."
                return "Available start times: " + ", ".join(slots)
            if name == "create_booking":
                if self.sheets.booking_exists(args["phone"], args["slot_datetime"]):
                    return f"Already booked for {args['slot_datetime']}."
                ev = self.calendar.create_event(
                    args["name"], args["phone"], args["complaint"], args["slot_datetime"]
                )
                self.sheets.append_booking(
                    args["name"], args["phone"], args["complaint"],
                    args["slot_datetime"], ev["event_id"],
                )
                return f"Booking confirmed for {args['slot_datetime']}."
            return f"Unknown tool: {name}"
        except Exception:  # tools must never crash the conversation
            log.exception("tool %s failed", name)
            return (
                "That action failed on my side. Apologize and offer the clinic "
                f"contact number {self.config.clinic.contact_number}."
            )

    # --- main loop ---------------------------------------------------------
    def respond(self, history: list[dict]) -> str:
        messages = [{"role": "system", "content": build_system_prompt(self.config)}]
        messages.extend(history)

        for _ in range(self.config.llm.max_tool_iterations):
            assistant = self.provider.chat(messages, TOOL_SCHEMAS)
            messages.append(assistant)
            tool_calls = assistant.get("tool_calls") or []

            if not tool_calls:
                return (assistant.get("content") or "").strip()

            for call in tool_calls:
                result = self._run_tool(call["name"], call["arguments"])
                messages.append({"role": "tool", "tool_call_id": call["id"],
                                 "name": call["name"], "content": result})

        # Exhausted tool iterations — make one final plain reply.
        final = self.provider.chat(messages, None)
        return (final.get("content") or "").strip()
