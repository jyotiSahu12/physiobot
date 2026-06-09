"""Google Calendar access: list free slots and create appointment events.

Uses the same service account as Sheets. The target calendar must be shared
with the service-account email (permission: "Make changes to events").
Free slots are derived from clinic working hours minus existing busy events.
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build

from ..config import Config, get_config
from ..google_auth import load_credentials

SCOPES = ["https://www.googleapis.com/auth/calendar"]


@lru_cache(maxsize=1)
def _service():
    creds = load_credentials(SCOPES)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


class CalendarClient:
    def __init__(self, config: Config | None = None):
        self.config = config or get_config()
        self.tz = ZoneInfo(self.config.clinic.timezone)

    @property
    def service(self):
        return _service()

    def _parse_date(self, date_str: str) -> dt.date:
        return dt.date.fromisoformat(date_str)

    def _candidate_slots(self, day: dt.date) -> list[dt.datetime]:
        hours = self.config.hours
        if day.weekday() in hours.closed_weekdays:
            return []
        open_h, open_m = map(int, hours.open.split(":"))
        close_h, close_m = map(int, hours.close.split(":"))
        start = dt.datetime.combine(day, dt.time(open_h, open_m), tzinfo=self.tz)
        end = dt.datetime.combine(day, dt.time(close_h, close_m), tzinfo=self.tz)
        step = dt.timedelta(minutes=hours.slot_minutes)
        slots, cur = [], start
        while cur + step <= end:
            slots.append(cur)
            cur += step
        return slots

    def _busy_intervals(self, day: dt.date) -> list[tuple[dt.datetime, dt.datetime]]:
        start = dt.datetime.combine(day, dt.time.min, tzinfo=self.tz)
        end = start + dt.timedelta(days=1)
        events = (
            self.service.events()
            .list(
                calendarId=self.config.google.calendar_id,
                timeMin=start.isoformat(),
                timeMax=end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
            .get("items", [])
        )
        busy = []
        for ev in events:
            s = ev["start"].get("dateTime")
            e = ev["end"].get("dateTime")
            if s and e:
                busy.append((dt.datetime.fromisoformat(s), dt.datetime.fromisoformat(e)))
        return busy

    def get_free_slots(self, date_str: str) -> list[str]:
        """Return open slot start times for a day as 'HH:MM' strings."""
        day = self._parse_date(date_str)
        step = dt.timedelta(minutes=self.config.hours.slot_minutes)
        busy = self._busy_intervals(day)
        free = []
        now = dt.datetime.now(self.tz)
        for slot in self._candidate_slots(day):
            if slot < now:  # don't offer past slots
                continue
            slot_end = slot + step
            overlaps = any(slot < b_end and slot_end > b_start for b_start, b_end in busy)
            if not overlaps:
                free.append(slot.strftime("%H:%M"))
        return free

    def create_event(
        self, name: str, phone: str, complaint: str, slot_datetime: str
    ) -> dict:
        """Create an appointment. `slot_datetime` is ISO 'YYYY-MM-DDTHH:MM'."""
        start = dt.datetime.fromisoformat(slot_datetime).replace(tzinfo=self.tz)
        end = start + dt.timedelta(minutes=self.config.hours.slot_minutes)
        body = {
            "summary": f"Physio: {name}",
            "description": f"Patient: {name}\nPhone: {phone}\nComplaint: {complaint}",
            "start": {"dateTime": start.isoformat(), "timeZone": self.config.clinic.timezone},
            "end": {"dateTime": end.isoformat(), "timeZone": self.config.clinic.timezone},
        }
        ev = (
            self.service.events()
            .insert(calendarId=self.config.google.calendar_id, body=body)
            .execute()
        )
        return {"event_id": ev.get("id", ""), "link": ev.get("htmlLink", "")}
