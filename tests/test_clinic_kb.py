from physiobot.clinic_kb import ClinicKB


def make_kb(**overrides) -> ClinicKB:
    data = {
        "clinic_profile": {"brand_name": "Balance Plus"},
        "primary_branch": {
            "branch_name": "Balance Plus - HSR Layout",
            "contact": {"phone": {"value": "+917411692516", "display_value": "+91 74116 92516"}},
        },
        "triage_and_safety_guardrails": {
            "red_flag_symptoms": ["chest pain", "loss of consciousness"],
            "red_flag_bot_action": {"message": "Seek urgent medical attention."},
        },
        "customer_facing_response_templates": {
            "unknown_price": "We don't have confirmed pricing yet.",
        },
        "official_service_catalog": [
            {
                "service_id": "physiotherapy_services",
                "service_name": "Physiotherapy Services",
                "sub_services": [
                    {"sub_service_id": "post_operative_physiotherapy", "name": "Post-operative physiotherapy"},
                ],
            },
            {
                "service_id": "diet_and_nutrition",
                "service_name": "Diet and Nutrition",
                "officially_listed_sub_services": [
                    {"sub_service_id": "diabetes", "name": "Diabetes"},
                ],
            },
        ],
        "service_recommendation_logic": {
            "rules": [
                {
                    "trigger_terms": ["post surgery", "knee replacement"],
                    "recommend_service_id": "physiotherapy_services",
                    "recommend_sub_service_id": "post_operative_physiotherapy",
                },
                {
                    "trigger_terms": ["weight loss"],
                    "recommend_service_id": "diet_and_nutrition",
                },
            ]
        },
    }
    data.update(overrides)
    return ClinicKB(data)


def test_clinic_name_prefers_branch_name():
    assert make_kb().clinic_name == "Balance Plus - HSR Layout"


def test_clinic_name_falls_back_to_brand_when_no_branch():
    kb = make_kb(primary_branch={})
    assert kb.clinic_name == "Balance Plus"


def test_clinic_phone_prefers_display_value():
    assert make_kb().clinic_phone == "+91 74116 92516"


def test_maps_url_built_from_customer_facing_address():
    kb = make_kb(primary_branch={
        "branch_name": "Balance Plus - HSR Layout",
        "official_address": {"full_address_customer_facing": "Sector 7, HSR Layout, Bengaluru"},
    })
    assert kb.clinic_address == "Sector 7, HSR Layout, Bengaluru"
    assert kb.maps_url == (
        "https://www.google.com/maps/search/?api=1&query=Sector%207%2C%20HSR%20Layout%2C%20Bengaluru"
    )


def test_maps_url_empty_when_no_address():
    assert make_kb().maps_url == ""


def test_red_flag_accessors():
    kb = make_kb()
    assert "chest pain" in kb.red_flag_triggers
    assert kb.red_flag_message == "Seek urgent medical attention."


def test_red_flag_message_has_safe_default_when_missing():
    kb = make_kb(triage_and_safety_guardrails={})
    assert "urgent medical attention" in kb.red_flag_message.lower()


def test_response_template_lookup():
    kb = make_kb()
    assert kb.response_template("unknown_price") == "We don't have confirmed pricing yet."
    assert kb.response_template("missing_key", default="fallback") == "fallback"


def test_match_service_prefers_sub_service_name():
    match = make_kb().match_service("I had a knee replacement last week")
    assert match is not None
    assert match.service_id == "physiotherapy_services"
    assert match.sub_service_id == "post_operative_physiotherapy"
    assert match.service_name == "Post-operative physiotherapy"


def test_match_service_falls_back_to_top_level_name_without_sub_service():
    match = make_kb().match_service("I want help with weight loss")
    assert match is not None
    assert match.service_name == "Diet and Nutrition"


def test_match_service_handles_officially_listed_sub_services_key():
    # diabetes is nested under "officially_listed_sub_services", not "sub_services"
    kb = make_kb(service_recommendation_logic={
        "rules": [{
            "trigger_terms": ["diabetes diet"],
            "recommend_service_id": "diet_and_nutrition",
            "recommend_sub_service_id": "diabetes",
        }]
    })
    match = kb.match_service("I need a diabetes diet plan")
    assert match.service_name == "Diabetes"


def test_match_service_no_match_returns_none():
    assert make_kb().match_service("something unrelated entirely") is None


def test_match_service_empty_complaint_returns_none():
    assert make_kb().match_service("") is None


def test_graceful_with_empty_metadata():
    kb = ClinicKB({})
    assert kb.clinic_name == ""
    assert kb.clinic_phone == ""
    assert kb.red_flag_triggers == []
    assert kb.response_template("anything", default="x") == "x"
    assert kb.match_service("knee pain") is None
