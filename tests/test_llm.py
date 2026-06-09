import json
from types import SimpleNamespace

import pytest

from physiobot.llm import (
    GroqProvider, OllamaProvider, _salvage_tool_calls, _to_groq, _to_ollama,
)


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


def test_salvage_parses_malformed_groq_generation():
    # the exact shape Groq returned in the live run
    text = '<function=save_patient_info {"name": "Asha", "phone": "9199", "complaint": "ankle pain"}</function>'
    calls = _salvage_tool_calls(text)
    assert calls == [{"id": "salvage_0", "name": "save_patient_info",
                      "arguments": {"name": "Asha", "phone": "9199", "complaint": "ankle pain"}}]


class _ToolUseFailedError(Exception):
    def __init__(self, failed_generation):
        super().__init__("tool_use_failed")
        self.body = {"error": {"code": "tool_use_failed",
                               "failed_generation": failed_generation}}


class FailingGroqClient:
    """Always raises tool_use_failed, like Groq does for a malformed call."""
    def __init__(self, failed_generation):
        class _Completions:
            def create(_self, **kwargs):
                raise _ToolUseFailedError(failed_generation)
        self.chat = SimpleNamespace(completions=_Completions())


def test_groq_salvages_after_retries_exhausted():
    fg = '<function=get_free_slots {"date": "2030-01-10"}</function>'
    p = GroqProvider("m", "key", client=FailingGroqClient(fg))
    out = p.chat([{"role": "user", "content": "slots?"}], tools=[{"type": "function"}],
                 _retries=1)
    assert out["tool_calls"] == [
        {"id": "salvage_0", "name": "get_free_slots", "arguments": {"date": "2030-01-10"}}
    ]


class RaisingGroqClient:
    def __init__(self, exc):
        class _Completions:
            def create(_self, **kwargs):
                raise exc
        self.chat = SimpleNamespace(completions=_Completions())


def test_groq_reraises_non_tool_use_errors():
    p = GroqProvider("m", "key", client=RaisingGroqClient(ValueError("boom")))
    with pytest.raises(ValueError):
        p.chat([{"role": "user", "content": "hi"}], tools=[{"type": "function"}], _retries=0)


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
