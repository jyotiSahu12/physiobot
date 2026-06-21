"""Structured LLM parser for NLU: Intent classification, slot filling, and red-flag detection.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
from zoneinfo import ZoneInfo

from .clinic_kb import ClinicKB
from .config import Config, get_config
from .llm import get_provider

log = logging.getLogger("physiobot.parser")

# Static phrases unique to each template's fallback text, used to infer which
# slot the bot is waiting on when the LLM is unavailable and we fall back to regex.
# Only slots with a gated extraction branch below need an entry here — pain_area,
# pain_duration, pain_score and service_mode are matched opportunistically from
# any message instead (see "2. Basic slot extraction"), and in practice they're
# answered via WhatsApp buttons/lists, which bypass this fallback entirely via
# the state machine's deterministic interactive-id assignment.
EXPECTED_SLOT_CUES = [
    ("share your full name", "full_name"),
    ("how can we help you today", "full_name"),  # the welcome greeting; name is always asked next
    ("is that correct", "details_confirmed"),
    ("do you agree that balance plus can contact you", "consent"),
    ("what main problem or pain are you facing", "complaint"),
    ("what date would you like to come in", "preferred_date"),
    ("which time works best for you", "preferred_date_or_time"),  # could be a new date instead of a time pick
]

_MONTH_ALIASES = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_WEEKDAY_ALIASES = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thurs": 3, "friday": 4, "fri": 4, "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}
_MONTH_NAME_PATTERN = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)


def parse_natural_date(text: str, today: dt.date) -> str | None:
    """Best-effort free-text date resolution for the regex NLU fallback.

    The LLM resolves dates natively via its prompt instructions; this only
    needs to cover common phrasing so a date change still works if the LLM is
    unavailable — otherwise a free-text date gets silently dropped and the bot
    keeps showing slots for the old date, looking like it's ignoring the
    patient. Returns YYYY-MM-DD or None.
    """
    text = text.lower().strip()

    iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if iso_match:
        try:
            dt.date.fromisoformat(iso_match.group(1))
            return iso_match.group(1)
        except ValueError:
            pass

    if "today" in text:
        return today.isoformat()
    if "tomorrow" in text:
        return (today + dt.timedelta(days=1)).isoformat()

    for name, weekday in _WEEKDAY_ALIASES.items():
        if re.search(rf"\b{name}\b", text):
            days_ahead = (weekday - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7  # same weekday mentioned -> the upcoming one, not literally today
            elif "next" in text:
                days_ahead += 7
            return (today + dt.timedelta(days=days_ahead)).isoformat()

    day_month_match = re.search(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_NAME_PATTERN})\b", text
    )
    month_day_match = re.search(
        rf"\b({_MONTH_NAME_PATTERN})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", text
    )
    day, month_name = None, None
    if day_month_match:
        day, month_name = int(day_month_match.group(1)), day_month_match.group(2)
    elif month_day_match:
        month_name, day = month_day_match.group(1), int(month_day_match.group(2))

    if day and month_name:
        month = _MONTH_ALIASES.get(month_name)
        if month:
            try:
                candidate = dt.date(today.year, month, day)
                if candidate < today:
                    candidate = dt.date(today.year + 1, month, day)
                return candidate.isoformat()
            except ValueError:
                return None
    return None


def parse_natural_time(text: str) -> str | None:
    """Best-effort free-text time resolution (e.g. "1pm", "13:00") for the
    regex NLU fallback, in case a patient types a time instead of tapping the
    slot list. Returns HH:MM (24h) or None."""
    match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", text.lower().strip())
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2)) if match.group(2) else 0
    meridiem = match.group(3)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    if meridiem == "pm" and hour < 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


def detect_expected_slot(history: list[dict]) -> str | None:
    """Look at the most recent assistant turn to infer which slot the bot is waiting
    on. The regex fallback parser has no other way to know conversation state, since
    unlike the LLM it doesn't read the question being answered."""
    for turn in reversed(history):
        if turn.get("role") == "assistant":
            content = (turn.get("content") or "").lower()
            for cue, slot in EXPECTED_SLOT_CUES:
                if cue in content:
                    return slot
            return None
    # No assistant turn yet: the first thing the bot ever needs is the patient's name.
    return "full_name"


def clean_json_response(content: str) -> str:
    """Extract first JSON object matching {...} from response string."""
    content = content.strip()
    match = re.search(r"(\{.*\})", content, re.DOTALL)
    if match:
        return match.group(1)
    return content


class Parser:
    def __init__(self, config: Config | None = None, provider=None):
        self.config = config or get_config()
        self.provider = provider or get_provider(self.config)
        self.kb = ClinicKB()

    def parse_message(self, history: list[dict]) -> dict:
        """Analyze conversation history and user turn to extract structured intent,
        slots, and red flags. Returns a dict matching the structured parser schema."""
        tz = ZoneInfo(self.config.clinic.timezone)
        today = dt.datetime.now(tz)
        today_str = today.strftime("%A, %Y-%m-%d")

        supported_intents = [
            "greeting",
            "book_appointment",
            "reschedule_appointment",
            "cancel_appointment",
            "ask_price",
            "ask_services",
            "ask_location",
            "ask_timings",
            "ask_home_visit",
            "ask_online_consultation",
            "ask_therapist_details",
            "insurance_query",
            "payment_query",
            "medical_report_query",
            "emergency_or_red_flag"
        ]
        
        red_flags_list = self.kb.red_flag_triggers

        pain_area_options = [
            "neck", "shoulder", "upper back", "lower back", "knee", "ankle",
            "hip", "elbow", "wrist", "hand", "general weakness", "post-surgery rehab", "sports injury"
        ]
        pain_duration_options = [
            "less than 24 hours", "1-3 days", "4-7 days", "1-4 weeks", "1-3 months", "more than 3 months"
        ]

        # phone_number is deliberately not part of the schema: it's sourced from the
        # WhatsApp sender id by the state machine, and state_machine.py ignores any
        # phone_number the NLU layer returns so it can never be silently overwritten.
        system_prompt = (
            "You are an NLU parser for a physiotherapy clinic bot. "
            "Analyze the user's latest input and the chat history to extract the intent and slot values, and detect any medical red flags.\n\n"
            "You MUST respond with a single valid JSON object and nothing else. Do not wrap the JSON in markdown code blocks. "
            "Never include any conversational preamble or explanations.\n\n"
            f"Today's date is: {today_str}.\n\n"
            "Supported Intents list:\n"
            f"{json.dumps(supported_intents)}\n\n"
            "Pain Area options (normalize to these exactly):\n"
            f"{json.dumps(pain_area_options)}\n\n"
            "Pain Duration options (normalize to these exactly):\n"
            f"{json.dumps(pain_duration_options)}\n\n"
            "Urgent medical red flags to check for:\n"
            f"{json.dumps(red_flags_list)}\n\n"
            "Expected JSON Output Schema:\n"
            "{\n"
            '  "intent": "one_of_supported_intents_or_greeting_or_other",\n'
            '  "slots": {\n'
            '    "full_name": "string_or_null",\n'
            '    "main_problem": "string_or_null",\n'
            '    "pain_area": "one_of_pain_area_options_or_null",\n'
            '    "pain_duration": "one_of_pain_duration_options_or_null",\n'
            '    "pain_score": "integer_0_to_10_or_null",\n'
            '    "preferred_service_mode": "clinic_visit" | "home_visit" | "tele_consultation" | null,\n'
            '    "preferred_date": "YYYY-MM-DD_or_null", // Resolve relative dates like tomorrow/Monday using today\'s date\n'
            '    "preferred_time": "HH:MM_or_null",\n'
            '    "consent_given": "yes" | "no" | null, // whether the patient agreed to be contacted and to share symptom details\n'
            '    "details_confirmed": "yes" | "no" | null // whether the patient confirmed their detected WhatsApp name and number are correct\n'
            "  },\n"
            '  "red_flags_detected": [] // List of red flag keywords/phrases from the urgent list if matched in user inputs\n'
            "}"
        )

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)

        try:
            assistant_msg = self.provider.chat(messages)
            raw_content = assistant_msg.get("content") or ""
            cleaned = clean_json_response(raw_content)
            parsed = json.loads(cleaned)
            # Ensure keys exist
            if "intent" not in parsed:
                parsed["intent"] = "other"
            if "slots" not in parsed or not isinstance(parsed["slots"], dict):
                parsed["slots"] = {}
            if "red_flags_detected" not in parsed or not isinstance(parsed["red_flags_detected"], list):
                parsed["red_flags_detected"] = []
            return parsed
        except Exception:
            log.exception("failed to parse LLM response")
            # Fallback NLU rules when LLM fails or is empty
            user_msg = history[-1]["content"] if history else ""
            lower_msg = user_msg.lower().strip()
            expected_slot = detect_expected_slot(history[:-1])

            intent = "other"
            slots = {}
            red_flags_detected = []

            # 1. Intent matching
            if any(greet in lower_msg for greet in ["hello", "hi", "hey", "hola", "namaste", "morning", "evening"]):
                intent = "greeting"
            elif any(word in lower_msg for word in ["book", "appointment", "schedule", "visit", "consult"]):
                intent = "book_appointment"
            elif "cancel" in lower_msg:
                intent = "cancel_appointment"
            elif "reschedule" in lower_msg:
                intent = "reschedule_appointment"
            elif any(p in lower_msg for p in ["price", "cost", "fee", "charge", "package", "rate"]):
                intent = "ask_price"
            elif any(l in lower_msg for l in ["where", "address", "branch", "location", "clinic at"]):
                intent = "ask_location"
            elif any(t in lower_msg for t in ["timings", "opening hours", "open hours", "what time do you open"]):
                intent = "ask_timings"
            elif any(ins in lower_msg for ins in ["insurance", "reimbursement", "claim", "coverage"]):
                intent = "insurance_query"
            elif any(pay in lower_msg for pay in ["payment", "pay", "upi", "cash", "card", "refund", "invoice"]):
                intent = "payment_query"
            elif any(rep in lower_msg for rep in ["report", "prescription", "scan", "mri", "xray", "x-ray"]):
                intent = "medical_report_query"

            # 2. Basic slot extraction
            # phone_number is never extracted here: the WhatsApp sender id is the
            # source of truth (set by the state machine) and must not be overwritten
            # by a stray digit sequence elsewhere in the message.
            # Still detect a phone-number-shaped run of digits so it can be stripped
            # out before guessing a name from the remaining words below.
            phone_match = re.search(r"(\+?\d{10,12})", user_msg)

            # Consent yes/no (only when the bot just asked for it)
            if expected_slot == "consent":
                if re.search(r"\b(yes|agree|ok|okay|sure)\b", lower_msg):
                    slots["consent_given"] = "yes"
                elif re.search(r"\b(no|disagree|don'?t agree)\b", lower_msg):
                    slots["consent_given"] = "no"

            # Confirming the WhatsApp-detected name + number (only when just asked)
            if expected_slot == "details_confirmed":
                if re.search(r"\b(yes|correct|right|yep|yeah)\b", lower_msg):
                    slots["details_confirmed"] = "yes"
                elif re.search(r"\b(no|wrong|incorrect|nope)\b", lower_msg):
                    slots["details_confirmed"] = "no"

            # Name (e.g. "my name is Asha" or "i am Asha" or just "Asha").
            # Only attempted when the bot just asked for the name — otherwise free
            # text answering a later question (e.g. the complaint) gets
            # mis-extracted as a name on every turn.
            if expected_slot == "full_name":
                name_match = re.search(r"(?:my name is|i am)\s+([a-zA-Z]+)", lower_msg)
                if name_match:
                    slots["full_name"] = name_match.group(1).title()
                else:
                    # Fallback: clean out the phone number and punctuation, use remaining alpha words
                    cleaned_name = user_msg
                    if phone_match:
                        cleaned_name = cleaned_name.replace(phone_match.group(1), "")
                    cleaned_name = re.sub(r"[^\w\s]", "", cleaned_name).strip()
                    words = [w for w in cleaned_name.split() if w.isalpha()]
                    if words and not any(w.lower() in ["hi", "hello", "book", "appointment", "yes", "no"] for w in words):
                        slots["full_name"] = " ".join(words).title()

            # Main complaint: when the bot asked "what main problem or pain are you
            # facing", take the raw answer as-is rather than trying to keyword-match it.
            if expected_slot == "complaint" and user_msg.strip():
                slots["main_problem"] = user_msg.strip()

            # Pain score: the WhatsApp UI now offers Mild/Moderate/Severe buckets
            # (see templates.py request_pain_score), so recognize those words first;
            # a bare number is still accepted as a fallback for free-typed answers.
            if "severe" in lower_msg or "intense" in lower_msg:
                slots["pain_score"] = 9
            elif "moderate" in lower_msg:
                slots["pain_score"] = 6
            elif "mild" in lower_msg:
                slots["pain_score"] = 3
            else:
                score_match = re.search(r"\b([0-9]|10)\b", lower_msg)
                if score_match:
                    slots["pain_score"] = int(score_match.group(1))

            # Date change / time pick — only when the bot is actually in the
            # date/time phase (see EXPECTED_SLOT_CUES), so a stray number or
            # month name elsewhere in the conversation never gets mistaken for
            # a scheduling answer.
            if expected_slot in ("preferred_date", "preferred_date_or_time"):
                date_val = parse_natural_date(user_msg, today.date())
                if date_val:
                    slots["preferred_date"] = date_val
                elif expected_slot == "preferred_date_or_time":
                    time_val = parse_natural_time(user_msg)
                    if time_val:
                        slots["preferred_time"] = time_val

            # Service mode
            if "home" in lower_msg:
                slots["preferred_service_mode"] = "home_visit"
            elif "clinic" in lower_msg:
                slots["preferred_service_mode"] = "clinic_visit"
            elif "online" in lower_msg or "tele" in lower_msg or "video" in lower_msg:
                slots["preferred_service_mode"] = "tele_consultation"

            # Pain area
            area_mapping = {
                "neck": ["neck"],
                "shoulder": ["shoulder"],
                "upper back": ["upper back"],
                "lower back": ["lower back", "back"],
                "knee": ["knee"],
                "ankle": ["ankle", "foot"],
                "hip": ["hip"],
                "elbow": ["elbow"],
                "wrist": ["wrist"],
                "hand": ["hand"],
                "general weakness": ["weakness", "general weakness"],
                "post-surgery rehab": ["post-surgery", "surgery", "rehab"],
                "sports injury": ["sports", "injury"]
            }
            for area_id, keywords in area_mapping.items():
                if any(kw in lower_msg for kw in keywords):
                    slots["pain_area"] = area_id
                    break

            # Pain duration
            duration_mapping = {
                "less than 24 hours": ["24 hours", "24 hrs", "one day", "1 day", "less than 24"],
                "1-3 days": ["1-3 days", "1 to 3 days", "2 days", "3 days"],
                "4-7 days": ["4-7 days", "4 to 7 days", "4 days", "5 days", "6 days", "7 days", "a week", "1 week"],
                "1-4 weeks": ["1-4 weeks", "1 to 4 weeks", "2 weeks", "3 weeks", "4 weeks", "couple of weeks"],
                "1-3 months": ["1-3 months", "1 to 3 months", "a month", "1 month", "2 months", "3 months"],
                "more than 3 months": ["more than 3 months", "3+ months", "chronic", "years", "months"]
            }
            for dur_id, keywords in duration_mapping.items():
                if any(kw in lower_msg for kw in keywords):
                    slots["pain_duration"] = dur_id
                    break

            # Red flags scan
            for rf in red_flags_list:
                if rf in lower_msg:
                    red_flags_detected.append(rf)

            return {
                "intent": intent,
                "slots": slots,
                "red_flags_detected": red_flags_detected
            }
