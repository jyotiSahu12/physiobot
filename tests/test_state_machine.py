from unittest.mock import MagicMock
import pytest
from physiobot.state_machine import StateMachine


@pytest.fixture
def mock_sheets():
    sheets = MagicMock()
    sheets.booking_exists.return_value = False
    return sheets


@pytest.fixture
def mock_calendar():
    calendar = MagicMock()
    calendar.get_free_slots.return_value = ["10:00", "11:00"]
    calendar.create_event.return_value = {"event_id": "event_123"}
    return calendar


def test_state_machine_red_flag(config, tmp_path, mock_sheets, mock_calendar):
    sm = StateMachine(config, db_path=tmp_path / "sm.db", sheets_client=mock_sheets, calendar_client=mock_calendar)
    
    # User sends a query containing a red flag
    template, params = sm.process_turn("911", "book_appointment", {"full_name": "Asha"}, ["chest pain"])
    
    assert template == "red_flag_alert"
    assert "urgent medical attention" in params["red_flag_bot_response"]
    
    # Session state should transition to HUMAN_HANDOFF
    status, slots = sm.get_session("911")
    assert status == "HUMAN_HANDOFF"


def test_state_machine_faq_price_answered_inline_from_metadata(config, tmp_path, mock_sheets, mock_calendar):
    """Price/hours/etc. are answered with clinic-approved canned copy and the
    conversation continues — they don't break off into a full handoff."""
    sm = StateMachine(config, db_path=tmp_path / "sm.db", sheets_client=mock_sheets, calendar_client=mock_calendar)
    template, params = sm.process_turn("p1", "ask_price", {}, [])

    assert template == "faq_response"
    assert params["answer"] == sm.kb.response_template("unknown_price")
    assert params["answer"]  # not empty
    status, slots = sm.get_session("p1")
    assert status != "HUMAN_HANDOFF"


def test_state_machine_therapist_request_answered_inline_not_handoff(config, tmp_path, mock_sheets, mock_calendar):
    """Per the new metadata's team.specific_therapist_booking_rule: acknowledge
    and continue, don't hard-stop the conversation."""
    sm = StateMachine(config, db_path=tmp_path / "sm.db", sheets_client=mock_sheets, calendar_client=mock_calendar)
    template, params = sm.process_turn("p2", "ask_therapist_details", {}, [])

    assert template == "faq_response"
    assert params["answer"] == sm.kb.response_template("specific_therapist_request")
    status, slots = sm.get_session("p2")
    assert status != "HUMAN_HANDOFF"


def test_state_machine_ask_location_includes_tappable_maps_link(config, tmp_path, mock_sheets, mock_calendar):
    """ask_location gets the canned address copy plus a tappable Google Maps
    deep link (no API key needed), unlike the other plain-text FAQ intents."""
    sm = StateMachine(config, db_path=tmp_path / "sm.db", sheets_client=mock_sheets, calendar_client=mock_calendar)
    template, params = sm.process_turn("p3", "ask_location", {}, [])

    assert template == "location_with_map"
    assert params["answer"] == sm.kb.response_template("hsr_address")
    assert params["maps_url"] == sm.kb.maps_url
    assert params["maps_url"].startswith("https://www.google.com/maps/search/?api=1&query=")
    status, slots = sm.get_session("p3")
    assert status != "HUMAN_HANDOFF"


def test_state_machine_cancel_intent_still_hands_off(config, tmp_path, mock_sheets, mock_calendar):
    sm = StateMachine(config, db_path=tmp_path / "sm.db", sheets_client=mock_sheets, calendar_client=mock_calendar)
    template, params = sm.process_turn("p3", "cancel_appointment", {}, [])

    assert template == "human_handoff"
    status, slots = sm.get_session("p3")
    assert status == "HUMAN_HANDOFF"


def test_state_machine_slot_filling_flow(config, tmp_path, mock_sheets, mock_calendar):
    sm = StateMachine(config, db_path=tmp_path / "sm.db", sheets_client=mock_sheets, calendar_client=mock_calendar)
    phone = "12345"

    # Step 1: Greeting
    template, params = sm.process_turn(phone, "greeting", {}, [])
    assert template == "welcome_greeting"
    assert params["clinic_name"] == sm.kb.clinic_name
    
    # Step 2: User provides name & phone
    template, params = sm.process_turn(phone, "book_appointment", {"full_name": "Asha", "phone_number": "12345"}, [])
    # Next missing slot is consent
    assert template == "request_consent"

    # Step 2b: User agrees to consent
    template, params = sm.process_turn(phone, "share_symptoms", {"consent_given": "yes"}, [])
    # Next missing slot is main_problem / complaint
    assert template == "request_complaint"
    assert params["name"] == "Asha"

    # Step 3: User provides complaint
    template, params = sm.process_turn(phone, "share_symptoms", {"main_problem": "knee pain"}, [])
    # Next missing slot is pain_area
    assert template == "request_pain_area"

    # Step 4: User provides pain_area, duration, score, and mode
    template, params = sm.process_turn(phone, "share_symptoms", {
        "pain_area": "knee",
        "pain_duration": "1-3 days",
        "pain_score": 5,
        "preferred_service_mode": "clinic_visit"
    }, [])
    
    # Now intake is complete:
    # 1. Sheets save_patient_info should be called
    mock_sheets.save_patient_info.assert_called_once_with("Asha", "12345", "knee pain")
    # 2. Next template should ask for date/time
    assert template == "request_date_time"

    # Step 5: User provides preferred date
    template, params = sm.process_turn(phone, "book_appointment", {"preferred_date": "2026-06-21"}, [])
    # Should call get_free_slots and show slots
    mock_calendar.get_free_slots.assert_called_once_with("2026-06-21")
    assert template == "show_slots"
    assert "10:00" in params["slots_list"]
    assert "11:00" in params["slots_list"]

    # Step 6: User selects a slot time
    template, params = sm.process_turn(phone, "book_appointment", {"preferred_time": "10:00"}, [])
    # Calendar/sheets still get the plain ISO id; only the patient-facing copy is humanized.
    mock_calendar.create_event.assert_called_once_with("Asha", "12345", "knee pain", "2026-06-21T10:00")
    mock_sheets.append_booking.assert_called_once_with("Asha", "12345", "knee pain", "2026-06-21T10:00", "event_123")
    assert template == "booking_confirmed"
    assert params["date_time"] == "Sunday, June 21, 2026 at 10:00 AM"

    status, slots = sm.get_session(phone)
    assert status == "CONFIRMED"


def test_state_machine_ignores_hallucinated_date_during_intake(config, tmp_path, mock_sheets, mock_calendar):
    """An LLM can "helpfully" guess a preferred_date on a turn where the patient
    never mentioned one (e.g. defaulting to tomorrow just because the
    conversation is about booking). The bot must still explicitly ask for a
    date once intake completes, instead of silently booking against the
    guessed value."""
    sm = StateMachine(config, db_path=tmp_path / "sm.db", sheets_client=mock_sheets, calendar_client=mock_calendar)
    phone = "12345"

    sm.process_turn(phone, "greeting", {}, [])
    sm.process_turn(phone, "book_appointment", {"full_name": "Asha", "phone_number": "12345"}, [])
    sm.process_turn(phone, "share_symptoms", {"consent_given": "yes"}, [])
    sm.process_turn(phone, "share_symptoms", {"main_problem": "knee pain"}, [])

    # The complaint turn's NLU also (incorrectly) returns a hallucinated date.
    template, params = sm.process_turn(phone, "share_symptoms", {
        "pain_area": "knee",
        "pain_duration": "1-3 days",
        "pain_score": 6,
        "preferred_service_mode": "clinic_visit",
        "preferred_date": "2026-06-22",  # never actually asked for or mentioned
    }, [])

    assert template == "request_date_time"
    status, slots = sm.get_session(phone)
    assert slots.get("preferred_date") is None
    mock_calendar.get_free_slots.assert_not_called()


def test_state_machine_date_change_while_awaiting_slot_selection_is_honored(config, tmp_path, mock_sheets, mock_calendar):
    """A patient typing a different date while slots are displayed (instead of
    tapping a time) must switch the booking to that date, not keep re-showing
    the original date's slots."""
    sm = StateMachine(config, db_path=tmp_path / "sm.db", sheets_client=mock_sheets, calendar_client=mock_calendar)
    phone = "12345"

    sm.process_turn(phone, "greeting", {}, [])
    sm.process_turn(phone, "book_appointment", {"full_name": "Asha", "phone_number": "12345"}, [])
    sm.process_turn(phone, "share_symptoms", {"consent_given": "yes"}, [])
    sm.process_turn(phone, "share_symptoms", {"main_problem": "knee pain"}, [])
    sm.process_turn(phone, "share_symptoms", {
        "pain_area": "knee", "pain_duration": "1-3 days", "pain_score": 6,
        "preferred_service_mode": "clinic_visit",
    }, [])
    template, params = sm.process_turn(phone, "book_appointment", {"preferred_date": "2026-06-22"}, [])
    assert template == "show_slots"
    assert params["date"] == "Monday, June 22, 2026"

    # Patient asks for a different date instead of picking a time slot.
    template, params = sm.process_turn(phone, "book_appointment", {"preferred_date": "2026-06-23"}, [])
    assert template == "show_slots"
    assert params["date"] == "Tuesday, June 23, 2026"
    mock_calendar.get_free_slots.assert_called_with("2026-06-23")


def test_state_machine_confirmed_session_survives_misclassified_greeting(config, tmp_path, mock_sheets, mock_calendar):
    """A "thank you" that the NLU loosely classifies as "greeting" must not
    wipe the confirmed booking and reopen name confirmation — only an explicit
    "book_appointment" intent should start a fresh intake after a booking."""
    sm = StateMachine(config, db_path=tmp_path / "sm.db", sheets_client=mock_sheets, calendar_client=mock_calendar)
    phone = "9988"
    sm.save_session(phone, "CONFIRMED", {
        "full_name": "Naman", "phone_number": phone, "main_problem": "lower back pain",
        "preferred_date": "2026-06-22", "preferred_time": "13:00", "profile_name_detected": "Naman",
    })

    template, params = sm.process_turn(phone, "greeting", {}, [])

    assert template == "post_booking_chat"
    assert params["date_time"] == "Monday, June 22, 2026 at 1:00 PM"
    status, slots = sm.get_session(phone)
    assert status == "CONFIRMED"
    assert slots["full_name"] == "Naman"


def test_state_machine_confirmed_session_explicit_new_booking_resets_intake(config, tmp_path, mock_sheets, mock_calendar):
    sm = StateMachine(config, db_path=tmp_path / "sm.db", sheets_client=mock_sheets, calendar_client=mock_calendar)
    phone = "9988"
    sm.save_session(phone, "CONFIRMED", {
        "full_name": "Naman", "phone_number": phone, "main_problem": "lower back pain",
        "preferred_date": "2026-06-22", "preferred_time": "13:00",
    })

    template, params = sm.process_turn(phone, "book_appointment", {}, [])

    status, slots = sm.get_session(phone)
    assert status == "COLLECTING_INTAKE"
    assert "full_name" not in slots


def test_state_machine_consent_declined_routes_to_handoff(config, tmp_path, mock_sheets, mock_calendar):
    sm = StateMachine(config, db_path=tmp_path / "sm.db", sheets_client=mock_sheets, calendar_client=mock_calendar)
    phone = "5555"

    sm.process_turn(phone, "greeting", {}, [])
    sm.process_turn(phone, "book_appointment", {"full_name": "Bala", "phone_number": "5555"}, [])

    template, params = sm.process_turn(phone, "share_symptoms", {"consent_given": "no"}, [])

    assert template == "consent_declined"
    status, slots = sm.get_session(phone)
    assert status == "HUMAN_HANDOFF"


def test_state_machine_service_recommendation_hint(config, tmp_path, mock_sheets, mock_calendar):
    sm = StateMachine(config, db_path=tmp_path / "sm.db", sheets_client=mock_sheets, calendar_client=mock_calendar)
    phone = "6666"

    sm.process_turn(phone, "greeting", {}, [])
    sm.process_turn(phone, "book_appointment", {"full_name": "Ravi", "phone_number": "6666"}, [])
    sm.process_turn(phone, "share_symptoms", {"consent_given": "yes"}, [])

    template, params = sm.process_turn(phone, "share_symptoms", {"main_problem": "I had a knee replacement surgery"}, [])

    assert template == "request_pain_area"
    assert "Post-operative physiotherapy" in params["service_hint"]


def test_state_machine_service_recommendation_hint_survives_opportunistic_slot_fill(config, tmp_path, mock_sheets, mock_calendar):
    """If the parser fills pain_area in the same turn as main_problem (as the LLM
    often does), request_pain_area is skipped entirely — the hint must attach to
    whichever question is actually asked next instead of being lost."""
    sm = StateMachine(config, db_path=tmp_path / "sm.db", sheets_client=mock_sheets, calendar_client=mock_calendar)
    phone = "7777"

    sm.process_turn(phone, "greeting", {}, [])
    sm.process_turn(phone, "book_appointment", {"full_name": "Meena", "phone_number": "7777"}, [])
    sm.process_turn(phone, "share_symptoms", {"consent_given": "yes"}, [])

    # main_problem and pain_area both arrive in the same turn.
    template, params = sm.process_turn(
        phone, "share_symptoms", {"main_problem": "knee replacement surgery", "pain_area": "knee"}, []
    )

    assert template == "request_pain_duration"
    assert "Post-operative physiotherapy" in params["service_hint"]

    # The hint should not repeat on the next turn.
    template, params = sm.process_turn(phone, "share_symptoms", {"pain_duration": "1-3 days"}, [])
    assert template == "request_pain_score"
    assert params["service_hint"] == ""


def test_state_machine_restart_and_inactivity_reset(config, tmp_path, mock_sheets, mock_calendar):
    import sqlite3
    import time
    
    sm = StateMachine(config, db_path=tmp_path / "sm.db", sheets_client=mock_sheets, calendar_client=mock_calendar)
    phone = "9988"
    
    # Pre-populate session and slots
    sm.save_session(phone, "AWAITING_SLOT_SELECTION", {"full_name": "Naman", "pain_score": 8})
    
    # Pre-populate messages
    with sqlite3.connect(sm.db_path) as conn:
        conn.execute("INSERT INTO messages (phone, role, content, ts) VALUES (?, 'user', 'my back hurts', ?)", (phone, time.time() - 10))
        conn.execute("INSERT INTO messages (phone, role, content, ts) VALUES (?, 'user', 'restart', ?)", (phone, time.time()))
        
    # Process turn with restart message present
    template, params = sm.process_turn(phone, "greeting", {}, [])
    
    assert template == "welcome_greeting"
    status, slots = sm.get_session(phone)
    assert status == "COLLECTING_INTAKE"
    assert slots == {}
    
    # Check that messages are deleted
    with sqlite3.connect(sm.db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM messages WHERE phone = ?", (phone,)).fetchone()
        assert row[0] == 0

    # Test Inactivity Reset
    sm.save_session(phone, "AWAITING_SLOT_SELECTION", {"full_name": "Naman"})
    # Manually backdate updated_at to > 4 hours ago
    with sqlite3.connect(sm.db_path) as conn:
        conn.execute("UPDATE sessions SET updated_at = ? WHERE phone = ?", (time.time() - 15000, phone))
        # Insert a new message
        conn.execute("INSERT INTO messages (phone, role, content, ts) VALUES (?, 'user', 'hello', ?)", (phone, time.time()))
        
    # Process turn after long inactivity
    template, params = sm.process_turn(phone, "greeting", {}, [])
    
    status, slots = sm.get_session(phone)
    assert status == "COLLECTING_INTAKE" # Transitioned from START because of greeting
    # phone_number is always re-derived from the WhatsApp sender id, even on a fresh session
    assert slots == {"phone_number": phone}

    # Check that messages are deleted
    with sqlite3.connect(sm.db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM messages WHERE phone = ?", (phone,)).fetchone()
        assert row[0] == 0


def test_state_machine_profile_name_offered_for_confirmation(config, tmp_path, mock_sheets, mock_calendar):
    sm = StateMachine(config, db_path=tmp_path / "sm.db", sheets_client=mock_sheets, calendar_client=mock_calendar)
    phone = "8001"

    sm.process_turn(phone, "greeting", {}, [], profile_name="Asha Verma")

    template, params = sm.process_turn(phone, "book_appointment", {}, [], profile_name="Asha Verma")

    assert template == "confirm_details"
    assert params["detected_name"] == "Asha Verma"
    assert params["detected_phone"] == phone
    # phone is taken from the WhatsApp sender id, never asked as free text
    status, slots = sm.get_session(phone)
    assert slots["phone_number"] == phone


def test_state_machine_confirm_details_yes_adopts_profile_name(config, tmp_path, mock_sheets, mock_calendar):
    sm = StateMachine(config, db_path=tmp_path / "sm.db", sheets_client=mock_sheets, calendar_client=mock_calendar)
    phone = "8002"

    sm.process_turn(phone, "greeting", {}, [], profile_name="Asha Verma")
    sm.process_turn(phone, "book_appointment", {}, [], profile_name="Asha Verma")  # -> confirm_details

    # User taps "Yes, that's right" — an interactive reply, no NLU involved
    template, params = sm.process_turn(
        phone, "interactive_reply", {}, [], interactive_id="yes", profile_name="Asha Verma"
    )

    # Confirmed in the same turn, flow proceeds straight to the next missing slot (consent)
    assert template == "request_consent"
    status, slots = sm.get_session(phone)
    assert slots["full_name"] == "Asha Verma"
    assert slots["details_confirmed"] == "yes"


def test_state_machine_confirm_details_no_falls_back_to_manual_name(config, tmp_path, mock_sheets, mock_calendar):
    sm = StateMachine(config, db_path=tmp_path / "sm.db", sheets_client=mock_sheets, calendar_client=mock_calendar)
    phone = "8003"

    sm.process_turn(phone, "greeting", {}, [], profile_name="Wrong Name")
    sm.process_turn(phone, "book_appointment", {}, [], profile_name="Wrong Name")  # -> confirm_details

    template, params = sm.process_turn(
        phone, "interactive_reply", {}, [], interactive_id="no", profile_name="Wrong Name"
    )
    assert template == "request_full_name"

    # Manual name now works as free text via the normal NLU slot
    template, params = sm.process_turn(phone, "share_symptoms", {"full_name": "Real Name"}, [], profile_name="Wrong Name")
    assert template == "request_consent"
    status, slots = sm.get_session(phone)
    assert slots["full_name"] == "Real Name"


def test_state_machine_no_profile_name_skips_confirmation(config, tmp_path, mock_sheets, mock_calendar):
    sm = StateMachine(config, db_path=tmp_path / "sm.db", sheets_client=mock_sheets, calendar_client=mock_calendar)
    phone = "8004"

    sm.process_turn(phone, "greeting", {}, [])
    template, params = sm.process_turn(phone, "book_appointment", {}, [])

    assert template == "request_full_name"


def test_state_machine_interactive_reply_never_misassigned_to_wrong_slot(config, tmp_path, mock_sheets, mock_calendar):
    """Regression test for the reported bug: a list reply like '1-3 days' must
    only ever be assigned to pain_duration, never guessed into pain_score or a
    date, regardless of how an NLU layer might have read that text out of context."""
    sm = StateMachine(config, db_path=tmp_path / "sm.db", sheets_client=mock_sheets, calendar_client=mock_calendar)
    phone = "8005"

    sm.process_turn(phone, "greeting", {}, [], profile_name="Ravi")
    sm.process_turn(phone, "book_appointment", {}, [], profile_name="Ravi")
    sm.process_turn(phone, "interactive_reply", {}, [], interactive_id="yes", profile_name="Ravi")  # confirm details
    sm.process_turn(phone, "interactive_reply", {}, [], interactive_id="yes")  # consent
    sm.process_turn(phone, "share_symptoms", {"main_problem": "back pain"}, [])  # -> pain_area

    # The bot is now waiting on pain_area; an interactive reply must land there,
    # never on pain_score or preferred_date even though "1-3 days" looks numeric.
    template, params = sm.process_turn(phone, "interactive_reply", {}, [], interactive_id="lower back")
    assert template == "request_pain_duration"

    template, params = sm.process_turn(phone, "interactive_reply", {}, [], interactive_id="1-3 days")
    assert template == "request_pain_score"

    status, slots = sm.get_session(phone)
    assert slots["pain_area"] == "lower back"
    assert slots["pain_duration"] == "1-3 days"
    assert slots.get("pain_score") is None
    assert slots.get("preferred_date") is None


def test_state_machine_no_slots_available_uses_dedicated_template(config, tmp_path, mock_sheets, mock_calendar):
    mock_calendar.get_free_slots.return_value = []
    sm = StateMachine(config, db_path=tmp_path / "sm.db", sheets_client=mock_sheets, calendar_client=mock_calendar)
    phone = "8006"

    sm.save_session(phone, "AWAITING_SLOT_SELECTION", {
        "full_name": "Ravi", "phone_number": phone, "main_problem": "knee pain",
    })
    template, params = sm.process_turn(phone, "book_appointment", {"preferred_date": "2026-06-21"}, [])

    assert template == "no_slots_available"
    assert params["date"] == "Sunday, June 21, 2026"
    # No sentence is stuffed into clinic_phone — it's a plain contact number
    assert "available" not in params["clinic_phone"].lower()


def test_state_machine_booking_failed_uses_dedicated_template(config, tmp_path, mock_sheets, mock_calendar):
    mock_calendar.create_event.side_effect = Exception("calendar down")
    sm = StateMachine(config, db_path=tmp_path / "sm.db", sheets_client=mock_sheets, calendar_client=mock_calendar)
    phone = "8007"

    sm.save_session(phone, "AWAITING_SLOT_SELECTION", {
        "full_name": "Ravi", "phone_number": phone, "main_problem": "knee pain", "preferred_date": "2026-06-21",
    })
    template, params = sm.process_turn(phone, "book_appointment", {"preferred_time": "10:00"}, [])

    assert template == "booking_failed"
    assert "failed" not in params["clinic_phone"].lower()

