"""WhatsApp Template Registry mapping template keys to Meta configurations.
Includes fallback text for developer simulation and helpers to build WhatsApp payloads.
Supports standard Meta templates and native WhatsApp Interactive Buttons/Lists.
"""
from __future__ import annotations

# Meta WhatsApp Cloud API hard limits for interactive messages. Exceeding ANY
# of these makes Meta reject the whole send with HTTP 400 — and because the send
# happens after the state machine has already advanced and saved the session,
# the conversation just goes silent with no error visible to the patient. These
# are enforced centrally (see enforce_meta_interactive_limits) on every outgoing
# interactive payload, so content from any source — static templates, clinic
# metadata, calendar slots, or LLM output — can never trip them.
# Refs: developers.facebook.com/docs/whatsapp/cloud-api/guides/send-messages
META_LIMITS = {
    "body_text": 1024,
    "header_text": 60,
    "button_title": 20,          # quick-reply button label
    "buttons": 3,                # max quick-reply buttons per message
    "list_button_label": 20,     # the CTA that opens a list (e.g. "Select")
    "list_rows_total": 10,       # rows across ALL sections combined, not per-section
    "list_sections": 10,
    "section_title": 24,
    "row_title": 24,
    "row_description": 72,
    "cta_display_text": 20,      # cta_url button label
}


def _clip(value, limit: int):
    """Truncate a string to a max length; pass non-strings through untouched."""
    return value[:limit] if isinstance(value, str) else value


def enforce_meta_interactive_limits(payload: dict) -> dict:
    """Final safety pass clamping an interactive payload to Meta's hard limits.

    This is the single guarantee that an interactive message is sendable,
    regardless of how it was built. Individual builders express *intent*
    (which rows/buttons to show); this function makes the result *valid*.
    Mutates and returns the payload.
    """
    interactive = payload.get("interactive")
    if not isinstance(interactive, dict):
        return payload

    body = interactive.get("body")
    if isinstance(body, dict) and "text" in body:
        body["text"] = _clip(body["text"], META_LIMITS["body_text"])

    header = interactive.get("header")
    if isinstance(header, dict) and header.get("type") == "text":
        header["text"] = _clip(header.get("text", ""), META_LIMITS["header_text"])

    action = interactive.get("action")
    if not isinstance(action, dict):
        return payload

    # Quick-reply buttons
    buttons = action.get("buttons")
    if isinstance(buttons, list):
        del buttons[META_LIMITS["buttons"]:]
        for btn in buttons:
            reply = btn.get("reply", {})
            if "title" in reply:
                reply["title"] = _clip(reply["title"], META_LIMITS["button_title"])

    # cta_url single-button
    if interactive.get("type") == "cta_url":
        params = action.get("parameters", {})
        if "display_text" in params:
            params["display_text"] = _clip(params["display_text"], META_LIMITS["cta_display_text"])

    # List
    if "button" in action:
        action["button"] = _clip(action["button"], META_LIMITS["list_button_label"])
    sections = action.get("sections")
    if isinstance(sections, list):
        del sections[META_LIMITS["list_sections"]:]
        remaining = META_LIMITS["list_rows_total"]  # the 10-row cap is shared across sections
        for sec in sections:
            sec["title"] = _clip(sec.get("title", ""), META_LIMITS["section_title"])
            rows = sec.get("rows", [])
            del rows[max(remaining, 0):]
            remaining -= len(rows)
            for row in rows:
                if "title" in row:
                    row["title"] = _clip(row["title"], META_LIMITS["row_title"])
                if "description" in row:
                    row["description"] = _clip(row.get("description", ""), META_LIMITS["row_description"])
        # Meta rejects a section with zero rows, so drop any emptied by the cap.
        action["sections"] = [s for s in sections if s.get("rows")]

    return payload


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
    "confirm_returning_branch": {
        "name": "confirm_returning_branch",
        "parameter_keys": ["branch_name"],
        "interactive_type": "button",
        "buttons": [
            {"id": "yes", "title": "Yes, same branch"},
            {"id": "no", "title": "No, choose again"}
        ],
        "text_fallback": "Last time you visited our {branch_name} branch — would you like to book there again?"
    },
    "request_branch": {
        "name": "request_branch",
        "parameter_keys": [],
        "interactive_type": "list",
        "button_label": "Select Branch",
        # Rows are built dynamically from ClinicKB.branches() in
        # build_whatsapp_interactive_payload (like show_slots) rather than
        # hardcoded here, so the branch list stays driven by clinic_metadata.json.
        "text_fallback": "Which Balance Plus branch would you like to visit?"
    },
    "non_hsr_branch_handoff": {
        "name": "non_hsr_branch_handoff",
        "parameter_keys": ["branch_name", "branch_phone"],
        # This bot only has live calendar access for the HSR Layout branch —
        # for any other branch we'd be guessing at availability, so a human
        # confirms it instead rather than the bot fabricating a booking.
        "text_fallback": (
            "Got it — our {branch_name} branch. We don't manage that branch's calendar through this chat yet, "
            "so I've passed your request to our team and they'll confirm your slot directly. "
            "You can also reach that branch at {branch_phone}."
        )
    },
    "request_date_time": {
        "name": "request_date_time",
        "parameter_keys": [],
        # Ask about *when* the way a receptionist would — open-ended, so a
        # natural reply like "today evening" or "tomorrow morning" is welcome.
        # The NLU resolves the day + rough time-of-day and we then show the
        # matching slots; don't fixate on pinning an exact calendar date first.
        "text_fallback": "When would you like to come in? Morning, afternoon or evening — and which day suits you?"
    },
    "show_slots": {
        "name": "show_slots",
        "parameter_keys": ["date", "slots_list", "note"],
        "interactive_type": "list",
        "button_label": "Select Time Slot",
        # {note} is an optional lead-in (e.g. "Today evening is fully booked —
        # here's the next availability:") set by the state machine when it had
        # to roll the request forward; empty otherwise.
        # The native list rows already enumerate every time slot, so the
        # interactive message body must not repeat slots_list — that's the
        # exact "timings printed in text as well" duplication bug. The full
        # text_fallback (with slots_list) is still used in dev/no-Meta mode,
        # where there's no list UI to show the times any other way.
        "interactive_body_text": "{note}Available times for {date}:\n\nWhich time works best for you?",
        "text_fallback": "{note}Available times for {date}:\n{slots_list}\n\nWhich time works best for you?"
    },
    "booking_confirmed": {
        "name": "booking_confirmed",
        "parameter_keys": ["date_time", "clinic_address", "clinic_phone"],
        "text_fallback": (
            "You're all set! We've booked you in for {date_time} at {clinic_address}. "
            "If you need to reach us, call {clinic_phone}. Looking forward to seeing you."
        )
    },
    "booking_confirmed_map": {
        "name": "booking_confirmed_map",
        "parameter_keys": ["date_time", "clinic_address", "clinic_phone"],
        "interactive_type": "cta_url",
        "cta_label": "View on Map",
        # cta_body_text is the message body (shown above the tappable button);
        # the map link rides the button, so it isn't repeated in the body.
        "cta_body_text": (
            "You're all set! We've booked you in for {date_time} at {clinic_address}. "
            "If you need to reach us, call {clinic_phone}. Looking forward to seeing you."
        ),
        # Dev/no-Meta fallback has no tappable button, so the URL is inline.
        "text_fallback": (
            "You're all set! We've booked you in for {date_time} at {clinic_address}. "
            "If you need to reach us, call {clinic_phone}. Looking forward to seeing you.\n\n"
            "View on map: {maps_url}"
        )
    },
    "post_booking_chat": {
        "name": "post_booking_chat",
        "parameter_keys": ["date_time", "clinic_address", "clinic_phone"],
        "text_fallback": (
            "Happy to help! Your appointment is still confirmed for {date_time} at {clinic_address}. "
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
        # Body is either an explicit "answer" kwarg (location_with_map) or a
        # formatted template body (cta_body_text, e.g. booking_confirmed_map).
        body_text = kwargs.get("answer")
        if body_text is None:
            body_text = _format_text(
                template.get("cta_body_text", template["text_fallback"]),
                template.get("parameter_keys", []), **kwargs,
            )
        return enforce_meta_interactive_limits({
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient,
            "type": "interactive",
            "interactive": {
                "type": "cta_url",
                "body": {"text": body_text},
                "action": {
                    "name": "cta_url",
                    "parameters": {
                        "display_text": template.get("cta_label", "Open Link"),
                        "url": kwargs.get("maps_url", ""),
                    },
                },
            },
        })

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

    # Builders below express intent (which rows/buttons, in what order). All
    # length/count clamping to Meta's hard limits is done once, centrally, by
    # enforce_meta_interactive_limits at the return — never scatter [:24]/[:20]
    # truncations here (that's how the "row title too long" 400 slipped in).
    if int_type == "button":
        buttons = []
        for btn in template.get("buttons", []):
            buttons.append({
                "type": "reply",
                "reply": {"id": btn["id"], "title": btn["title"]}
            })
        interactive_content["action"] = {"buttons": buttons}

    elif int_type == "list":
        sections = []
        if template_key == "show_slots":
            # Dynamic rows for free slots
            raw_slots = kwargs.get("raw_slots") or []
            rows = [{"id": s, "title": s, "description": f"Book slot starting {s}"} for s in raw_slots]
            if rows:
                sections.append({"title": "Available Times", "rows": rows})
            else:
                sections.append({
                    "title": "No Times Available",
                    "rows": [{"id": "no_slots", "title": "No slots found", "description": "Please try another date"}]
                })
        elif template_key == "request_branch":
            # Dynamic rows from ClinicKB.branches() (see state_machine.py),
            # so this list always matches clinic_metadata.json.
            raw_branches = kwargs.get("raw_branches") or []
            rows = [
                {"id": b["id"], "title": b["name"], "description": b.get("address", "")}
                for b in raw_branches
            ]
            sections.append({"title": "Branches", "rows": rows})
        else:
            # Static rows from template definition
            for sec in template.get("sections", []):
                rows = [
                    {"id": r["id"], "title": r["title"], "description": r.get("description", "")}
                    for r in sec.get("rows", [])
                ]
                sections.append({"title": sec["title"], "rows": rows})

        interactive_content["action"] = {
            "button": template.get("button_label", "Select"),
            "sections": sections
        }

    return enforce_meta_interactive_limits({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": recipient,
        "type": "interactive",
        "interactive": interactive_content
    })
