"""Google Sheets access: append patient leads and booking rows.

Uses a Google service account. The target spreadsheet must be shared with the
service-account email (Editor). Two tabs are used: Patients and Bookings; both
are created with headers on first use if missing.
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache

import gspread

from ..config import Config, get_config
from ..google_auth import load_credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

PATIENT_HEADERS = ["Timestamp", "Name", "Phone", "Complaint", "Notes"]
BOOKING_HEADERS = ["Timestamp", "Name", "Phone", "Complaint", "Slot", "EventId"]


@lru_cache(maxsize=1)
def _client() -> gspread.Client:
    return gspread.authorize(load_credentials(SCOPES))


class SheetsClient:
    def __init__(self, config: Config | None = None):
        self.config = config or get_config()
        self._spreadsheet = None

    @property
    def spreadsheet(self):
        if self._spreadsheet is None:
            gc = _client()
            self._spreadsheet = gc.open_by_key(self.config.google.sheet_id)
        return self._spreadsheet

    def _worksheet(self, title: str, headers: list[str]):
        try:
            ws = self.spreadsheet.worksheet(title)
        except gspread.WorksheetNotFound:
            ws = self.spreadsheet.add_worksheet(title=title, rows=1000, cols=len(headers))
            ws.append_row(headers)
        return ws

    def save_patient_info(self, name: str, phone: str, complaint: str, notes: str = "") -> str:
        ws = self._worksheet(self.config.google.patients_tab, PATIENT_HEADERS)
        ws.append_row([_now(), name, phone, complaint, notes])
        return f"Saved patient details for {name}."

    def append_booking(
        self, name: str, phone: str, complaint: str, slot: str, event_id: str
    ) -> None:
        ws = self._worksheet(self.config.google.bookings_tab, BOOKING_HEADERS)
        ws.append_row([_now(), name, phone, complaint, slot, event_id])


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")
