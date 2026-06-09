"""Pluggable LLM providers behind one interface so the agent is provider-agnostic.

A provider exposes `chat(messages, tools) -> assistant_message` where both the
input messages and the returned message use a single CANONICAL shape:

    {"role": "user"|"assistant"|"tool"|"system", "content": str,
     # assistant only, when it calls tools:
     "tool_calls": [{"id": str, "name": str, "arguments": dict}],
     # tool result only:
     "tool_call_id": str, "name": str}

Each provider translates this canonical shape to/from its own wire format
(Ollama uses no tool-call ids; Groq/OpenAI requires id + tool_call_id linkage
and JSON-string arguments). This keeps `agent.py` free of provider quirks.
"""
from __future__ import annotations

import json

from .config import Config


# --- canonical <-> provider conversions -----------------------------------
def _to_ollama(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        if m["role"] == "assistant" and m.get("tool_calls"):
            out.append({
                "role": "assistant",
                "content": m.get("content", "") or "",
                "tool_calls": [
                    {"function": {"name": t["name"], "arguments": t["arguments"]}}
                    for t in m["tool_calls"]
                ],
            })
        elif m["role"] == "tool":
            out.append({"role": "tool", "content": m["content"]})
        else:
            out.append({"role": m["role"], "content": m.get("content", "") or ""})
    return out


def _to_groq(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        if m["role"] == "assistant" and m.get("tool_calls"):
            out.append({
                "role": "assistant",
                "content": m.get("content", "") or "",
                "tool_calls": [
                    {"id": t["id"], "type": "function",
                     "function": {"name": t["name"], "arguments": json.dumps(t["arguments"])}}
                    for t in m["tool_calls"]
                ],
            })
        elif m["role"] == "tool":
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"],
                        "content": m["content"]})
        else:
            out.append({"role": m["role"], "content": m.get("content", "") or ""})
    return out


# --- providers -------------------------------------------------------------
class OllamaProvider:
    def __init__(self, model: str, host: str, client=None):
        self.model = model
        if client is None:
            import ollama
            client = ollama.Client(host=host)
        self.client = client

    def chat(self, messages: list[dict], tools: list | None = None) -> dict:
        resp = self.client.chat(model=self.model, messages=_to_ollama(messages),
                                tools=tools)
        msg = resp["message"]
        calls = []
        for i, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc["function"]
            args = fn["arguments"]
            if isinstance(args, str):
                args = json.loads(args or "{}")
            calls.append({"id": f"call_{i}", "name": fn["name"], "arguments": args})
        return {"role": "assistant", "content": msg.get("content", "") or "",
                "tool_calls": calls}


class GroqProvider:
    def __init__(self, model: str, api_key: str, client=None):
        self.model = model
        if client is None:
            from groq import Groq
            client = Groq(api_key=api_key)
        self.client = client

    def chat(self, messages: list[dict], tools: list | None = None) -> dict:
        kwargs = {"model": self.model, "messages": _to_groq(messages)}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        resp = self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        calls = []
        for tc in (msg.tool_calls or []):
            args = tc.function.arguments
            if isinstance(args, str):
                args = json.loads(args or "{}")
            calls.append({"id": tc.id, "name": tc.function.name, "arguments": args})
        return {"role": "assistant", "content": msg.content or "", "tool_calls": calls}


def get_provider(config: Config):
    if config.llm.provider == "groq":
        if not config.llm.groq_api_key:
            raise RuntimeError("LLM provider is 'groq' but GROQ_API_KEY is not set.")
        return GroqProvider(config.llm.groq_model, config.llm.groq_api_key)
    return OllamaProvider(config.llm.ollama_model, config.llm.ollama_host)
