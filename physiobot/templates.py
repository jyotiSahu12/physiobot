"""WhatsApp Template Registry mapping template keys to Meta configurations.
Includes fallback text for developer simulation and helpers to build WhatsApp payloads.
"""
from __future__ import annotations

TEMPLATES = {
    "welcome_greeting": {
        "name": "welcome_greeting",
        "parameter_keys": ["clinic_name"],
        "text_fallback": "Hello! Welcome to {clinic_name}. How can we help you today?"
    },
    "request_name_phone": {
        "name": "request_name_phone",
        "parameter_keys": [],
        "text_fallback": "To proceed, could you please share your full name and phone number?"
    },
    "request_complaint": {
        "name": "request_complaint",
        "parameter_keys": ["name"],
        "text_fallback": "Thanks {name}! What main problem or pain are you facing?"
    },
    "request_pain_area": {
        "name": "request_pain_area",
        "parameter_keys": [],
        "text_fallback": "Where is the pain or discomfort? (e.g., neck, shoulder, back, knee, etc.)"
    },
    "request_pain_duration": {
        "name": "request_pain_duration",
        "parameter_keys": [],
        "text_fallback": "How long have you had this issue? (e.g., less than 24 hours, 1-3 days, 4-7 days, 1-4 weeks, 1-3 months, more than 3 months)"
    },
    "request_pain_score": {
        "name": "request_pain_score",
        "parameter_keys": [],
        "text_fallback": "On a scale of 0 to 10, how severe is the pain?"
    },
    "request_service_mode": {
        "name": "request_service_mode",
        "parameter_keys": [],
        "text_fallback": "Would you prefer a clinic_visit, home_visit, or tele_consultation?"
    },
    "request_branch": {
        "name": "request_branch",
        "parameter_keys": ["branches"],
        "text_fallback": "Which branch would you prefer? Available branches: {branches}"
    },
    "request_date_time": {
        "name": "request_date_time",
        "parameter_keys": [],
        "text_fallback": "What is your preferred date (YYYY-MM-DD) or day for the appointment?"
    },
    "request_doctor_referral": {
        "name": "request_doctor_referral",
        "parameter_keys": [],
        "text_fallback": "Have you consulted a doctor for this issue? (yes/no)"
    },
    "request_reports_available": {
        "name": "request_reports_available",
        "parameter_keys": [],
        "text_fallback": "Do you have any medical reports or prescriptions? (yes/no)"
    },
    "show_slots": {
        "name": "show_slots",
        "parameter_keys": ["date", "slots_list"],
        "text_fallback": "Available times for {date}:\n{slots_list}\n\nWhich time works best for you?"
    },
    "booking_confirmed": {
        "name": "booking_confirmed",
        "parameter_keys": ["date_time"],
        "text_fallback": "Your appointment is confirmed for {date_time}. Looking forward to seeing you!"
    },
    "red_flag_alert": {
        "name": "red_flag_alert",
        "parameter_keys": ["red_flag_bot_response"],
        "text_fallback": "{red_flag_bot_response}"
    },
    "human_handoff": {
        "name": "human_handoff",
        "parameter_keys": ["clinic_phone"],
        "text_fallback": "I've routed your query to our clinic coordinator. They will contact you shortly. You can also reach us at {clinic_phone}."
    },
    "faq_response": {
        "name": "faq_response",
        "parameter_keys": ["question", "answer"],
        "text_fallback": "Q: {question}\nA: {answer}"
    },
    "generic_fallback": {
        "name": "generic_fallback",
        "parameter_keys": ["clinic_phone"],
        "text_fallback": "I'm here to help. For any questions or direct bookings, please feel free to call our clinic at {clinic_phone}."
    }
}


def format_template_text(template_key: str, **kwargs) -> str:
    """Format the fallback text of a template for developer logging / simulation."""
    template = TEMPLATES.get(template_key, TEMPLATES["generic_fallback"])
    fallback = template["text_fallback"]
    try:
        # Default missing arguments to placeholders
        fmt_args = {}
        for key in template["parameter_keys"]:
            fmt_args[key] = kwargs.get(key, f"{{{key}}}")
        # Add any other kwargs that might exist in fallback
        for key, val in kwargs.items():
            if key not in fmt_args:
                fmt_args[key] = val
        return fallback.format(**fmt_args)
    except Exception:
        return fallback


def build_whatsapp_payload(template_key: str, recipient: str, lang_code: str = "en_US", **kwargs) -> dict:
    """Build the exact payload required to send a Meta WhatsApp template message."""
    template = TEMPLATES.get(template_key, TEMPLATES["generic_fallback"])
    parameters = []
    for key in template["parameter_keys"]:
        val = kwargs.get(key, "")
        parameters.append({
            "type": "text",
            "text": str(val)
        })

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "template",
        "template": {
            "name": template["name"],
            "language": {
                "code": lang_code
            }
        }
    }

    if parameters:
        payload["template"]["components"] = [
            {
                "type": "body",
                "parameters": parameters
            }
        ]

    return payload
