from physiobot.templates import (
    META_LIMITS,
    TEMPLATES,
    build_whatsapp_interactive_payload,
    enforce_meta_interactive_limits,
    format_template_text,
)

# Meta hard limits for WhatsApp interactive messages — violating these gets
# the whole send rejected outright (e.g. "Total row count exceed max allowed
# count: 10"), which is exactly what happened with the original
# request_pain_area (13 rows) and request_pain_score (11 rows) templates.
MAX_LIST_ROWS_TOTAL = 10
MAX_LIST_SECTIONS = 10
MAX_BUTTONS = 3
MAX_LIST_ROW_TITLE_CHARS = 24
MAX_LIST_ROW_DESC_CHARS = 72


def _static_list_templates():
    for key, template in TEMPLATES.items():
        if template.get("interactive_type") == "list" and "sections" in template:
            yield key, template


def test_static_list_templates_stay_within_meta_row_limit():
    for key, template in _static_list_templates():
        sections = template["sections"]
        total_rows = sum(len(sec["rows"]) for sec in sections)
        assert total_rows <= MAX_LIST_ROWS_TOTAL, (
            f"{key} has {total_rows} rows across {len(sections)} sections, "
            f"exceeds Meta's {MAX_LIST_ROWS_TOTAL}-row cap"
        )
        assert len(sections) <= MAX_LIST_SECTIONS, f"{key} has too many sections"


def test_static_button_templates_stay_within_meta_button_limit():
    for key, template in TEMPLATES.items():
        if template.get("interactive_type") == "button":
            assert len(template["buttons"]) <= MAX_BUTTONS, f"{key} has too many buttons"


def test_request_pain_score_payload_uses_three_buckets():
    # Grandma-friendly: a 0-10 numeric scale is too fine-grained over chat,
    # so the UI offers three plain-language buckets instead.
    payload = build_whatsapp_interactive_payload("request_pain_score", "9199", service_hint="")
    sections = payload["interactive"]["action"]["sections"]
    row_ids = [row["id"] for sec in sections for row in sec["rows"]]
    assert row_ids == ["3", "6", "9"]


def test_show_slots_interactive_body_omits_slots_list_to_avoid_duplication():
    payload = build_whatsapp_interactive_payload(
        "show_slots", "9199", date="2026-06-22", slots_list="- 10:00\n- 11:00",
        raw_slots=["10:00", "11:00"], note="",
    )
    body_text = payload["interactive"]["body"]["text"]
    assert "10:00" not in body_text
    assert "2026-06-22" in body_text


def test_show_slots_dev_fallback_text_still_includes_slots_list():
    # No native list UI in dev/no-Meta mode, so the times must still be visible.
    text = format_template_text("show_slots", date="2026-06-22", slots_list="- 10:00\n- 11:00", note="")
    assert "10:00" in text


def test_show_slots_note_prepended_when_rolled_forward():
    text = format_template_text(
        "show_slots", date="Monday, June 23, 2026", slots_list="- 10:00",
        note="Today evening is fully booked — here's the next availability:\n\n",
    )
    assert text.startswith("Today evening is fully booked")
    assert "Available times for Monday, June 23, 2026" in text


def test_request_pain_area_payload_stays_within_row_limit():
    payload = build_whatsapp_interactive_payload("request_pain_area", "9199", service_hint="")
    sections = payload["interactive"]["action"]["sections"]
    total_rows = sum(len(sec["rows"]) for sec in sections)
    assert total_rows <= MAX_LIST_ROWS_TOTAL


def test_request_branch_payload_built_dynamically_from_raw_branches():
    raw_branches = [
        {"id": "balanceplus_hsr_layout_sector_7", "name": "HSR Layout", "address": "Sector 7, HSR Layout"},
        {"id": "balanceplus_domlur", "name": "Domlur", "address": "Domlur, Bengaluru"},
    ]
    payload = build_whatsapp_interactive_payload("request_branch", "9199", raw_branches=raw_branches)
    rows = payload["interactive"]["action"]["sections"][0]["rows"]
    assert [r["id"] for r in rows] == ["balanceplus_hsr_layout_sector_7", "balanceplus_domlur"]
    assert rows[0]["title"] == "HSR Layout"
    assert rows[1]["description"] == "Domlur, Bengaluru"


def test_request_branch_row_title_truncated_to_meta_limit():
    # Meta rejects the whole send if any row title exceeds 24 chars
    # (error 131009 "Row title is too long. Max length is 24").
    raw_branches = [{"id": "x", "name": "A" * 40, "address": "B" * 100}]
    payload = build_whatsapp_interactive_payload("request_branch", "9199", raw_branches=raw_branches)
    row = payload["interactive"]["action"]["sections"][0]["rows"][0]
    assert len(row["title"]) <= MAX_LIST_ROW_TITLE_CHARS
    assert len(row["description"]) <= MAX_LIST_ROW_DESC_CHARS


def test_booking_confirmed_map_is_cta_url_with_map_button():
    payload = build_whatsapp_interactive_payload(
        "booking_confirmed_map", "9199",
        date_time="Monday, June 22, 2026 at 1:00 PM",
        clinic_address="Sector 7, HSR Layout", clinic_phone="+91 74116 92516",
        maps_url="https://www.google.com/maps/search/?api=1&query=Sector%207",
    )
    interactive = payload["interactive"]
    assert interactive["type"] == "cta_url"
    body = interactive["body"]["text"]
    assert "Monday, June 22, 2026 at 1:00 PM" in body
    assert "Sector 7, HSR Layout" in body
    # The map link rides the button, not the body text (no raw URL in the body).
    assert "http" not in body
    action = interactive["action"]["parameters"]
    assert action["display_text"] == "View on Map"
    assert action["url"].startswith("https://www.google.com/maps/")


def test_booking_confirmed_map_dev_fallback_shows_inline_url():
    text = format_template_text(
        "booking_confirmed_map",
        date_time="Mon", clinic_address="A", clinic_phone="P", maps_url="https://maps/x",
    )
    assert "https://maps/x" in text


# --- central Meta-limit enforcer: the single guarantee an interactive payload
# is sendable, no matter how adversarial the content it was built from is ------

def test_enforcer_clamps_oversized_list_payload_everywhere():
    payload = {
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": "X" * 5000},
            "action": {
                "button": "B" * 50,
                "sections": [
                    {"title": "T" * 50, "rows": [
                        {"id": str(i), "title": "R" * 50, "description": "D" * 200} for i in range(8)
                    ]},
                    {"title": "T2" * 50, "rows": [
                        {"id": f"b{i}", "title": "R" * 50, "description": "D" * 200} for i in range(8)
                    ]},
                    # A third section that should be dropped once the 10-row cap is hit.
                    {"title": "T3", "rows": [{"id": "z", "title": "Z", "description": "z"}]},
                ],
            },
        },
    }
    enforce_meta_interactive_limits(payload)
    action = payload["interactive"]["action"]
    assert len(payload["interactive"]["body"]["text"]) <= META_LIMITS["body_text"]
    assert len(action["button"]) <= META_LIMITS["list_button_label"]
    total_rows = sum(len(s["rows"]) for s in action["sections"])
    assert total_rows <= META_LIMITS["list_rows_total"]
    for sec in action["sections"]:
        assert sec["rows"], "empty sections must be dropped (Meta rejects them)"
        assert len(sec["title"]) <= META_LIMITS["section_title"]
        for row in sec["rows"]:
            assert len(row["title"]) <= META_LIMITS["row_title"]
            assert len(row["description"]) <= META_LIMITS["row_description"]


def test_enforcer_clamps_buttons_count_and_titles():
    payload = {
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "hi"},
            "action": {"buttons": [
                {"type": "reply", "reply": {"id": str(i), "title": "T" * 40}} for i in range(6)
            ]},
        },
    }
    enforce_meta_interactive_limits(payload)
    buttons = payload["interactive"]["action"]["buttons"]
    assert len(buttons) <= META_LIMITS["buttons"]
    assert all(len(b["reply"]["title"]) <= META_LIMITS["button_title"] for b in buttons)


def test_enforcer_clamps_cta_display_text():
    payload = {
        "type": "interactive",
        "interactive": {
            "type": "cta_url",
            "body": {"text": "x"},
            "action": {"name": "cta_url", "parameters": {"display_text": "L" * 40, "url": "https://x"}},
        },
    }
    enforce_meta_interactive_limits(payload)
    assert len(payload["interactive"]["action"]["parameters"]["display_text"]) <= META_LIMITS["cta_display_text"]


def test_enforcer_is_a_noop_for_non_interactive_payloads():
    payload = {"type": "template", "template": {"name": "x"}}
    assert enforce_meta_interactive_limits(payload) == {"type": "template", "template": {"name": "x"}}


def test_every_interactive_template_produces_a_valid_payload():
    # Smoke test: build each interactive template and confirm the enforced
    # payload never violates a Meta limit, so adding a template can't silently
    # ship something Meta will reject.
    sample_branches = [{"id": f"b{i}", "name": "Name " * 5, "address": "Addr " * 30} for i in range(12)]
    sample_slots = [f"{h:02d}:00" for h in range(15)]
    for key, template in TEMPLATES.items():
        if "interactive_type" not in template:
            continue
        payload = build_whatsapp_interactive_payload(
            key, "9199",
            service_hint="", answer="A" * 2000, maps_url="https://x",
            detected_name="N", detected_phone="9", date="2026-06-22",
            raw_branches=sample_branches, raw_slots=sample_slots, branch_name="B",
        )
        interactive = payload["interactive"]
        assert len(interactive.get("body", {}).get("text", "")) <= META_LIMITS["body_text"]
        action = interactive.get("action", {})
        if "buttons" in action:
            assert len(action["buttons"]) <= META_LIMITS["buttons"]
        if "sections" in action:
            assert len(action["sections"]) <= META_LIMITS["list_sections"]
            assert sum(len(s["rows"]) for s in action["sections"]) <= META_LIMITS["list_rows_total"]
