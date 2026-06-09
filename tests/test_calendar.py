import datetime as dt
from zoneinfo import ZoneInfo

from physiobot.tools.calendar import CalendarClient

FUTURE_DAY = "2030-01-10"  # a Thursday, far in the future
TZ = ZoneInfo("Asia/Kolkata")


def _slot(h):
    return dt.datetime(2030, 1, 10, h, 0, tzinfo=TZ)


def test_candidate_slots(config):
    cal = CalendarClient(config)
    slots = cal._candidate_slots(dt.date(2030, 1, 10))
    # 10:00-13:00, 60 min slots -> 10, 11, 12
    assert [s.strftime("%H:%M") for s in slots] == ["10:00", "11:00", "12:00"]


def test_closed_weekday_has_no_slots(config):
    cal = CalendarClient(config)
    # 2030-01-13 is a Sunday (closed_weekdays=[6])
    assert cal._candidate_slots(dt.date(2030, 1, 13)) == []


def test_free_slots_all_open(config, monkeypatch):
    cal = CalendarClient(config)
    monkeypatch.setattr(cal, "_busy_intervals", lambda day: [])
    assert cal.get_free_slots(FUTURE_DAY) == ["10:00", "11:00", "12:00"]


def test_free_slots_excludes_busy(config, monkeypatch):
    cal = CalendarClient(config)
    monkeypatch.setattr(cal, "_busy_intervals", lambda day: [(_slot(11), _slot(12))])
    assert cal.get_free_slots(FUTURE_DAY) == ["10:00", "12:00"]
