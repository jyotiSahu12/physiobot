"""WhatsApp Template Registry mapping template keys to Meta configurations.
Includes fallback text for developer simulation and helpers to build WhatsApp payloads.
Supports standard Meta templates and native WhatsApp Interactive Buttons/Lists.
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
        "interactive_type": "list",
        "button_label": "Select Pain Area",
        "sections": [
            {
                "title": "Common Areas",
                "rows": [
                    {"id": "neck", "title": "Neck"},
                    {"id": "shoulder", "title": "Shoulder"},
                    {"id": "upper back", "title": "Upper Back"},
                    {"id": "lower back", "title": "Lower Back"},
                    {"id": "knee", "title": "Knee"},
                    {"id": "ankle", "title": "Ankle/Foot"}
                ]
            },
            {
                "title": "Other Areas",
                "rows": [
                    {"id": "hip", "title": "Hip"},
                    {"id": "elbow", "title": "Elbow"},
                    {"id": "wrist", "title": "Wrist"},
                    {"id": "hand", "title": "Hand"},
                    {"id": "general weakness", "title": "General Weakness"},
                    {"id": "post-surgery rehab", "title": "Post-Surgery"},
                    {"id": "sports injury", "title": "Sports Injury"}
                ]
            }
        ],
        "text_fallback": "Where is the pain or discomfort? (e.g., neck, shoulder, back, knee, etc.)"
    },
    "request_pain_duration": {
        "name": "request_pain_duration",
        "parameter_keys": [],
        "interactive_type": "list",
        "button_label": "Select Duration",
        "sections": [
            {
                "title": "Duration Options",
                "rows": [
                    {"id": "less than 24 hours", "title": "Less than 24 hours"},
                    {"id": "1-3 days", "title": "1-3 days"},
                    {"id": "4-7 days", "title": "4-7 days"},
                    {"id": "1-4 weeks", "title": "1-4 weeks"},
                    {"id": "1-3 months", "title": "1-3 months"},
                    {"id": "more than 3 months", "title": "More than 3 months"}
                ]
            }
        ],
        "text_fallback": "How long have you had this issue? (e.g., less than 24 hours, 1-3 days, 4-7 days, 1-4 weeks, 1-3 months, more than 3 months)"
    },
    "request_pain_score": {
        "name": "request_pain_score",
        "parameter_keys": [],
        "interactive_type": "list",
        "button_label": "Select Pain Score",
        "sections": [
            {
                "title": "Mild Pain",
                "rows": [
                    {"id": "0", "title": "0 - No pain"},
                    {"id": "1", "title": "1 - Minimal"},
                    {"id": "2", "title": "2 - Mild"},
                    {"id": "3", "title": "3 - Tolerable"}
                ]
            },
            {
                "title": "Moderate Pain",
                "rows": [
                    {"id": "4", "title": "4 - Distressing"},
                    {"id": "5", "title": "5 - Moderate"},
                    {"id": "6", "title": "6 - Intense"}
                ]
            },
            {
                "title": "Severe Pain",
                "rows": [
                    {"id": "7", "title": "7 - Very Intense"},
                    {"id": "8", "title": "8 - Utterly Severe"},
                    {"id": "9", "title": "9 - Excruciating"},
                    {"id": "10", "title": "10 - Unbearable"}
                ]
            }
        ],
        "text_fallback": "On a scale of 0 to 10, how severe is the pain?"
    },
    "request_service_mode": {
        "name": "request_service_mode",
        "parameter_keys": [],
        "interactive_type": "button",
        "buttons": [
            {"id": "clinic_visit", "title": "Clinic Visit"},
            {"id": "home_visit", "title": "Home Visit"},
            {"id": "tele_consultation", "title": "Online Consult"}
        ],
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
        "interactive_type": "button",
        "buttons": [
            {"id": "yes", "title": "Yes"},
            {"id": "no", "title": "No"}
        ],
        "text_fallback": "Have you consulted a doctor for this issue? (yes/no)"
    },
    "request_reports_available": {
        "name": "request_reports_available",
        "parameter_keys": [],
        "interactive_type": "button",
        "buttons": [
            {"id": "yes", "title": "Yes"},
            {"id": "no", "title": "No"}
        ],
        "text_fallback": "Do you have any medical reports or prescriptions? (yes/no)"
    },
    "show_slots": {
        "name": "show_slots",
        "parameter_keys": ["date", "slots_list"],
        "interactive_type": "list",
        "button_label": "Select Time Slot",
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
        for key in template.get("parameter_keys", []):
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
    for key in template.get("parameter_keys", []):
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


def build_whatsapp_interactive_payload(template_key: str, recipient: str, **kwargs) -> dict:
    """Build the exact payload required to send a Meta WhatsApp interactive button/list message."""
    template = TEMPLATES.get(template_key, TEMPLATES["generic_fallback"])
    body_text = format_template_text(template_key, **kwargs)
    int_type = template["interactive_type"]

    interactive_content: dict = {
        "type": int_type,
        "body": {
            "text": body_text
        }
    }

    if int_type == "button":
        buttons = []
        for btn in template.get("buttons", []):
            buttons.append({
                "type": "reply",
                "reply": {
                    "id": btn["id"],
                    "title": btn["title"][:20]  # Meta limit is 20 chars
                }
            })
        interactive_content["action"] = {"buttons": buttons}

    elif int_type == "list":
        sections = []
        if template_key == "show_slots":
            # Dynamic rows for free slots
            raw_slots = kwargs.get("raw_slots") or []
            rows = []
            for s in raw_slots[:10]:  # Meta list limit is 10 rows
                rows.append({
                    "id": s,
                    "title": s,
                    "description": f"Book slot starting {s}"
                })
            if rows:
                sections.append({
                    "title": "Available Times",
                    "rows": rows
                })
            else:
                sections.append({
                    "title": "No Times Available",
                    "rows": [{"id": "no_slots", "title": "No slots found", "description": "Please try another date"}]
                })
        else:
            # Static rows from template definition
            for sec in template.get("sections", []):
                rows = []
                for r in sec.get("rows", []):
                    rows.append({
                        "id": r["id"],
                        "title": r["title"][:24],  # Meta limit is 24 chars
                        "description": r.get("description", "")[:72]  # Meta limit is 72 chars
                    })
                sections.append({
                    "title": sec["title"][:24],
                    "rows": rows
                })

        interactive_content["action"] = {
            "button": template.get("button_label", "Select")[:20],  # Meta limit is 20 chars
            "sections": sections
        }

    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "interactive",
        "interactive": interactive_content
    }
