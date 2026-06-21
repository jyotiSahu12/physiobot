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
BOOKING_HEADERS = ["Timestamp", "Name", "Phone", "Complaint", "Slot", "EventId", "BranchId"]


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
        # Guard: don't write half-collected leads (models often call too early).
        if not str(phone).strip():
            return "Not saved — ask the patient for their phone number first, then save."
        ws = self._worksheet(self.config.google.patients_tab, PATIENT_HEADERS)
        row = [_now(), name, phone, complaint, notes]
        # Idempotent: if this phone is already recorded, update that row instead
        # of appending a duplicate (LLMs may re-call this every turn).
        existing = ws.get_all_values()
        for i, r in enumerate(existing[1:], start=2):  # skip header; sheet rows are 1-based
            if len(r) >= 3 and r[2].strip() == str(phone).strip():
                ws.update(f"A{i}:E{i}", [row])
                return f"Updated patient details for {name}."
        ws.append_row(row)
        return f"Saved patient details for {name}."

    def append_booking(
        self, name: str, phone: str, complaint: str, slot: str, event_id: str, branch_id: str = ""
    ) -> None:
        ws = self._worksheet(self.config.google.bookings_tab, BOOKING_HEADERS)
        ws.append_row([_now(), name, phone, complaint, slot, event_id, branch_id])

    def booking_exists(self, phone: str, slot: str) -> bool:
        """True if this phone already has this slot booked (avoid duplicate
        calendar events when the model re-calls create_booking)."""
        ws = self._worksheet(self.config.google.bookings_tab, BOOKING_HEADERS)
        for r in ws.get_all_values()[1:]:  # skip header
            if len(r) >= 5 and r[2].strip() == str(phone).strip() and r[4].strip() == str(slot).strip():
                return True
        return False

    def last_branch_for_phone(self, phone: str) -> str | None:
        """The branch_id of this patient's most recent booking, so a returning
        patient can be offered "book the same branch again?" instead of being
        asked to choose from scratch every time. Returns None for a new
        patient, or for rows written before the BranchId column existed."""
        ws = self._worksheet(self.config.google.bookings_tab, BOOKING_HEADERS)
        last_branch_id = None
        for r in ws.get_all_values()[1:]:  # skip header; sheet is append-only, so last match wins
            if len(r) >= 7 and r[2].strip() == str(phone).strip() and r[6].strip():
                last_branch_id = r[6].strip()
        return last_branch_id


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")
