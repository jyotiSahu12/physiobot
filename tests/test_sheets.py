from physiobot.tools.sheets import PATIENT_HEADERS, SheetsClient


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
