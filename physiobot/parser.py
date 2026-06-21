"""Structured LLM parser for NLU: Intent classification, slot filling, and red-flag detection.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import Config, get_config
from .llm import get_provider

log = logging.getLogger("physiobot.parser")

METADATA_PATH = Path(__file__).resolve().parent / "clinic_metadata.json"


def load_metadata() -> dict:
    try:
        with open(METADATA_PATH) as f:
            return json.load(f)
    except Exception:
        log.exception("failed to load clinic_metadata.json")
        return {}


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
        self.metadata = load_metadata()

    def parse_message(self, history: list[dict]) -> dict:
        """Analyze conversation history and user turn to extract structured intent,
        slots, and red flags. Returns a dict matching the structured parser schema."""
        tz = ZoneInfo(self.config.clinic.timezone)
        today = dt.datetime.now(tz)
        today_str = today.strftime("%A, %Y-%m-%d")

        bot_cfg = self.metadata.get("bot_configuration", {})
        supported_intents = bot_cfg.get("supported_intents", [])
        
        triage_cfg = self.metadata.get("triage_and_safety", {})
        red_flags_list = triage_cfg.get("red_flags_requiring_urgent_medical_referral", [])

        pain_area_options = []
        pain_duration_options = []
        intake_questions = self.metadata.get("customer_intake", {}).get("clinical_intake_questions", [])
        for q in intake_questions:
            if q["field"] == "pain_area":
                pain_area_options = q.get("options", [])
            elif q["field"] == "pain_duration":
                pain_duration_options = q.get("options", [])

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
            '    "phone_number": "string_or_null",\n'
            '    "main_problem": "string_or_null",\n'
            '    "pain_area": "one_of_pain_area_options_or_null",\n'
            '    "pain_duration": "one_of_pain_duration_options_or_null",\n'
            '    "pain_score": "integer_0_to_10_or_null",\n'
            '    "preferred_service_mode": "clinic_visit" | "home_visit" | "tele_consultation" | null,\n'
            '    "preferred_branch_or_area": "string_or_null",\n'
            '    "preferred_date": "YYYY-MM-DD_or_null", // Resolve relative dates like tomorrow/Monday using today\'s date\n'
            '    "preferred_time": "HH:MM_or_null",\n'
            '    "doctor_referral_status": "yes" | "no" | null,\n'
            '    "reports_available": "yes" | "no" | null\n'
            "  },\n"
            '  "red_flags_detected": [] // List of red flag keywords/phrases from the urgent list if matched in user inputs\n'
            "}"
        )

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)

        try:
            assistant_msg = self.provider.chat(messages, tools=None)
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
            elif any(t in lower_msg for t in ["time", "timing", "hour", "when", "schedule"]):
                intent = "ask_timings"

            # 2. Basic slot extraction
            # Phone number (e.g. +917054256969 or 7054256969)
            phone_match = re.search(r"(\+?\d{10,12})", user_msg)
            if phone_match:
                slots["phone_number"] = phone_match.group(1)

            # Name (e.g. "my name is Asha" or "i am Asha")
            name_match = re.search(r"(?:my name is|i am)\s+([a-zA-Z]+)", lower_msg)
            if name_match:
                slots["full_name"] = name_match.group(1).title()

            # Pain score (integer 0 to 10)
            score_match = re.search(r"\b([0-9]|10)\b", lower_msg)
            if score_match:
                slots["pain_score"] = int(score_match.group(1))

            # Service mode
            if "home" in lower_msg:
                slots["preferred_service_mode"] = "home_visit"
            elif "clinic" in lower_msg:
                slots["preferred_service_mode"] = "clinic_visit"
            elif "online" in lower_msg or "tele" in lower_msg or "video" in lower_msg:
                slots["preferred_service_mode"] = "tele_consultation"

            # Pain area
            for area in pain_area_options:
                if area in lower_msg:
                    slots["pain_area"] = area
                    break

            # Pain duration
            for dur in pain_duration_options:
                if dur in lower_msg:
                    slots["pain_duration"] = dur
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
