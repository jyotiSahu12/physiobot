"""Build Google service-account credentials from either a key file (local dev)
or the key JSON passed directly as an env var (cloud deploy, where there is no
file on disk)."""
from __future__ import annotations

import json

from google.oauth2.service_account import Credentials

from .config import get_config


def load_credentials(scopes: list[str]) -> Credentials:
    cfg = get_config().google
    if cfg.credentials_json:
        info = json.loads(cfg.credentials_json)
        return Credentials.from_service_account_info(info, scopes=scopes)
    if cfg.credentials_path:
        return Credentials.from_service_account_file(cfg.credentials_path, scopes=scopes)
    raise RuntimeError(
        "No Google credentials: set GOOGLE_APPLICATION_CREDENTIALS (local) "
        "or GOOGLE_CREDENTIALS_JSON (cloud)."
    )
