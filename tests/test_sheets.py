from physiobot.tools.sheets import BOOKING_HEADERS, PATIENT_HEADERS, SheetsClient


class FakeWS:
    def __init__(self, rows):
        self.rows = rows
        self.appended = []
        self.updated = []

    def get_all_values(self):
        return self.rows

    def append_row(self, row):
        self.appended.append(row)
        self.rows.append(row)

    def update(self, rng, values):
        self.updated.append((rng, values))


def _client(config, rows):
    sc = SheetsClient(config)
    ws = FakeWS(rows)
    sc._worksheet = lambda title, headers: ws  # bypass real gspread
    return sc, ws


def test_empty_phone_is_not_saved(config):
    sc, ws = _client(config, [PATIENT_HEADERS])
    msg = sc.save_patient_info("Asha", "", "knee pain")
    assert "ask the patient for their phone" in msg.lower()
    assert ws.appended == []


def test_new_phone_appends(config):
    sc, ws = _client(config, [PATIENT_HEADERS])
    msg = sc.save_patient_info("Asha", "9199", "knee pain")
    assert msg.startswith("Saved")
    assert len(ws.appended) == 1 and ws.appended[0][1:4] == ["Asha", "9199", "knee pain"]


def test_existing_phone_updates_not_duplicates(config):
    rows = [PATIENT_HEADERS, ["2026-01-01", "Asha", "9199", "knee pain", ""]]
    sc, ws = _client(config, rows)
    msg = sc.save_patient_info("Asha", "9199", "knee and back pain")
    assert msg.startswith("Updated")
    assert ws.appended == []                      # no duplicate row
    assert ws.updated and ws.updated[0][0] == "A2:E2"


def test_append_booking_includes_branch_id(config):
    sc, ws = _client(config, [BOOKING_HEADERS])
    sc.append_booking("Asha", "9199", "knee pain", "2026-06-22T10:00", "evt_1", "balanceplus_hsr_layout_sector_7")
    assert ws.appended[0][1:] == ["Asha", "9199", "knee pain", "2026-06-22T10:00", "evt_1", "balanceplus_hsr_layout_sector_7"]


def test_last_branch_for_phone_returns_most_recent_match(config):
    rows = [
        BOOKING_HEADERS,
        ["2026-01-01", "Asha", "9199", "knee pain", "2026-01-05T10:00", "evt_1", "balanceplus_koramangala_ejipura"],
        ["2026-02-01", "Asha", "9199", "knee pain", "2026-02-05T10:00", "evt_2", "balanceplus_hsr_layout_sector_7"],
    ]
    sc, ws = _client(config, rows)
    assert sc.last_branch_for_phone("9199") == "balanceplus_hsr_layout_sector_7"


def test_last_branch_for_phone_returns_none_for_new_patient(config):
    sc, ws = _client(config, [BOOKING_HEADERS])
    assert sc.last_branch_for_phone("9199") is None


def test_last_branch_for_phone_returns_none_for_rows_without_branch_column(config):
    # Rows written before the BranchId column existed.
    rows = [BOOKING_HEADERS, ["2026-01-01", "Asha", "9199", "knee pain", "2026-01-05T10:00", "evt_1"]]
    sc, ws = _client(config, rows)
    assert sc.last_branch_for_phone("9199") is None
