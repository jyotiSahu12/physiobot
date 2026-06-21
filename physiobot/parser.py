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
        
        safety_cfg = self.metadata.get("medical_safety_and_red_flags") or self.metadata.get("triage_and_safety") or {}
        red_flags_list = safety_cfg.get("emergency_or_doctor_referral_triggers") or safety_cfg.get("red_flags_requiring_urgent_medical_referral") or []

        pain_area_options = [
            "neck", "shoulder", "upper back", "lower back", "knee", "ankle",
            "hip", "elbow", "wrist", "hand", "general weakness", "post-surgery rehab", "sports injury"
        ]
        pain_duration_options = [
            "less than 24 hours", "1-3 days", "4-7 days", "1-4 weeks", "1-3 months", "more than 3 months"
        ]

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
            elif any(t in lower_msg for t in ["timings", "opening hours", "open hours", "what time do you open"]):
                intent = "ask_timings"
            elif any(ins in lower_msg for ins in ["insurance", "reimbursement", "claim", "coverage"]):
                intent = "insurance_query"
            elif any(pay in lower_msg for pay in ["payment", "pay", "upi", "cash", "card", "refund", "invoice"]):
                intent = "payment_query"
            elif any(rep in lower_msg for rep in ["report", "prescription", "scan", "mri", "xray", "x-ray"]):
                intent = "medical_report_query"

            # 2. Basic slot extraction
            # Phone number (e.g. +917054256969 or 7054256969)
            phone_match = re.search(r"(\+?\d{10,12})", user_msg)
            if phone_match:
                slots["phone_number"] = phone_match.group(1)

            # Name (e.g. "my name is Asha" or "i am Asha" or just "Asha")
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
