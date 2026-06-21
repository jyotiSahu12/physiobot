from unittest.mock import MagicMock
import pytest
from physiobot.config import Config
from physiobot.parser import Parser


class StubProvider:
    def __init__(self, content):
        self.content = content

    def chat(self, messages, tools=None):
        return {"role": "assistant", "content": self.content}


def test_parser_normal_json(config):
    json_response = """
    {
      "intent": "book_appointment",
      "slots": {
        "full_name": "Asha",
        "phone_number": "9999",
        "main_problem": "knee pain"
      },
      "red_flags_detected": []
    }
    """
    provider = StubProvider(json_response)
    parser = Parser(config, provider=provider)
    result = parser.parse_message([])

    assert result["intent"] == "book_appointment"
    assert result["slots"]["full_name"] == "Asha"
    assert result["slots"]["phone_number"] == "9999"
    assert result["slots"]["main_problem"] == "knee pain"
    assert result["red_flags_detected"] == []


def test_parser_malformed_json_wrappers(config):
    # LLM might occasionally wrap JSON in markdown block code ```json ... ```
    wrapped_response = """
    Here is the parsed intent:
    ```json
    {
      "intent": "greeting",
      "slots": {},
      "red_flags_detected": ["chest pain"]
    }
    ```
    hope that helps!
    """
    provider = StubProvider(wrapped_response)
    parser = Parser(config, provider=provider)
    result = parser.parse_message([])

    assert result["intent"] == "greeting"
    assert result["red_flags_detected"] == ["chest pain"]


def test_parser_failure_fallback(config):
    # If the provider completely fails or returns unparseable text
    provider = StubProvider("Not JSON at all")
    parser = Parser(config, provider=provider)
    result = parser.parse_message([])

    assert result["intent"] == "other"
    assert result["slots"] == {}
    assert result["red_flags_detected"] == []
