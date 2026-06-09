from physiobot.orchestrator import Orchestrator
from physiobot.store import Store


class StubAgent:
    def __init__(self, reply="hi from agent"):
        self.reply = reply
        self.seen_history = None

    def respond(self, history):
        self.seen_history = history
        return self.reply


class RecordingOutbound:
    def __init__(self):
        self.sent = []

    def send_text(self, to, text):
        self.sent.append((to, text))


def test_handle_message_persists_and_sends(config, tmp_path):
    store = Store(tmp_path / "o.db")
    agent = StubAgent("Hello Asha!")
    out = RecordingOutbound()
    orch = Orchestrator(config, store=store, agent=agent, outbound=out)

    reply = orch.handle_message("9199", "hi")

    assert reply == "Hello Asha!"
    assert out.sent == [("9199", "Hello Asha!")]
    # both user and assistant turns persisted
    assert store.history("9199") == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "Hello Asha!"},
    ]


def test_handle_message_agent_failure_falls_back(config, tmp_path):
    class BoomAgent:
        def respond(self, history):
            raise RuntimeError("ollama down")

    out = RecordingOutbound()
    orch = Orchestrator(config, store=Store(tmp_path / "o.db"),
                        agent=BoomAgent(), outbound=out)
    reply = orch.handle_message("p", "hi")
    assert "went wrong" in reply.lower()
    assert out.sent[0][0] == "p"
