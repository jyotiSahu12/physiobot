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


def test_state_machine_slot_filling_flow(config, tmp_path, mock_sheets, mock_calendar):
    sm = StateMachine(config, db_path=tmp_path / "sm.db", sheets_client=mock_sheets, calendar_client=mock_calendar)
    phone = "12345"

    # Step 1: Greeting
    template, params = sm.process_turn(phone, "greeting", {}, [])
    assert template == "welcome_greeting"
    assert params["clinic_name"] == config.clinic.name
    
    # Step 2: User provides name & phone
    template, params = sm.process_turn(phone, "book_appointment", {"full_name": "Asha", "phone_number": "12345"}, [])
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
    # Should create calendar event and write booking
    mock_calendar.create_event.assert_called_once_with("Asha", "12345", "knee pain", "2026-06-21T10:00")
    mock_sheets.append_booking.assert_called_once_with("Asha", "12345", "knee pain", "2026-06-21T10:00", "event_123")
    assert template == "booking_confirmed"
    assert params["date_time"] == "2026-06-21T10:00"

    status, slots = sm.get_session(phone)
    assert status == "CONFIRMED"


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
    assert slots == {}
    
    # Check that messages are deleted
    with sqlite3.connect(sm.db_path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM messages WHERE phone = ?", (phone,)).fetchone()
        assert row[0] == 0

