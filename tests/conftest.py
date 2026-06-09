import sys
from pathlib import Path

import pytest

# Make the repo root importable (so `import physiobot...` works under pytest).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from physiobot.config import (  # noqa: E402
    ClinicConfig, Config, GoogleConfig, HoursConfig, LLMConfig, MetaConfig,
)


@pytest.fixture
def config():
    return Config(
        clinic=ClinicConfig(name="Test Clinic", contact_number="+91-99999-00000",
                            timezone="Asia/Kolkata"),
        hours=HoursConfig(open="10:00", close="13:00", slot_minutes=60, closed_weekdays=[6]),
        llm=LLMConfig(provider="ollama", ollama_model="qwen2.5",
                      ollama_host="http://localhost:11434",
                      groq_model="llama-3.3-70b-versatile", groq_api_key="",
                      max_tool_iterations=5),
        google=GoogleConfig(sheet_id="sheet", patients_tab="Patients",
                            bookings_tab="Bookings", calendar_id="cal",
                            credentials_path="/tmp/fake.json", credentials_json=""),
        meta=MetaConfig(token="", phone_number_id="", verify_token="physiobot-verify",
                        app_secret=""),
    )
