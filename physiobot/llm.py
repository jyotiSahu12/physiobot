"""Pluggable LLM providers behind one interface so the NLU parser is
provider-agnostic.

A provider exposes `chat(messages) -> {"role": "assistant", "content": str}`.
Messages are plain {"role": "system"|"user"|"assistant", "content": str}
dicts — there's no tool-calling support here, since the parser only ever
needs a single JSON-text reply (see parser.py).
"""
from __future__ import annotations

from .config import Config


class OllamaProvider:
    def __init__(self, model: str, host: str, client=None):
        self.model = model
        if client is None:
            import ollama
            client = ollama.Client(host=host)
        self.client = client

    def chat(self, messages: list[dict]) -> dict:
        resp = self.client.chat(model=self.model, messages=messages)
        return {"role": "assistant", "content": resp["message"].get("content") or ""}


class GroqProvider:
    def __init__(self, model: str, api_key: str, client=None):
        self.model = model
        if client is None:
            from groq import Groq
            client = Groq(api_key=api_key)
        self.client = client

    def chat(self, messages: list[dict]) -> dict:
        resp = self.client.chat.completions.create(model=self.model, messages=messages)
        return {"role": "assistant", "content": resp.choices[0].message.content or ""}


def get_provider(config: Config):
    if config.llm.provider == "groq":
        if not config.llm.groq_api_key:
            raise RuntimeError("LLM provider is 'groq' but GROQ_API_KEY is not set.")
        return GroqProvider(config.llm.groq_model, config.llm.groq_api_key)
    return OllamaProvider(config.llm.ollama_model, config.llm.ollama_host)
