import datetime as dt

from physiobot.parser import Parser, parse_natural_date, parse_natural_time, parse_time_of_day


class StubProvider:
    def __init__(self, content):
        self.content = content

    def chat(self, messages):
        return {"role": "assistant", "content": self.content}


def test_parser_fallback_classifies_contact_intent(config):
    provider = StubProvider("Not JSON at all")
    parser = Parser(config, provider=provider)
    result = parser.parse_message([{"role": "user", "content": "what is your contact number?"}])
    assert result["intent"] == "ask_contact"


def test_parser_fallback_classifies_combined_location_and_contact_as_location(config):
    # Only one intent label can come back for a compound question; location
    # wins so state_machine can fold the phone number into that answer too.
    provider = StubProvider("Not JSON at all")
    parser = Parser(config, provider=provider)
    result = parser.parse_message([{"role": "user", "content": "what's the location and contact?"}])
    assert result["intent"] == "ask_location"


def test_parser_normal_json(config):
    json_response = """
    {
      "intent": "book_appointment",
      "slots": {
        "full_name": "Asha",
        "phone_number": "9999",
        "main_problem": "knee pain"
      },
      "red_flags_detected": []
    }
    """
    provider = StubProvider(json_response)
    parser = Parser(config, provider=provider)
    result = parser.parse_message([])

    assert result["intent"] == "book_appointment"
    assert result["slots"]["full_name"] == "Asha"
    assert result["slots"]["phone_number"] == "9999"
    assert result["slots"]["main_problem"] == "knee pain"
    assert result["red_flags_detected"] == []


def test_parser_malformed_json_wrappers(config):
    # LLM might occasionally wrap JSON in markdown block code ```json ... ```
    wrapped_response = """
    Here is the parsed intent:
    ```json
    {
      "intent": "greeting",
      "slots": {},
      "red_flags_detected": ["chest pain"]
    }
    ```
    hope that helps!
    """
    provider = StubProvider(wrapped_response)
    parser = Parser(config, provider=provider)
    result = parser.parse_message([])

    assert result["intent"] == "greeting"
    assert result["red_flags_detected"] == ["chest pain"]


def test_parser_failure_fallback(config):
    # If the provider completely fails or returns unparseable text
    provider = StubProvider("Not JSON at all")
    parser = Parser(config, provider=provider)
    result = parser.parse_message([])

    assert result["intent"] == "other"
    assert result["slots"] == {}
    assert result["red_flags_detected"] == []


def _today_iso(config):
    from zoneinfo import ZoneInfo
    return dt.datetime.now(ZoneInfo(config.clinic.timezone)).date().isoformat()


def _next_occurrence_iso(config, month, day):
    """The next future date matching month/day (this year, or next if already
    passed) — mirrors parse_natural_date so these tests aren't time-bombs that
    break once the hardcoded date slips into the past."""
    from zoneinfo import ZoneInfo
    today = dt.datetime.now(ZoneInfo(config.clinic.timezone)).date()
    cand = dt.date(today.year, month, day)
    if cand < today:
        cand = dt.date(today.year + 1, month, day)
    return cand.isoformat()


def test_parser_fallback_resolves_date_change_when_awaiting_date(config):
    # The bot just asked for a date and the LLM is unavailable — the regex
    # fallback must still resolve a spoken date like "23rd June" instead of
    # silently dropping it (the bug where the bot kept re-showing the old
    # date's slots after the patient asked for a different one).
    provider = StubProvider("Not JSON at all")
    parser = Parser(config, provider=provider)
    history = [
        {"role": "assistant", "content": "When would you like to come in?"},
        {"role": "user", "content": "Can I have appointment for 23rd June?"},
    ]
    result = parser.parse_message(history)
    assert result["slots"]["preferred_date"] == _next_occurrence_iso(config, 6, 23)


def test_parser_fallback_resolves_natural_when_with_time_of_day(config):
    # "today evening" / "tomorrow morning" — resolve both a date and a rough
    # time-of-day window so the bot can show the matching slots.
    provider = StubProvider("Not JSON at all")
    parser = Parser(config, provider=provider)
    history = [
        {"role": "assistant", "content": "When would you like to come in?"},
        {"role": "user", "content": "today evening or tomorrow morning works"},
    ]
    result = parser.parse_message(history)
    # earliest-mentioned day + time-of-day win: today + evening
    assert result["slots"]["preferred_date"] == _today_iso(config)
    assert result["slots"]["preferred_time_of_day"] == "evening"


def test_parser_fallback_bare_time_of_day_defaults_to_today(config):
    provider = StubProvider("Not JSON at all")
    parser = Parser(config, provider=provider)
    history = [
        {"role": "assistant", "content": "When would you like to come in?"},
        {"role": "user", "content": "evening please"},
    ]
    result = parser.parse_message(history)
    assert result["slots"]["preferred_date"] == _today_iso(config)
    assert result["slots"]["preferred_time_of_day"] == "evening"


def test_parser_fallback_resolves_time_when_awaiting_slot_pick(config):
    provider = StubProvider("Not JSON at all")
    parser = Parser(config, provider=provider)
    history = [
        {"role": "assistant", "content": "Available times for 2026-06-22:\nWhich time works best for you?"},
        {"role": "user", "content": "1pm works for me"},
    ]
    result = parser.parse_message(history)
    assert result["slots"]["preferred_time"] == "13:00"


def test_parser_fallback_prefers_date_over_time_when_both_possible(config):
    # While slots are shown, a free-text date should switch the booking date
    # rather than being misread as a time.
    provider = StubProvider("Not JSON at all")
    parser = Parser(config, provider=provider)
    history = [
        {"role": "assistant", "content": "Available times for 2026-06-22:\nWhich time works best for you?"},
        {"role": "user", "content": "Actually, can we do 23rd June instead?"},
    ]
    result = parser.parse_message(history)
    assert result["slots"]["preferred_date"] == _next_occurrence_iso(config, 6, 23)
    assert "preferred_time" not in result["slots"]


def test_parser_fallback_does_not_extract_date_outside_date_phase(config):
    # No date/time extraction should happen unless the bot is actually
    # waiting on a date or time — otherwise a stray mention of a month
    # anywhere in the conversation could get mistaken for a scheduling answer.
    provider = StubProvider("Not JSON at all")
    parser = Parser(config, provider=provider)
    history = [
        {"role": "assistant", "content": "Thanks Asha! What main problem or pain are you facing?"},
        {"role": "user", "content": "I've had knee pain since 23rd June"},
    ]
    result = parser.parse_message(history)
    assert "preferred_date" not in result["slots"]


def test_parse_natural_date_iso_passthrough():
    assert parse_natural_date("2026-06-25", dt.date(2026, 6, 21)) == "2026-06-25"


def test_parse_natural_date_relative_words():
    today = dt.date(2026, 6, 21)  # Sunday
    assert parse_natural_date("today", today) == "2026-06-21"
    assert parse_natural_date("tomorrow", today) == "2026-06-22"


def test_parse_natural_date_weekday_name_rolls_to_upcoming_occurrence():
    today = dt.date(2026, 6, 21)  # Sunday
    assert parse_natural_date("monday", today) == "2026-06-22"


def test_parse_natural_date_day_month_and_month_day_orderings():
    today = dt.date(2026, 6, 21)
    assert parse_natural_date("23rd June", today) == "2026-06-23"
    assert parse_natural_date("June 23", today) == "2026-06-23"


def test_parse_natural_date_rolls_to_next_year_when_date_already_passed():
    today = dt.date(2026, 6, 21)
    assert parse_natural_date("3rd January", today) == "2027-01-03"


def test_parse_natural_date_returns_none_when_no_date_present():
    assert parse_natural_date("I am having lower back pain", dt.date(2026, 6, 21)) is None


def test_parse_natural_time_handles_common_formats():
    assert parse_natural_time("1pm") == "13:00"
    assert parse_natural_time("13:00") == "13:00"
    assert parse_natural_time("9am") == "09:00"
    assert parse_natural_time("12am") == "00:00"
    assert parse_natural_time("no time mentioned here") is None


def test_parse_time_of_day_buckets_and_earliest_wins():
    assert parse_time_of_day("tomorrow morning") == "morning"
    assert parse_time_of_day("this afternoon") == "afternoon"
    assert parse_time_of_day("come by in the evening") == "evening"
    assert parse_time_of_day("tonight if possible") == "evening"
    # earliest-mentioned wins for an "or" answer
    assert parse_time_of_day("today evening or tomorrow morning") == "evening"
    assert parse_time_of_day("next Friday") is None
