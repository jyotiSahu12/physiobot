from types import SimpleNamespace

from physiobot.llm import GroqProvider, OllamaProvider


class FakeOllamaClient:
    def __init__(self, response):
        self.response = response
        self.last = None

    def chat(self, model, messages):
        self.last = {"model": model, "messages": messages}
        return self.response


def test_ollama_returns_assistant_content():
    resp = {"message": {"content": "hello there"}}
    p = OllamaProvider("qwen2.5", "http://x", client=FakeOllamaClient(resp))
    out = p.chat([{"role": "user", "content": "hi"}])
    assert out == {"role": "assistant", "content": "hello there"}


def test_ollama_passes_messages_through_unchanged():
    client = FakeOllamaClient({"message": {"content": ""}})
    p = OllamaProvider("qwen2.5", "http://x", client=client)
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    p.chat(messages)
    assert client.last["messages"] == messages


def test_ollama_handles_missing_content():
    client = FakeOllamaClient({"message": {}})
    p = OllamaProvider("qwen2.5", "http://x", client=client)
    assert p.chat([{"role": "user", "content": "hi"}])["content"] == ""


class FakeGroqClient:
    def __init__(self, message):
        self.last = None

        class _Completions:
            def create(_self, **kwargs):
                self.last = kwargs
                return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        self.chat = SimpleNamespace(completions=_Completions())


def test_groq_returns_assistant_content():
    message = SimpleNamespace(content="hello from groq")
    p = GroqProvider("llama-3.3-70b-versatile", "key", client=FakeGroqClient(message))
    out = p.chat([{"role": "user", "content": "hi"}])
    assert out == {"role": "assistant", "content": "hello from groq"}


def test_groq_handles_missing_content():
    message = SimpleNamespace(content=None)
    p = GroqProvider("llama-3.3-70b-versatile", "key", client=FakeGroqClient(message))
    assert p.chat([{"role": "user", "content": "hi"}])["content"] == ""
