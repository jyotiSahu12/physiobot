from physiobot.agent import Agent


class FakeProvider:
    """Returns scripted canonical assistant messages in order."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.seen = []

    def chat(self, messages, tools=None):
        self.seen.append(messages)
        return self.responses.pop(0)


class FakeSheets:
    def __init__(self):
        self.patients = []
        self.bookings = []

    def save_patient_info(self, name, phone, complaint, notes=""):
        self.patients.append((name, phone, complaint, notes))
        return "saved"

    def append_booking(self, name, phone, complaint, slot, event_id):
        self.bookings.append((name, phone, complaint, slot, event_id))

    def booking_exists(self, phone, slot):
        return any(b[1] == phone and b[3] == slot for b in self.bookings)


class FakeCalendar:
    def __init__(self, slots=None):
        self.slots = slots or ["10:00", "11:00"]

    def get_free_slots(self, date):
        return self.slots

    def create_event(self, name, phone, complaint, slot_datetime):
        return {"event_id": "evt123", "link": "http://cal/evt123"}


def _asst(content="", tool_calls=None):
    return {"role": "assistant", "content": content, "tool_calls": tool_calls or []}


def _call(cid, name, arguments):
    return {"id": cid, "name": name, "arguments": arguments}


def test_plain_reply(config):
    provider = FakeProvider([_asst("Hello! How can I help?")])
    agent = Agent(config, sheets=FakeSheets(), calendar=FakeCalendar(), provider=provider)
    reply = agent.respond([{"role": "user", "content": "hi"}])
    assert reply == "Hello! How can I help?"


def test_save_patient_info_tool(config):
    sheets = FakeSheets()
    provider = FakeProvider([
        _asst(tool_calls=[_call("c1", "save_patient_info",
              {"name": "Asha", "phone": "9199", "complaint": "knee pain"})]),
        _asst("Thanks Asha, noted your knee pain."),
    ])
    agent = Agent(config, sheets=sheets, calendar=FakeCalendar(), provider=provider)
    reply = agent.respond([{"role": "user", "content": "I'm Asha, 9199, knee pain"}])
    assert sheets.patients == [("Asha", "9199", "knee pain", "")]
    assert "Asha" in reply


def test_booking_flow(config):
    sheets = FakeSheets()
    provider = FakeProvider([
        _asst(tool_calls=[_call("c1", "get_free_slots", {"date": "2030-01-10"})]),
        _asst(tool_calls=[_call("c2", "create_booking",
              {"name": "Ravi", "phone": "9100", "complaint": "back",
               "slot_datetime": "2030-01-10T10:00"})]),
        _asst("You're booked for Jan 10 at 10:00."),
    ])
    agent = Agent(config, sheets=sheets, calendar=FakeCalendar(), provider=provider)
    reply = agent.respond([{"role": "user", "content": "book me on Jan 10"}])
    assert sheets.bookings == [("Ravi", "9100", "back", "2030-01-10T10:00", "evt123")]
    assert "booked" in reply.lower()


def test_create_booking_is_idempotent(config):
    """If the model re-calls create_booking for the same phone+slot, no second
    calendar event / row is created."""
    sheets = FakeSheets()
    cal = FakeCalendar()
    create_calls = {"n": 0}
    orig = cal.create_event
    def counting(*a, **k):
        create_calls["n"] += 1
        return orig(*a, **k)
    cal.create_event = counting
    booking = {"name": "Ravi", "phone": "9100", "complaint": "back",
               "slot_datetime": "2030-01-10T10:00"}
    provider = FakeProvider([
        _asst(tool_calls=[_call("c1", "create_booking", booking)]),
        _asst(tool_calls=[_call("c2", "create_booking", booking)]),  # duplicate
        _asst("Done."),
    ])
    agent = Agent(config, sheets=sheets, calendar=cal, provider=provider)
    agent.respond([{"role": "user", "content": "book"}])
    assert create_calls["n"] == 1
    assert len(sheets.bookings) == 1


def test_tool_result_threads_tool_call_id(config):
    """The tool result message must carry the originating call id (Groq needs it)."""
    provider = FakeProvider([
        _asst(tool_calls=[_call("call_xyz", "get_free_slots", {"date": "2030-01-10"})]),
        _asst("Here are the times."),
    ])
    agent = Agent(config, sheets=FakeSheets(), calendar=FakeCalendar(), provider=provider)
    agent.respond([{"role": "user", "content": "slots?"}])
    # second chat call saw the tool result with the matching id
    tool_msgs = [m for m in provider.seen[1] if m.get("role") == "tool"]
    assert tool_msgs and tool_msgs[0]["tool_call_id"] == "call_xyz"


def test_normalize_args_unwraps_single_key_dict():
    out = Agent._normalize_args({"complaint": {"complaint": "knee pain"}, "name": "Asha"})
    assert out == {"complaint": "knee pain", "name": "Asha"}


def test_normalize_args_joins_list():
    out = Agent._normalize_args({"complaint": ["knee", "back"]})
    assert out == {"complaint": "knee, back"}


def test_dispatch_cleans_nested_dict_arg(config):
    """Reproduces the real qwen2.5 quirk: complaint wrapped in a single-key dict."""
    sheets = FakeSheets()
    provider = FakeProvider([
        _asst(tool_calls=[_call("c1", "save_patient_info",
              {"name": "Asha", "phone": "9876543210",
               "complaint": {"complaint": "knee pain"}})]),
        _asst("Noted."),
    ])
    agent = Agent(config, sheets=sheets, calendar=FakeCalendar(), provider=provider)
    agent.respond([{"role": "user", "content": "hi"}])
    assert sheets.patients == [("Asha", "9876543210", "knee pain", "")]
