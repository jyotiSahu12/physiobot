"""Deterministic state machine for managing conversation steps, slot filling, and integrations.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path

from .clinic_kb import ClinicKB
from .config import Config, get_config
from .formatting import humanize_date, humanize_datetime
from .tools.calendar import CalendarClient
from .tools.sheets import SheetsClient

log = logging.getLogger("physiobot.state_machine")

# intent -> customer_facing_response_templates key. These are answerable inline
# from clinic-approved canned copy without breaking off the booking flow.
FAQ_RESPONSE_TEMPLATE_KEYS = {
    "ask_price": "unknown_price",
    "ask_services": "service_summary",
    "ask_location": "hsr_address",
    "ask_timings": "unknown_hours",
    "ask_home_visit": "home_visit",
    "ask_online_consultation": "virtual_consultation",
    "ask_therapist_details": "specific_therapist_request",
}

# Intents that require a human to take over entirely (the bot has no
# clinic-approved way to resolve these itself).
HANDOFF_INTENTS = [
    "cancel_appointment",
    "insurance_query",
    "payment_query",
    "medical_report_query",
]


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
        self.kb = ClinicKB()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        # Re-create the schema on every connection (cheap: CREATE TABLE IF NOT
        # EXISTS / column-exists checks), not just once at construction. This
        # object is a long-lived singleton in app.py — if the db file is ever
        # deleted or replaced out from under a running process, the next query
        # would otherwise crash with "no such table" instead of self-healing.
        conn = sqlite3.connect(self.db_path)
        self._init_db(conn)
        return conn

    def _init_db(self, conn: sqlite3.Connection | None = None) -> None:
        """Create sessions and messages tables if not exist, and add columns if not present."""
        own_conn = conn is None
        if own_conn:
            conn = sqlite3.connect(self.db_path)
        try:
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
            conn.commit()
        finally:
            if own_conn:
                conn.close()

    def get_session(self, phone: str) -> tuple[str, dict]:
        """Fetch session status and slots dict from SQLite."""
        with self._connect() as conn:
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
        with self._connect() as conn:
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

    def _service_recommendation_hint(self, slots: dict) -> str:
        """Match the patient's stated complaint against clinic_metadata.json's
        service_recommendation_logic and surface a relevant service suggestion
        before asking the generic pain-area question."""
        match = self.kb.match_service(slots.get("main_problem") or "")
        if not match:
            return ""
        return f"Based on what you shared, our {match.service_name} would be a good fit. "

    def _current_expected_slot(self, status: str, slots: dict) -> str | None:
        """Mirror the sequential slot-filling order below, so a button/list reply
        (whose id is unambiguous) can be assigned to exactly the slot the bot just
        asked about — instead of being re-parsed by the NLU layer, which has
        misread free text like "1-3 days" as a pain score when read out of context.
        Returns None for slots that are always answered as free text (name, complaint,
        typed date), since those never arrive as a button/list reply."""
        if status == "COLLECTING_INTAKE":
            if not slots.get("full_name"):
                if slots.get("profile_name_detected") and not slots.get("details_confirmed"):
                    return "details_confirmed"
                return None
            if not slots.get("consent_given"):
                return "consent_given"
            if not slots.get("main_problem"):
                return None
            if not slots.get("pain_area"):
                return "pain_area"
            if not slots.get("pain_duration"):
                return "pain_duration"
            if not slots.get("pain_score"):
                return "pain_score"
            if not slots.get("preferred_service_mode"):
                return "preferred_service_mode"
        elif status == "AWAITING_SLOT_SELECTION":
            if slots.get("preferred_date") and not slots.get("preferred_time"):
                return "preferred_time"
        return None

    @staticmethod
    def _coerce_interactive_value(slot: str, value: str):
        if slot == "pain_score":
            try:
                return int(value)
            except (TypeError, ValueError):
                return value
        return value

    def process_turn(
        self,
        phone: str,
        intent: str,
        parsed_slots: dict,
        red_flags_detected: list[str],
        interactive_id: str | None = None,
        profile_name: str | None = None,
    ) -> tuple[str, dict]:
        """Process one conversational turn.
        Updates accumulated slots, checks triage criteria, runs integration actions,
        and determines the next template key and template parameters to send.
        Returns:
            (template_key, template_parameters_dict)
        """
        status, slots = self.get_session(phone)
        clinic_name = self.kb.clinic_name or self.config.clinic.name
        clinic_phone = self.kb.clinic_phone or self.config.clinic.contact_number

        # Check for session inactivity timeout (e.g. 4 hours = 14400 seconds)
        with self._connect() as conn:
            row = conn.execute("SELECT updated_at FROM sessions WHERE phone = ?", (phone,)).fetchone()
            last_active = row[0] if row else None
        
        if last_active and (time.time() - last_active > 14400):
            slots = {}
            status = "START"
            with self._connect() as conn:
                conn.execute("DELETE FROM messages WHERE phone = ?", (phone,))

        # Fetch the latest user message text to check for keywords/intents
        with self._connect() as conn:
            row = conn.execute(
                "SELECT content FROM messages WHERE phone = ? AND role = 'user' ORDER BY id DESC LIMIT 1", (phone,)
            ).fetchone()
            user_msg = row[0] if row else ""
        lower_msg = user_msg.lower().strip()

        # Handle explicit restart request
        if "restart" in lower_msg or "start over" in lower_msg:
            slots = {}
            self.save_session(phone, "COLLECTING_INTAKE", slots)
            with self._connect() as conn:
                conn.execute("DELETE FROM messages WHERE phone = ?", (phone,))
            return "welcome_greeting", {"clinic_name": clinic_name}

        # Reset session slots to start a fresh booking after a confirmed/handed-off
        # one. Gated to an explicit "book_appointment" intent only — a bare
        # "hi" or "thank you" after booking is just continuing the chat, not a
        # request to wipe the existing appointment and restart intake from
        # scratch (that misfire is exactly why "thank you" used to reopen the
        # name-confirmation prompt out of nowhere).
        if intent == "book_appointment" and status in ["CONFIRMED", "HUMAN_HANDOFF"]:
            slots = {}
            status = "COLLECTING_INTAKE"
            with self._connect() as conn:
                conn.execute("DELETE FROM messages WHERE phone = ?", (phone,))

        # Handle rescheduling requests by clearing slots and prompting for new date
        if status in ["AWAITING_SLOT_SELECTION", "CONFIRMED"] and (
            intent == "reschedule_appointment"
            or "another slot" in lower_msg
            or "reschedule" in lower_msg
            or "other slot" in lower_msg
            or "different date" in lower_msg
            or "change the date" in lower_msg
            or "change date" in lower_msg
            or "another date" in lower_msg
        ):
            slots["preferred_date"] = None
            slots["preferred_time"] = None
            self.save_session(phone, "AWAITING_SLOT_SELECTION", slots)
            return "request_date_time", {}

        # Merge parsed slots into session storage (ignore null/empty strings).
        # phone_number is excluded: it's always set from the WhatsApp sender id
        # below, and must never be silently overwritten by an NLU guess (e.g. a
        # stray 10-digit number mentioned elsewhere in the conversation).
        # preferred_date/preferred_time are further gated to only merge once the
        # bot has actually reached the date-picking phase (AWAITING_SLOT_SELECTION)
        # — otherwise a chatty LLM can "helpfully" invent a date (e.g. defaulting
        # to tomorrow) on a turn where nothing about scheduling was even said,
        # and the bot ends up booking a day the patient never asked for.
        for k, v in parsed_slots.items():
            if k == "phone_number":
                continue
            if k in ("preferred_date", "preferred_time") and status != "AWAITING_SLOT_SELECTION":
                continue
            if v is not None and v != "":
                slots[k] = v

        # Button/list replies carry an unambiguous option id — assign it straight
        # to whichever slot the bot is currently waiting on rather than letting the
        # NLU layer re-interpret the title text out of context.
        if interactive_id is not None:
            target_slot = self._current_expected_slot(status, slots)
            if target_slot:
                slots[target_slot] = self._coerce_interactive_value(target_slot, interactive_id)

        # The WhatsApp sender's number is always known and reliable — never ask
        # the patient to type it. If Meta included their profile name, remember it
        # so we can offer it for confirmation instead of asking from scratch.
        slots.setdefault("phone_number", phone)
        if profile_name:
            slots["profile_name_detected"] = profile_name

        # 1. Urgent Triage & Red Flags
        if red_flags_detected or intent == "emergency_or_red_flag":
            self.save_session(phone, "HUMAN_HANDOFF", slots)
            return "red_flag_alert", {"red_flag_bot_response": self.kb.red_flag_message}

        # 2. Human Handoff Intents — the bot has no clinic-approved way to
        # resolve these itself (see HANDOFF_INTENTS above).
        if intent in HANDOFF_INTENTS:
            self.save_session(phone, "HUMAN_HANDOFF", slots)
            return "human_handoff", {"clinic_phone": clinic_phone}

        # 3. FAQ Intents (stay in current state, just respond with clinic-approved
        # canned copy from customer_facing_response_templates — see FAQ_RESPONSE_TEMPLATE_KEYS)
        faq_key = FAQ_RESPONSE_TEMPLATE_KEYS.get(intent)
        if faq_key:
            answer = self.kb.response_template(faq_key)
            if answer:
                if intent == "ask_location" and self.kb.maps_url:
                    return "location_with_map", {"answer": answer, "maps_url": self.kb.maps_url}
                return "faq_response", {"answer": answer}
            # No canned copy configured for this — fall through to normal flow

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

            # Guide slot-filling sequentially.
            # The phone number is always known (slots.setdefault above), so the only
            # thing left to resolve here is the name: offer the WhatsApp profile name
            # for a one-tap confirmation when we have it, otherwise ask directly.
            if not name:
                details_confirmed = slots.get("details_confirmed")
                detected_name = slots.get("profile_name_detected")
                if details_confirmed == "yes" and detected_name:
                    slots["full_name"] = detected_name
                    name = detected_name
                elif details_confirmed == "no" or not detected_name:
                    self.save_session(phone, "COLLECTING_INTAKE", slots)
                    return "request_full_name", {}
                else:
                    self.save_session(phone, "COLLECTING_INTAKE", slots)
                    return "confirm_details", {
                        "detected_name": detected_name,
                        "detected_phone": phone_num,
                    }

            # privacy_and_consent.required_bot_consents requires explicit agreement
            # before the bot collects symptom details.
            consent = slots.get("consent_given")
            if consent == "no":
                self.save_session(phone, "HUMAN_HANDOFF", slots)
                return "consent_declined", {"clinic_phone": clinic_phone}
            if not consent:
                self.save_session(phone, "COLLECTING_INTAKE", slots)
                return "request_consent", {}

            if not complaint:
                self.save_session(phone, "COLLECTING_INTAKE", slots)
                return "request_complaint", {"name": name}

            # Surface the service recommendation once, attached to whichever slot
            # question goes out next — pain_area is often filled in the same turn
            # as the complaint (the LLM extracts both at once), so the hint can't
            # be tied to the request_pain_area step alone or it'd never be shown.
            hint = ""
            if not slots.get("service_hint_shown"):
                hint = self._service_recommendation_hint(slots)
                if hint:
                    slots["service_hint_shown"] = True

            if not slots.get("pain_area"):
                self.save_session(phone, "COLLECTING_INTAKE", slots)
                return "request_pain_area", {"service_hint": hint}
            if not slots.get("pain_duration"):
                self.save_session(phone, "COLLECTING_INTAKE", slots)
                return "request_pain_duration", {"service_hint": hint}
            if not slots.get("pain_score"):
                self.save_session(phone, "COLLECTING_INTAKE", slots)
                return "request_pain_score", {"service_hint": hint}
            if not slots.get("preferred_service_mode"):
                self.save_session(phone, "COLLECTING_INTAKE", slots)
                return "request_service_mode", {"service_hint": hint}

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
                        return "no_slots_available", {"date": humanize_date(pref_date), "clinic_phone": clinic_phone}
                    slots_list_str = "\n".join(f"- {s}" for s in free_slots)
                    self.save_session(phone, "AWAITING_SLOT_SELECTION", slots)
                    return "show_slots", {
                        "date": humanize_date(pref_date), "slots_list": slots_list_str, "raw_slots": free_slots,
                    }
                except Exception:
                    log.exception("failed to retrieve slots")
                    return "generic_fallback", {"clinic_phone": clinic_phone}

            # Date and time both present — execute booking!
            try:
                name = slots["full_name"]
                phone_num = slots["phone_number"]
                complaint = slots["main_problem"]
                # The internal id used for calendar/sheets stays a plain ISO
                # string; only the copy shown to the patient is humanized.
                dt_str = f"{pref_date}T{pref_time}"
                display_dt = humanize_datetime(pref_date, pref_time)

                if self.sheets.booking_exists(phone_num, dt_str):
                    self.save_session(phone, "CONFIRMED", slots)
                    return "booking_confirmed", {"date_time": display_dt}

                ev = self.calendar.create_event(name, phone_num, complaint, dt_str)
                self.sheets.append_booking(
                    name, phone_num, complaint, dt_str, ev["event_id"]
                )
                self.save_session(phone, "CONFIRMED", slots)
                return "booking_confirmed", {"date_time": display_dt}
            except Exception:
                log.exception("failed to create booking event")
                # Clear time slot so they can retry selecting a slot
                slots["preferred_time"] = None
                self.save_session(phone, "AWAITING_SLOT_SELECTION", slots)
                return "booking_failed", {"clinic_phone": clinic_phone}

        if status == "CONFIRMED":
            # A bare "hi" or "thank you" here is just continuing the chat, not
            # a request for a new booking (that's handled above, gated to an
            # explicit "book_appointment" intent) — so reassure them their
            # existing appointment still stands rather than going silent or
            # making them re-confirm their name and number from scratch.
            display_dt = humanize_datetime(slots.get("preferred_date", ""), slots.get("preferred_time", ""))
            return "post_booking_chat", {"date_time": display_dt, "clinic_phone": clinic_phone}

        return "generic_fallback", {"clinic_phone": clinic_phone}
