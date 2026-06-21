"""Shared loader for the clinic knowledge base (clinic_metadata.json).

Both the NLU parser and the state machine need this file; this module is the
single place that loads it, so a schema change only needs to be reconciled
in one spot.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("physiobot.metadata")

METADATA_PATH = Path(__file__).resolve().parent / "clinic_metadata.json"

# Top-level keys the bot actually reads (schema v3.0.0+). If clinic_metadata.json
# is edited (e.g. a future schema migration renames a section) and one of these
# goes missing, the affected feature silently degrades to an empty dict rather
# than raising — so we log it loudly instead. See clinic_kb.py for what reads
# each of these.
EXPECTED_TOP_LEVEL_KEYS = [
    "clinic_profile",
    "primary_branch",
    "triage_and_safety_guardrails",
    "customer_facing_response_templates",
    "service_recommendation_logic",
    "official_service_catalog",
    "handoff_to_human_rules",
    "compliance_and_privacy",
]


def load_metadata() -> dict:
    try:
        with open(METADATA_PATH) as f:
            data = json.load(f)
    except Exception:
        log.exception("failed to load clinic_metadata.json")
        return {}

    missing = [key for key in EXPECTED_TOP_LEVEL_KEYS if key not in data]
    if missing:
        log.warning(
            "clinic_metadata.json is missing expected top-level keys: %s", missing
        )
    return data
