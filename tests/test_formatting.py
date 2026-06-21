from physiobot.formatting import humanize_date, humanize_time, humanize_datetime


def test_humanize_date():
    assert humanize_date("2026-06-22") == "Monday, June 22, 2026"


def test_humanize_date_single_digit_day_has_no_leading_zero():
    assert humanize_date("2026-06-03") == "Wednesday, June 3, 2026"


def test_humanize_date_passes_through_unparseable_input():
    assert humanize_date("not-a-date") == "not-a-date"


def test_humanize_time_pm():
    assert humanize_time("13:00") == "1:00 PM"


def test_humanize_time_am_single_digit_hour_has_no_leading_zero():
    assert humanize_time("09:30") == "9:30 AM"


def test_humanize_time_midnight_and_noon():
    assert humanize_time("00:00") == "12:00 AM"
    assert humanize_time("12:00") == "12:00 PM"


def test_humanize_time_passes_through_unparseable_input():
    assert humanize_time("not-a-time") == "not-a-time"


def test_humanize_datetime():
    assert humanize_datetime("2026-06-22", "13:00") == "Monday, June 22, 2026 at 1:00 PM"
