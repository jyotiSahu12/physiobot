import json
from types import SimpleNamespace

from physiobot.llm import GroqProvider, OllamaProvider, _to_groq, _to_ollama


# --- Ollama -----------------------------------------------------------------
class FakeOllamaClient:
    def __init__(self, response):
        self.response = response
        self.last = None

    def chat(self, model, messages, tools=None):
        self.last = {"model": model, "messages": messages, "tools": tools}
        return self.response


def test_ollama_normalizes_tool_calls():
    resp = {"message": {"content": "", "tool_calls": [
        {"function": {"name": "get_free_slots", "arguments": {"date": "2030-01-10"}}}
    ]}}
    p = OllamaProvider("qwen2.5", "http://x", client=FakeOllamaClient(resp))
    out = p.chat([{"role": "user", "content": "hi"}], tools=[])
    assert out["tool_calls"] == [
        {"id": "call_0", "name": "get_free_slots", "arguments": {"date": "2030-01-10"}}
    ]


def test_to_ollama_strips_ids():
    canonical = [
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "c1", "name": "f", "arguments": {"a": 1}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "f", "content": "result"},
    ]
    out = _to_ollama(canonical)
    assert out[0]["tool_calls"] == [{"function": {"name": "f", "arguments": {"a": 1}}}]
    assert out[1] == {"role": "tool", "content": "result"}


# --- Groq -------------------------------------------------------------------
class FakeGroqClient:
    def __init__(self, message):
        self._message = message
        self.last = None

        class _Completions:
            def create(_self, **kwargs):
                self.last = kwargs
                return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        self.chat = SimpleNamespace(completions=_Completions())


def test_groq_normalizes_and_parses_json_args():
    tc = SimpleNamespace(id="call_abc", function=SimpleNamespace(
        name="save_patient_info", arguments='{"name": "Sam", "phone": "5"}'))
    message = SimpleNamespace(content="", tool_calls=[tc])
    p = GroqProvider("llama-3.3-70b-versatile", "key", client=FakeGroqClient(message))
    out = p.chat([{"role": "user", "content": "hi"}], tools=[{"type": "function"}])
    assert out["tool_calls"] == [
        {"id": "call_abc", "name": "save_patient_info",
         "arguments": {"name": "Sam", "phone": "5"}}
    ]


def test_to_groq_requires_id_and_tool_call_id():
    canonical = [
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "c1", "name": "f", "arguments": {"a": 1}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "f", "content": "result"},
    ]
    out = _to_groq(canonical)
    assert out[0]["tool_calls"][0]["id"] == "c1"
    assert out[0]["tool_calls"][0]["function"]["arguments"] == json.dumps({"a": 1})
    assert out[1] == {"role": "tool", "tool_call_id": "c1", "content": "result"}
