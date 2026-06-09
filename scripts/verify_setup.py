"""One-shot connectivity check. Run after filling config.yaml + .env:

    python scripts/verify_setup.py

Checks Ollama, the Google Sheet, and the Google Calendar so you find problems
before going live on WhatsApp.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from physiobot.config import get_config  # noqa: E402


def ok(msg):
    print(f"  \033[92m✓\033[0m {msg}")


def fail(msg):
    print(f"  \033[91m✗\033[0m {msg}")


def check_llm(config) -> bool:
    if config.llm.provider == "groq":
        if not config.llm.groq_api_key:
            fail("Provider is 'groq' but GROQ_API_KEY is not set in the environment")
            return False
        try:
            from groq import Groq
            Groq(api_key=config.llm.groq_api_key).models.list()
            ok(f"Groq reachable; model '{config.llm.groq_model}' configured")
            return True
        except Exception as e:
            fail(f"Cannot reach Groq: {e}")
            return False
    # ollama
    import ollama
    try:
        client = ollama.Client(host=config.llm.ollama_host)
        models = [m.get("model", m.get("name", "")) for m in client.list().get("models", [])]
        if any(config.llm.ollama_model in m for m in models):
            ok(f"Ollama reachable; model '{config.llm.ollama_model}' present")
            return True
        fail(f"Ollama up but model '{config.llm.ollama_model}' not found. "
             f"Run: ollama pull {config.llm.ollama_model}")
        return False
    except Exception as e:
        fail(f"Cannot reach Ollama at {config.llm.ollama_host}: {e}")
        return False


def check_sheet(config) -> bool:
    from physiobot.tools.sheets import SheetsClient
    try:
        sc = SheetsClient(config)
        title = sc.spreadsheet.title
        # ensure both tabs are reachable/creatable
        sc._worksheet(config.google.patients_tab, ["Timestamp"])
        sc._worksheet(config.google.bookings_tab, ["Timestamp"])
        ok(f"Google Sheet '{title}' opened; tabs ready")
        return True
    except Exception as e:
        fail(f"Cannot open Google Sheet ({config.google.sheet_id}): {e}")
        return False


def check_calendar(config) -> bool:
    from physiobot.tools.calendar import CalendarClient
    try:
        cal = CalendarClient(config)
        cal.service.calendars().get(calendarId=config.google.calendar_id).execute()
        ok(f"Google Calendar '{config.google.calendar_id}' accessible")
        return True
    except Exception as e:
        fail(f"Cannot access Google Calendar ({config.google.calendar_id}): {e}")
        return False


def main():
    config = get_config()
    print("PhysioBot setup check\n")
    print(f"LLM provider: {config.llm.provider}")
    a = check_llm(config)
    print("Google Sheet:")
    b = check_sheet(config)
    print("Google Calendar:")
    c = check_calendar(config)
    print()
    if a and b and c:
        print("All good — you can start the app: uvicorn physiobot.app:app --reload")
        return 0
    print("Some checks failed — fix the above before going live.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
