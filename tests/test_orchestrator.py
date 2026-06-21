from physiobot.orchestrator import Orchestrator
from physiobot.store import Store


class StubParser:
    def __init__(self, intent="greeting", slots=None, red_flags=None):
        self.intent = intent
        self.slots = slots or {}
        self.red_flags = red_flags or []

    def parse_message(self, history):
        return {
            "intent": self.intent,
            "slots": self.slots,
            "red_flags_detected": self.red_flags,
        }


class StubStateMachine:
    def __init__(self, template="welcome_greeting", params=None):
        self.template = template
        self.params = params or {"clinic_name": "Test Clinic"}
        self.calls = []

    def process_turn(self, phone, intent, slots, red_flags, interactive_id=None, profile_name=None):
        self.calls.append({
            "phone": phone, "intent": intent, "slots": slots, "red_flags": red_flags,
            "interactive_id": interactive_id, "profile_name": profile_name,
        })
        return self.template, self.params


class RecordingOutbound:
    def __init__(self):
        self.sent = []
        self.templates_sent = []

    def send_text(self, to, text):
        self.sent.append((to, text))

    def send_template(self, to, template_key, **kwargs):
        self.templates_sent.append((to, template_key, kwargs))
        from physiobot.templates import format_template_text
        return format_template_text(template_key, **kwargs)


def test_handle_message_persists_and_sends(config, tmp_path):
    store = Store(tmp_path / "o.db")
    parser = StubParser(intent="greeting")
    sm = StubStateMachine(template="welcome_greeting", params={"clinic_name": "Physio Clinic"})
    out = RecordingOutbound()
    orch = Orchestrator(config, store=store, parser=parser, state_machine=sm, outbound=out)

    reply = orch.handle_message("9199", "hi")

    assert "Physio Clinic" in reply
    assert out.templates_sent == [("9199", "welcome_greeting", {"clinic_name": "Physio Clinic"})]
    # both user and assistant turns persisted
    assert store.history("9199") == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": reply},
    ]


def test_handle_message_interactive_reply_bypasses_parser(config, tmp_path):
    """Button/list replies must skip the NLU layer entirely — the option id is
    unambiguous, so there's nothing for the parser to add and no risk of it
    misreading the title text out of context."""
    store = Store(tmp_path / "o.db")

    class BoomParser:
        def parse_message(self, history):
            raise AssertionError("parser should not be called for interactive replies")

    sm = StubStateMachine(template="request_pain_duration", params={"service_hint": ""})
    out = RecordingOutbound()
    orch = Orchestrator(config, store=store, parser=BoomParser(), state_machine=sm, outbound=out)

    orch.handle_message("9199", "1-3 days", interactive_id="1-3 days", profile_name="Asha")

    assert sm.calls == [{
        "phone": "9199", "intent": "interactive_reply", "slots": {}, "red_flags": [],
        "interactive_id": "1-3 days", "profile_name": "Asha",
    }]


def test_handle_message_dedupes_duplicate_message_id(config, tmp_path):
    """Meta retries a webhook until it gets a 200, so the same message can
    arrive twice — the second delivery must be dropped, not re-answered or
    (worse) re-booked."""
    store = Store(tmp_path / "o.db")
    sm = StubStateMachine()
    out = RecordingOutbound()
    orch = Orchestrator(config, store=store, parser=StubParser(), state_machine=sm, outbound=out)

    orch.handle_message("9199", "hi", message_id="wamid.DUP")
    orch.handle_message("9199", "hi", message_id="wamid.DUP")  # duplicate delivery

    assert len(sm.calls) == 1
    assert len(out.templates_sent) == 1


def test_handle_message_parser_failure_falls_back(config, tmp_path):
    class BoomParser:
        def parse_message(self, history):
            raise RuntimeError("llm down")

    out = RecordingOutbound()
    orch = Orchestrator(config, store=Store(tmp_path / "o.db"),
                        parser=BoomParser(), outbound=out)
    reply = orch.handle_message("p", "hi")
    assert "went wrong" in reply.lower()
    assert out.sent == [("p", reply)]


def test_handle_message_store_failure_still_sends_fallback(config):
    """Regression test: touch_session/add_message used to run outside the
    try/except, so a DB error there (e.g. the db file got deleted out from under
    a live process) raised uncaught inside a FastAPI BackgroundTask and silently
    swallowed the turn — the patient got no reply at all."""
    class BoomStore:
        def mark_processed(self, message_id):
            return True

        def touch_session(self, phone):
            raise RuntimeError("db is gone")

        def add_message(self, phone, role, content):
            raise RuntimeError("db is gone")

    out = RecordingOutbound()
    orch = Orchestrator(config, store=BoomStore(), parser=StubParser(), state_machine=StubStateMachine(), outbound=out)

    reply = orch.handle_message("p", "hi")

    assert "went wrong" in reply.lower()
    assert out.sent == [("p", reply)]
