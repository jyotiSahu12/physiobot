from physiobot.templates import TEMPLATES, build_whatsapp_interactive_payload, format_template_text

# Meta hard limits for WhatsApp interactive messages — violating these gets
# the whole send rejected outright (e.g. "Total row count exceed max allowed
# count: 10"), which is exactly what happened with the original
# request_pain_area (13 rows) and request_pain_score (11 rows) templates.
MAX_LIST_ROWS_TOTAL = 10
MAX_LIST_SECTIONS = 10
MAX_BUTTONS = 3


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
        "show_slots", "9199", date="2026-06-22", slots_list="- 10:00\n- 11:00", raw_slots=["10:00", "11:00"]
    )
    body_text = payload["interactive"]["body"]["text"]
    assert "10:00" not in body_text
    assert "2026-06-22" in body_text


def test_show_slots_dev_fallback_text_still_includes_slots_list():
    # No native list UI in dev/no-Meta mode, so the times must still be visible.
    text = format_template_text("show_slots", date="2026-06-22", slots_list="- 10:00\n- 11:00")
    assert "10:00" in text


def test_request_pain_area_payload_stays_within_row_limit():
    payload = build_whatsapp_interactive_payload("request_pain_area", "9199", service_hint="")
    sections = payload["interactive"]["action"]["sections"]
    total_rows = sum(len(sec["rows"]) for sec in sections)
    assert total_rows <= MAX_LIST_ROWS_TOTAL
