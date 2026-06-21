"""WhatsApp Template Registry mapping template keys to Meta configurations.
Includes fallback text for developer simulation and helpers to build WhatsApp payloads.
Supports standard Meta templates and native WhatsApp Interactive Buttons/Lists.
"""
from __future__ import annotations

TEMPLATES = {
    "welcome_greeting": {
        "name": "welcome_greeting",
        "parameter_keys": ["clinic_name"],
        "text_fallback": "Hello, and welcome to {clinic_name}. We're glad you reached out — how can we help you today?"
    },
    "request_full_name": {
        "name": "request_full_name",
        "parameter_keys": [],
        "text_fallback": "Could you share your full name, please?"
    },
    "confirm_details": {
        "name": "confirm_details",
        "parameter_keys": ["detected_name", "detected_phone"],
        "interactive_type": "button",
        "buttons": [
            {"id": "yes", "title": "Yes, that's right"},
            {"id": "no", "title": "No, let me correct"}
        ],
        "text_fallback": "I see your WhatsApp name as {detected_name} and number as {detected_phone}. Is that correct?"
    },
    "request_consent": {
        "name": "request_consent",
        "parameter_keys": [],
        "interactive_type": "button",
        "buttons": [
            {"id": "yes", "title": "Yes, I agree"},
            {"id": "no", "title": "No"}
        ],
        "text_fallback": (
            "Before we continue: do you agree that Balance Plus can contact you about "
            "this appointment, and that you can share basic symptom details so our team "
            "can triage your case? (Yes/No)"
        )
    },
    "consent_declined": {
        "name": "consent_declined",
        "parameter_keys": ["clinic_phone"],
        "text_fallback": (
            "No problem, we won't collect your symptom details over chat. "
            "Please call the HSR Layout clinic directly at {clinic_phone} to book your appointment."
        )
    },
    "request_complaint": {
        "name": "request_complaint",
        "parameter_keys": ["name"],
        "text_fallback": "Thanks {name}! What main problem or pain are you facing?"
    },
    "request_pain_area": {
        "name": "request_pain_area",
        "parameter_keys": ["service_hint"],
        "interactive_type": "list",
        "button_label": "Select Pain Area",
        # WhatsApp list messages cap out at 10 rows total across all sections
        # combined (Meta returns "Total row count exceed max allowed count: 10"
        # otherwise). Post-surgery/sports-injury context is already captured
        # via the free-text complaint (main_problem) and matched against
        # service_recommendation_logic there, so dropping them here loses no
        # signal. Wrist and hand are merged into one row to make room.
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
                    {"id": "wrist", "title": "Wrist/Hand"},
                    {"id": "general weakness", "title": "General Weakness"}
                ]
            }
        ],
        "text_fallback": "{service_hint}Where is the pain or discomfort?"
    },
    "request_pain_duration": {
        "name": "request_pain_duration",
        "parameter_keys": ["service_hint"],
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
        "text_fallback": "{service_hint}How long have you had this issue?"
    },
    "request_pain_score": {
        "name": "request_pain_score",
        "parameter_keys": ["service_hint"],
        "interactive_type": "list",
        "button_label": "Select Pain Level",
        # A 0-10 numeric scale asks too much precision of a patient describing
        # pain over chat. Three plain-language buckets are easier to answer
        # confidently, and each still maps to a representative 0-10 value
        # (3/6/9) for the pain_score_0_to_10 field staff see in the sheet.
        "sections": [
            {
                "title": "Pain Level",
                "rows": [
                    {"id": "3", "title": "Mild", "description": "Noticeable, but manageable"},
                    {"id": "6", "title": "Moderate", "description": "Distressing, hard to ignore"},
                    {"id": "9", "title": "Severe", "description": "Intense, hard to bear"}
                ]
            }
        ],
        "text_fallback": "{service_hint}How severe is the pain — mild, moderate, or severe?"
    },
    "request_service_mode": {
        "name": "request_service_mode",
        "parameter_keys": ["service_hint"],
        "interactive_type": "button",
        "buttons": [
            {"id": "clinic_visit", "title": "Clinic Visit"},
            {"id": "home_visit", "title": "Home Visit"},
            {"id": "tele_consultation", "title": "Online Consult"}
        ],
        "text_fallback": "{service_hint}How would you like to have your consultation?"
    },
    "request_date_time": {
        "name": "request_date_time",
        "parameter_keys": [],
        "text_fallback": "What date would you like to come in? (e.g. 2026-06-25, or just say \"next Monday\")"
    },
    "show_slots": {
        "name": "show_slots",
        "parameter_keys": ["date", "slots_list"],
        "interactive_type": "list",
        "button_label": "Select Time Slot",
        # The native list rows already enumerate every time slot, so the
        # interactive message body must not repeat slots_list — that's the
        # exact "timings printed in text as well" duplication bug. The full
        # text_fallback (with slots_list) is still used in dev/no-Meta mode,
        # where there's no list UI to show the times any other way.
        "interactive_body_text": "Available times for {date}:\n\nWhich time works best for you?",
        "text_fallback": "Available times for {date}:\n{slots_list}\n\nWhich time works best for you?"
    },
    "booking_confirmed": {
        "name": "booking_confirmed",
        "parameter_keys": ["date_time"],
        "text_fallback": "You're all set! We've booked you in for {date_time}. Looking forward to seeing you."
    },
    "post_booking_chat": {
        "name": "post_booking_chat",
        "parameter_keys": ["date_time", "clinic_phone"],
        "text_fallback": (
            "Happy to help! Your appointment is still confirmed for {date_time}. "
            "Let us know if you'd like to book another visit, or call us at {clinic_phone} for anything else."
        )
    },
    "no_slots_available": {
        "name": "no_slots_available",
        "parameter_keys": ["date", "clinic_phone"],
        "text_fallback": "Sorry, there are no available slots on {date}. Please share another date, or call {clinic_phone} directly."
    },
    "booking_failed": {
        "name": "booking_failed",
        "parameter_keys": ["clinic_phone"],
        "text_fallback": "Sorry, that booking could not be completed. Please pick another time, or call {clinic_phone} directly."
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
        "parameter_keys": ["answer"],
        "text_fallback": "{answer}"
    },
    "location_with_map": {
        "name": "location_with_map",
        "parameter_keys": ["answer"],
        "interactive_type": "cta_url",
        "cta_label": "View on Map",
        "text_fallback": "{answer}\n\nView on map: {maps_url}"
    },
    "generic_fallback": {
        "name": "generic_fallback",
        "parameter_keys": ["clinic_phone"],
        "text_fallback": "I'm here to help. For any questions or direct bookings, please feel free to call our clinic at {clinic_phone}."
    }
}


def _format_text(text: str, parameter_keys: list[str], **kwargs) -> str:
    try:
        # Default missing arguments to placeholders
        fmt_args = {}
        for key in parameter_keys:
            fmt_args[key] = kwargs.get(key, f"{{{key}}}")
        # Add any other kwargs that might exist in the text
        for key, val in kwargs.items():
            if key not in fmt_args:
                fmt_args[key] = val
        return text.format(**fmt_args)
    except Exception:
        return text


def format_template_text(template_key: str, **kwargs) -> str:
    """Format the fallback text of a template for developer logging / simulation."""
    template = TEMPLATES.get(template_key, TEMPLATES["generic_fallback"])
    return _format_text(template["text_fallback"], template.get("parameter_keys", []), **kwargs)


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
    int_type = template["interactive_type"]

    if int_type == "cta_url":
        # The link itself becomes the button's action, not text in the body —
        # unlike format_template_text's fallback (used in dev/no-Meta mode,
        # where there's no tappable button so the raw URL needs to be visible).
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "interactive",
            "interactive": {
                "type": "cta_url",
                "body": {"text": kwargs.get("answer", "")},
                "action": {
                    "name": "cta_url",
                    "parameters": {
                        "display_text": template.get("cta_label", "Open Link")[:20],
                        "url": kwargs.get("maps_url", ""),
                    },
                },
            },
        }

    # Native interactive messages render their own rows/buttons, so the body
    # text must not repeat that content (see show_slots' interactive_body_text).
    # Falls back to the same text dev/no-Meta mode uses when no override exists.
    body_source = template.get("interactive_body_text", template["text_fallback"])
    body_text = _format_text(body_source, template.get("parameter_keys", []), **kwargs)

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
