"""Load configuration from config.yaml + environment (.env).

Environment variables override config.yaml where it matters for deployment:
- LLM_PROVIDER   -> llm.provider ("ollama" for local, "groq" for cloud)
- GROQ_API_KEY   -> Groq credentials (cloud)
- GOOGLE_APPLICATION_CREDENTIALS / GOOGLE_CREDENTIALS_JSON -> Google auth
- WHATSAPP_*     -> Meta WhatsApp credentials
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Repo root = parent of the `physiobot` package directory.
ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class ClinicConfig:
    name: str
    contact_number: str
    timezone: str


@dataclass(frozen=True)
class HoursConfig:
    open: str
    close: str
    slot_minutes: int
    closed_weekdays: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class LLMConfig:
    provider: str            # "ollama" | "groq"
    ollama_model: str
    ollama_host: str
    groq_model: str
    groq_api_key: str
    max_tool_iterations: int


@dataclass(frozen=True)
class GoogleConfig:
    sheet_id: str
    patients_tab: str
    bookings_tab: str
    calendar_id: str
    credentials_path: str
    credentials_json: str    # alternative to the file, for cloud env vars


@dataclass(frozen=True)
class MetaConfig:
    token: str
    phone_number_id: str
    verify_token: str
    app_secret: str

    @property
    def configured(self) -> bool:
        return bool(self.token and self.phone_number_id)


@dataclass(frozen=True)
class Config:
    clinic: ClinicConfig
    hours: HoursConfig
    llm: LLMConfig
    google: GoogleConfig
    meta: MetaConfig


@lru_cache(maxsize=1)
def get_config(path: str | None = None) -> Config:
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    raw = yaml.safe_load(cfg_path.read_text())
    llm = raw["llm"]

    return Config(
        clinic=ClinicConfig(**raw["clinic"]),
        hours=HoursConfig(**raw["hours"]),
        llm=LLMConfig(
            provider=os.environ.get("LLM_PROVIDER", llm.get("provider", "ollama")),
            ollama_model=llm.get("ollama_model", "qwen2.5"),
            ollama_host=llm.get("ollama_host", "http://localhost:11434"),
            groq_model=llm.get("groq_model", "llama-3.3-70b-versatile"),
            groq_api_key=os.environ.get("GROQ_API_KEY", ""),
            max_tool_iterations=llm.get("max_tool_iterations", 5),
        ),
        google=GoogleConfig(
            sheet_id=raw["google"]["sheet_id"],
            patients_tab=raw["google"]["patients_tab"],
            bookings_tab=raw["google"]["bookings_tab"],
            calendar_id=raw["google"]["calendar_id"],
            credentials_path=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", ""),
            credentials_json=os.environ.get("GOOGLE_CREDENTIALS_JSON", ""),
        ),
        meta=MetaConfig(
            token=os.environ.get("WHATSAPP_TOKEN", ""),
            phone_number_id=os.environ.get("WHATSAPP_PHONE_NUMBER_ID", ""),
            verify_token=os.environ.get("WHATSAPP_VERIFY_TOKEN", "physiobot-verify"),
            app_secret=os.environ.get("WHATSAPP_APP_SECRET", ""),
        ),
    )
