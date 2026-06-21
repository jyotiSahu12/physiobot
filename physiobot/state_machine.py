"""Deterministic state machine for managing conversation steps, slot filling, and integrations.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path

from .config import Config, get_config
from .tools.calendar import CalendarClient
from .tools.sheets import SheetsClient

log = logging.getLogger("physiobot.state_machine")

METADATA_PATH = Path(__file__).resolve().parent / "clinic_metadata.json"


def load_metadata() -> dict:
    try:
        with open(METADATA_PATH) as f:
            return json.load(f)
    except Exception:
        log.exception("failed to load clinic_metadata.json")
        return {}


class StateMachine:
    def __init__(
        self,
        config: Config | None = None,
        db_path: str | Path | None = None,
        sheets_client: SheetsClient | None = None,
        calendar_client: CalendarClient | None = None,
    ):
        self.config = config or get_config()
        self.db_path = str(db_path or (Path(__file__).resolve().parent.parent / "physiobot.db"))
        self.sheets = sheets_client or SheetsClient(self.config)
        self.calendar = calendar_client or CalendarClient(self.config)
        self.metadata = load_metadata()
        self._init_db()

    def _init_db(self) -> None:
        """Create sessions and messages tables if not exist, and add columns if not present."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    phone       TEXT PRIMARY KEY,
                    state       TEXT NOT NULL DEFAULT 'active',
                    updated_at  REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone   TEXT NOT NULL,
                    role    TEXT NOT NULL,
                    content TEXT NOT NULL,
                    ts      REAL NOT NULL
                );
                """
            )
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(sessions)")
            columns = [row[1] for row in cursor.fetchall()]
            if "status" not in columns:
                conn.execute("ALTER TABLE sessions ADD COLUMN status TEXT NOT NULL DEFAULT 'START'")
            if "slots_json" not in columns:
                conn.execute("ALTER TABLE sessions ADD COLUMN slots_json TEXT NOT NULL DEFAULT '{}'")

    def get_session(self, phone: str) -> tuple[str, dict]:
        """Fetch session status and slots dict from SQLite."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT status, slots_json FROM sessions WHERE phone = ?", (phone,)
            ).fetchone()
            if row:
                status = row["status"]
                slots = json.loads(row["slots_json"] or "{}")
                return status, slots
            return "START", {}

    def save_session(self, phone: str, status: str, slots: dict) -> None:
        """Upsert session status and slots dict into SQLite."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO sessions (phone, status, slots_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(phone) DO UPDATE SET 
                    status=excluded.status, 
                    slots_json=excluded.slots_json, 
                    updated_at=excluded.updated_at
                """,
                (phone, status, json.dumps(slots), time.time()),
            )

    def process_turn(
        self,
        phone: str,
        intent: str,
        parsed_slots: dict,
        red_flags_detected: list[str],
    ) -> tuple[str, dict]:
        """Process one conversational turn.
        Updates accumulated slots, checks triage criteria, runs integration actions,
        and determines the next template key and template parameters to send.
        Returns:
            (template_key, template_parameters_dict)
        """
        status, slots = self.get_session(phone)
        clinic_name = self.metadata.get("business_context", {}).get("clinic_display_name") or self.config.clinic.name
        clinic_phone = self.metadata.get("hsr_branch", {}).get("contact", {}).get("primary_phone") or self.config.clinic.contact_number

        # Check for session inactivity timeout (e.g. 4 hours = 14400 seconds)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT updated_at FROM sessions WHERE phone = ?", (phone,)).fetchone()
            last_active = row[0] if row else None
        
        if last_active and (time.time() - last_active > 14400):
            slots = {}
            status = "START"
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM messages WHERE phone = ?", (phone,))

        # Fetch the latest user message text to check for keywords/intents
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT content FROM messages WHERE phone = ? AND role = 'user' ORDER BY id DESC LIMIT 1", (phone,)
            ).fetchone()
            user_msg = row[0] if row else ""
        lower_msg = user_msg.lower().strip()

        # Handle explicit restart request
        if "restart" in lower_msg or "start over" in lower_msg:
            slots = {}
            self.save_session(phone, "COLLECTING_INTAKE", slots)
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM messages WHERE phone = ?", (phone,))
            return "welcome_greeting", {"clinic_name": clinic_name}

        # Reset session slots on new flow start to avoid carrying over old bookings
        if intent in ["greeting", "book_appointment"] and status in ["CONFIRMED", "HUMAN_HANDOFF"]:
            slots = {}
            status = "COLLECTING_INTAKE"
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM messages WHERE phone = ?", (phone,))

        # Handle rescheduling requests by clearing slots and prompting for new date
        if status in ["AWAITING_SLOT_SELECTION", "CONFIRMED"] and (
            intent == "reschedule_appointment" 
            or "another slot" in lower_msg 
            or "reschedule" in lower_msg 
            or "other slot" in lower_msg
        ):
            slots["preferred_date"] = None
            slots["preferred_time"] = None
            self.save_session(phone, "AWAITING_SLOT_SELECTION", slots)
            return "request_date_time", {}

        # Merge parsed slots into session storage (ignore null/empty strings)
        for k, v in parsed_slots.items():
            if v is not None and v != "":
                slots[k] = v

        # 1. Urgent Triage & Red Flags
        safety_cfg = self.metadata.get("medical_safety_and_red_flags") or self.metadata.get("triage_and_safety") or {}
        red_flag_response = safety_cfg.get(
            "red_flag_response"
        ) or safety_cfg.get(
            "red_flag_bot_response",
            "Your symptoms may need urgent medical attention. Please visit the nearest hospital.",
        )
        if red_flags_detected or intent == "emergency_or_red_flag":
            self.save_session(phone, "HUMAN_HANDOFF", slots)
            return "red_flag_alert", {"red_flag_bot_response": red_flag_response}

        # 2. Human Handoff Intents
        handoff_intents = [
            "cancel_appointment",
            "insurance_query",
            "payment_query",
            "medical_report_query"
        ]
        if (
            intent in handoff_intents
            or intent == "cancel_appointment"
        ):
            self.save_session(phone, "HUMAN_HANDOFF", slots)
            return "human_handoff", {"clinic_phone": clinic_phone}

        # 3. FAQ Intents (stay in current state, just respond)
        faqs = self.metadata.get("faq_for_bot") or self.metadata.get("faqs") or []
        faq_intent_keywords = {
            "ask_price": ["price", "fee", "cost", "charge"],
            "ask_services": ["treat", "problems", "services", "specialty"],
            "ask_location": ["branch", "hsr", "where", "location", "address"],
            "ask_timings": ["timing", "hour", "open", "time"],
            "ask_home_visit": ["home visit", "home care", "at-home"],
            "ask_online_consultation": ["virtual", "online", "tele"],
            "ask_therapist_details": ["therapist", "doctor", "physiotherapist", "team"],
        }
        if intent in faq_intent_keywords or intent == "faq_query":
            keywords = faq_intent_keywords.get(intent, ["physiotherapy"])
            matched_faq = None
            for faq in faqs:
                if any(kw in faq["question"].lower() or kw in faq["answer"].lower() for kw in keywords):
                    matched_faq = faq
                    break

            if matched_faq:
                return "faq_response", {
                    "question": matched_faq["question"],
                    "answer": matched_faq["answer"],
                }
            # Fall through if no matching FAQ was found to let the normal conversation flow reply

        # 4. State Transitions
        if status == "START":
            if intent == "greeting":
                self.save_session(phone, "COLLECTING_INTAKE", slots)
                return "welcome_greeting", {"clinic_name": clinic_name}
            # Fallback to intake if not a greeting
            status = "COLLECTING_INTAKE"

        if status == "COLLECTING_INTAKE":
            # If name, phone, complaint are populated, write to Sheets (once)
            name = slots.get("full_name")
            phone_num = slots.get("phone_number")
            complaint = slots.get("main_problem")
            if name and phone_num and complaint and not slots.get("patient_saved"):
                try:
                    self.sheets.save_patient_info(name, phone_num, complaint)
                    slots["patient_saved"] = True
                except Exception:
                    log.exception("failed to save patient info to sheets")

            # Guide slot-filling sequentially
            if not name or not phone_num:
                self.save_session(phone, "COLLECTING_INTAKE", slots)
                return "request_name_phone", {}
            if not complaint:
                self.save_session(phone, "COLLECTING_INTAKE", slots)
                return "request_complaint", {"name": name}
            if not slots.get("pain_area"):
                self.save_session(phone, "COLLECTING_INTAKE", slots)
                return "request_pain_area", {}
            if not slots.get("pain_duration"):
                self.save_session(phone, "COLLECTING_INTAKE", slots)
                return "request_pain_duration", {}
            if not slots.get("pain_score"):
                self.save_session(phone, "COLLECTING_INTAKE", slots)
                return "request_pain_score", {}
            if not slots.get("preferred_service_mode"):
                self.save_session(phone, "COLLECTING_INTAKE", slots)
                return "request_service_mode", {}

            # All intake complete! Advance to date/time booking
            status = "AWAITING_SLOT_SELECTION"

        if status == "AWAITING_SLOT_SELECTION":
            pref_date = slots.get("preferred_date")
            pref_time = slots.get("preferred_time")

            if not pref_date:
                self.save_session(phone, "AWAITING_SLOT_SELECTION", slots)
                return "request_date_time", {}

            # Date provided, show slots if time is not chosen yet
            if not pref_time:
                try:
                    free_slots = self.calendar.get_free_slots(pref_date)
                    if not free_slots:
                        # Clear date so they pick another date next turn
                        slots["preferred_date"] = None
                        self.save_session(phone, "AWAITING_SLOT_SELECTION", slots)
                        return "generic_fallback", {
                            "clinic_phone": f"No available slots on {pref_date}. Please try another date or contact {clinic_phone}."
                        }
                    slots_list_str = "\n".join(f"- {s}" for s in free_slots)
                    self.save_session(phone, "AWAITING_SLOT_SELECTION", slots)
                    return "show_slots", {"date": pref_date, "slots_list": slots_list_str, "raw_slots": free_slots}
                except Exception:
                    log.exception("failed to retrieve slots")
                    return "generic_fallback", {"clinic_phone": clinic_phone}

            # Date and time both present — execute booking!
            try:
                name = slots["full_name"]
                phone_num = slots["phone_number"]
                complaint = slots["main_problem"]
                dt_str = f"{pref_date}T{pref_time}"

                if self.sheets.booking_exists(phone_num, dt_str):
                    self.save_session(phone, "CONFIRMED", slots)
                    return "booking_confirmed", {"date_time": dt_str}

                ev = self.calendar.create_event(name, phone_num, complaint, dt_str)
                self.sheets.append_booking(
                    name, phone_num, complaint, dt_str, ev["event_id"]
                )
                self.save_session(phone, "CONFIRMED", slots)
                return "booking_confirmed", {"date_time": dt_str}
            except Exception:
                log.exception("failed to create booking event")
                # Clear time slot so they can retry selecting a slot
                slots["preferred_time"] = None
                self.save_session(phone, "AWAITING_SLOT_SELECTION", slots)
                return "generic_fallback", {
                    "clinic_phone": f"Booking failed. Please try a different slot or call {clinic_phone}."
                }

        if status == "CONFIRMED":
            if intent == "greeting":
                # Start new intake session
                self.save_session(phone, "COLLECTING_INTAKE", {})
                return "welcome_greeting", {"clinic_name": clinic_name}
            return "generic_fallback", {"clinic_phone": clinic_phone}

        return "generic_fallback", {"clinic_phone": clinic_phone}
