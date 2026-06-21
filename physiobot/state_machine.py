"""Deterministic state machine for managing conversation steps, slot filling, and integrations.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import sqlite3
import time
from pathlib import Path
from zoneinfo import ZoneInfo

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
    "ask_contact": "phone_email",
    "ask_timings": "unknown_hours",
    "ask_home_visit": "home_visit",
    "ask_online_consultation": "virtual_consultation",
    "ask_therapist_details": "specific_therapist_request",
}

# Words that suggest the patient actually wants a brand new booking, used as a
# safety net alongside the "book_appointment" intent before wiping a
# confirmed/handed-off session — see the reset block in process_turn. An NLU
# intent label alone isn't trustworthy enough for a destructive action: a
# compound question like "what's the location and contact?" has been
# misclassified as "book_appointment" before, which used to silently erase the
# patient's confirmed appointment and reopen name confirmation out of nowhere.
NEW_BOOKING_KEYWORDS = ["book", "appointment", "schedule", "another visit", "new visit", "rebook"]

# Hour ranges [start, end) for narrowing the slot list when a patient asks for a
# rough time of day ("tomorrow morning") instead of an exact time.
TIME_OF_DAY_RANGES = {
    "morning": (0, 12),
    "afternoon": (12, 17),
    "evening": (17, 24),
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
            if not slots.get("preferred_branch"):
                if slots.get("last_branch_id_detected") and not slots.get("returning_branch_confirmed"):
                    return "returning_branch_confirmed"
                return "preferred_branch"
        elif status == "AWAITING_SLOT_SELECTION":
            if slots.get("preferred_date") and not slots.get("preferred_time"):
                return "preferred_time"
        return None

    @staticmethod
    def _filter_slots_by_time_of_day(free_slots: list[str], time_of_day: str | None) -> list[str]:
        """Strictly narrow HH:MM slots to a time-of-day window. Returns the input
        unchanged if no/unknown window, but an EMPTY list if nothing falls in the
        window — the caller (forward search) needs to know a window is unavailable
        so it can roll forward rather than silently show unrelated times."""
        rng = TIME_OF_DAY_RANGES.get(time_of_day or "")
        if not rng:
            return free_slots
        lo, hi = rng
        narrowed = []
        for s in free_slots:
            try:
                hour = int(s.split(":")[0])
            except (ValueError, IndexError, AttributeError):
                continue
            if lo <= hour < hi:
                narrowed.append(s)
        return narrowed

    def _find_next_availability(self, start_date_iso: str, time_of_day: str | None, max_days: int = 14):
        """Search forward from start_date for real availability, acting like a
        receptionist scanning the diary. Returns (date_iso, slots, honored_window):
        - First pass prefers the requested time-of-day window, rolling day by day.
        - Second pass (or when no window was requested) returns the first day with
          any free slots.
        honored_window is True when the returned slots actually match what was
        asked (so the caller knows whether to apologise for rolling forward).
        Returns (None, [], False) if nothing is open within max_days."""
        try:
            start = dt.date.fromisoformat(start_date_iso)
        except (ValueError, TypeError):
            return None, [], False

        cache: dict[int, tuple[str, list[str]]] = {}

        def day_slots(offset: int) -> tuple[str, list[str]]:
            if offset not in cache:
                d = (start + dt.timedelta(days=offset)).isoformat()
                cache[offset] = (d, self.calendar.get_free_slots(d))
            return cache[offset]

        if time_of_day:
            for offset in range(max_days):
                d, free = day_slots(offset)
                windowed = self._filter_slots_by_time_of_day(free, time_of_day)
                if windowed:
                    return d, windowed, True

        for offset in range(max_days):
            d, free = day_slots(offset)
            if free:
                return d, free, (time_of_day is None)

        return None, [], False

    def _describe_window(self, date_iso: str, time_of_day: str | None) -> str:
        """Human label for a requested slot window, e.g. "Today evening",
        "Tomorrow morning", "Monday" — used when telling the patient that what
        they asked for is fully booked."""
        today = dt.datetime.now(ZoneInfo(self.config.clinic.timezone)).date()
        try:
            d = dt.date.fromisoformat(date_iso)
        except (ValueError, TypeError):
            return "That time"
        if d == today:
            day = "today"
        elif d == today + dt.timedelta(days=1):
            day = "tomorrow"
        else:
            day = d.strftime("%A")
        phrase = f"{day} {time_of_day}" if time_of_day else day
        return phrase[0].upper() + phrase[1:]

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
        clinic_address = self.kb.clinic_address

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
        # one. Gated to an explicit "book_appointment" intent AND an actual
        # booking-shaped word in the message itself — a bare "hi"/"thank you"
        # is just continuing the chat, not a request to wipe the existing
        # appointment. The keyword check is a deliberate belt-and-braces on
        # top of the NLU intent: a compound info question like "what's the
        # location and contact?" has been seen misclassified as
        # "book_appointment" by the LLM, which used to silently erase the
        # confirmed appointment and reopen name confirmation out of nowhere.
        if (
            intent == "book_appointment"
            and status in ["CONFIRMED", "HUMAN_HANDOFF"]
            and any(kw in lower_msg for kw in NEW_BOOKING_KEYWORDS)
        ):
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
            if k in ("preferred_date", "preferred_time", "preferred_time_of_day") and status != "AWAITING_SLOT_SELECTION":
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
        # red_flags_detected reflects only the *current* message (the parser is
        # instructed to flag the latest user turn, not re-surface historical
        # mentions — see parser.py), so a genuine urgent symptom said right now
        # always triggers the alert.
        if red_flags_detected or intent == "emergency_or_red_flag":
            slots["red_flag_handoff"] = True
            self.save_session(phone, "HUMAN_HANDOFF", slots)
            return "red_flag_alert", {"red_flag_bot_response": self.kb.red_flag_message}

        # A red-flag handoff isn't a dead end for everything else the patient
        # says. Once the urgent symptom isn't being restated (this turn carries
        # no red flag), the rest of what they came in for — e.g. lower back
        # pain alongside the chest pain — is something physiotherapy can
        # actually help with. So resume intake for it instead of repeating the
        # same urgent-care alert forever, while reminding them once that the
        # urgent symptom still needs separate medical attention.
        resumed_after_red_flag = False
        if status == "HUMAN_HANDOFF" and slots.get("red_flag_handoff"):
            slots["red_flag_handoff"] = False
            status = "COLLECTING_INTAKE"
            resumed_after_red_flag = True

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
                self.save_session(phone, status, slots)
                if intent == "ask_location":
                    # Location and "how do I reach you" are almost always
                    # asked together in practice, but the NLU can only return
                    # one intent for a question — so the location answer
                    # always includes the phone number too.
                    contact = self.kb.response_template("phone_email")
                    if contact:
                        answer = f"{answer} {contact}"
                    if self.kb.maps_url:
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

            if resumed_after_red_flag:
                # Don't let resuming read as "never mind about the chest
                # pain" — repeat the reminder once, then carry on with what
                # the clinic can actually help with.
                hint = (
                    "Please do get that other symptom checked by a doctor separately — physiotherapy "
                    f"can't treat it. For the rest, happy to help. {hint}"
                )

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

            # Branch confirmation — never silently assume HSR Layout. A
            # returning patient is offered a one-tap "same as last time?"
            # using their most recent booking's branch (looked up from the
            # Bookings sheet); everyone else picks from the full list. This
            # must resolve before date/slot selection, since it determines
            # whether we can even check live availability (see the
            # non-HSR handoff right below).
            if not slots.get("preferred_branch"):
                if not slots.get("branch_lookup_done"):
                    try:
                        slots["last_branch_id_detected"] = self.sheets.last_branch_for_phone(phone_num) or ""
                    except Exception:
                        log.exception("failed to look up last booked branch for phone")
                        slots["last_branch_id_detected"] = ""
                    slots["branch_lookup_done"] = True

                last_branch_id = slots.get("last_branch_id_detected")
                returning_branch_confirmed = slots.get("returning_branch_confirmed")

                if returning_branch_confirmed == "yes" and last_branch_id:
                    slots["preferred_branch"] = last_branch_id
                elif last_branch_id and not returning_branch_confirmed:
                    self.save_session(phone, "COLLECTING_INTAKE", slots)
                    branch = self.kb.branch_by_id(last_branch_id)
                    return "confirm_returning_branch", {"branch_name": branch.short_name if branch else "previous"}
                else:
                    self.save_session(phone, "COLLECTING_INTAKE", slots)
                    raw_branches = [
                        {"id": b.branch_id, "name": b.short_name, "address": b.address} for b in self.kb.branches()
                    ]
                    return "request_branch", {"raw_branches": raw_branches}

            # Live calendar/sheet access only exists for the primary (HSR
            # Layout) branch — for any other branch a human confirms the slot
            # directly, rather than the bot guessing at availability it can't
            # actually see.
            branch_id = slots.get("preferred_branch")
            if branch_id != self.kb.primary_branch_id and not slots.get("non_primary_branch_handled"):
                slots["non_primary_branch_handled"] = True
                branch = self.kb.branch_by_id(branch_id)
                self.save_session(phone, "HUMAN_HANDOFF", slots)
                return "non_hsr_branch_handoff", {
                    "branch_name": branch.short_name if branch else "that branch",
                    "branch_phone": branch.phone if branch else clinic_phone,
                }

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
                    tod = slots.get("preferred_time_of_day")
                    # Scan forward like a receptionist: prefer the asked-for
                    # day/time-of-day, but roll to the next real availability if
                    # it's fully booked instead of silently showing odd times.
                    found_date, found_slots, honored = self._find_next_availability(pref_date, tod)
                    if not found_date:
                        slots["preferred_date"] = None
                        self.save_session(phone, "AWAITING_SLOT_SELECTION", slots)
                        return "no_slots_available", {"date": humanize_date(pref_date), "clinic_phone": clinic_phone}

                    # Apologise + signpost only when we couldn't honour the exact
                    # request (different day, or the requested window was full).
                    note = ""
                    if found_date != pref_date or not honored:
                        note = f"{self._describe_window(pref_date, tod)} is fully booked — here's the next availability:\n\n"

                    # Book against what we actually showed.
                    slots["preferred_date"] = found_date
                    slots_list_str = "\n".join(f"- {s}" for s in found_slots)
                    self.save_session(phone, "AWAITING_SLOT_SELECTION", slots)
                    return "show_slots", {
                        "date": humanize_date(found_date), "slots_list": slots_list_str,
                        "raw_slots": found_slots, "note": note,
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

                # Confirmation copy + a tappable "View on Map" button when we
                # have a maps link (always the case for the HSR branch). Falls
                # back to plain text if no link is available.
                confirm_params = {
                    "date_time": display_dt, "clinic_address": clinic_address, "clinic_phone": clinic_phone,
                }
                if self.kb.maps_url:
                    confirm_params["maps_url"] = self.kb.maps_url
                    confirm_template = "booking_confirmed_map"
                else:
                    confirm_template = "booking_confirmed"

                if self.sheets.booking_exists(phone_num, dt_str):
                    self.save_session(phone, "CONFIRMED", slots)
                    return confirm_template, confirm_params

                ev = self.calendar.create_event(name, phone_num, complaint, dt_str)
                self.sheets.append_booking(
                    name, phone_num, complaint, dt_str, ev["event_id"], slots.get("preferred_branch", "")
                )
                self.save_session(phone, "CONFIRMED", slots)
                return confirm_template, confirm_params
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
            return "post_booking_chat", {
                "date_time": display_dt, "clinic_address": clinic_address, "clinic_phone": clinic_phone,
            }

        return "generic_fallback", {"clinic_phone": clinic_phone}
