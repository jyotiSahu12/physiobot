"""Typed accessor over clinic_metadata.json.

The rest of the codebase used to reach into the raw metadata dict directly
with chains of `.get(...).get(...)`. That broke silently when the clinic
shipped a new schema version (v2.0.0 -> v3.0.0): every key path changed, and
the `or self.metadata.get("old_key")` fallbacks meant red-flag detection, FAQ
answers and service hints all quietly degraded to empty instead of erroring.

This module is the one place that knows the current schema. A future schema
migration should only require changes here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import quote

from .metadata import load_metadata


@dataclass(frozen=True)
class ServiceMatch:
    service_id: str
    service_name: str
    sub_service_id: str | None
    follow_up_questions: list[str] = field(default_factory=list)
    requires_human_review: bool = False


class ClinicKB:
    def __init__(self, data: dict | None = None):
        self.data = data if data is not None else load_metadata()

    # --- identity / contact --------------------------------------------------

    @property
    def clinic_name(self) -> str:
        branch_name = self.data.get("primary_branch", {}).get("branch_name")
        return branch_name or self.data.get("clinic_profile", {}).get("brand_name", "")

    @property
    def clinic_phone(self) -> str:
        phone = self.data.get("primary_branch", {}).get("contact", {}).get("phone", {})
        return phone.get("display_value") or phone.get("value") or ""

    @property
    def clinic_address(self) -> str:
        return self.data.get("primary_branch", {}).get("official_address", {}).get(
            "full_address_customer_facing", ""
        )

    @property
    def maps_url(self) -> str:
        """A Google Maps deep link built from the official, already-public address
        text — no Maps API key or GCP billing needed. Opens Maps centered on a
        text search rather than a precise geocoded pin, since the metadata
        explicitly marks the exact street address and a verified Maps URL as
        needs_confirmation (clinic hasn't validated either yet)."""
        address = self.clinic_address
        if not address:
            return ""
        return f"https://www.google.com/maps/search/?api=1&query={quote(address)}"

    # --- safety ---------------------------------------------------------------

    @property
    def red_flag_triggers(self) -> list[str]:
        return self.data.get("triage_and_safety_guardrails", {}).get("red_flag_symptoms", [])

    @property
    def red_flag_message(self) -> str:
        action = self.data.get("triage_and_safety_guardrails", {}).get("red_flag_bot_action", {})
        return action.get("message") or (
            "Your symptoms may need urgent medical attention. Please visit the nearest hospital."
        )

    # --- canned customer-facing copy ------------------------------------------

    def response_template(self, key: str, default: str = "") -> str:
        """Look up a canned reply from customer_facing_response_templates.
        This is the clinic-approved wording for things the bot can't confirm
        itself (pricing, hours, etc.) — keeping it data-driven means the bot
        never says anything the clinic hasn't reviewed."""
        return self.data.get("customer_facing_response_templates", {}).get(key) or default

    # --- service recommendation ------------------------------------------------

    def _service_name_lookup(self) -> dict[str, str]:
        return {
            s["service_id"]: s["service_name"]
            for s in self.data.get("official_service_catalog", [])
            if s.get("service_id")
        }

    def _sub_service_name_lookup(self) -> dict[str, str]:
        # Sub-services are nested under either "sub_services" or
        # "officially_listed_sub_services" depending on the parent service —
        # the metadata isn't consistent about which key it uses.
        lookup: dict[str, str] = {}
        for s in self.data.get("official_service_catalog", []):
            subs = s.get("sub_services") or s.get("officially_listed_sub_services") or []
            for sub in subs:
                sub_id, name = sub.get("sub_service_id"), sub.get("name")
                if sub_id and name:
                    lookup[sub_id] = name
        return lookup

    def match_service(self, complaint: str) -> ServiceMatch | None:
        """Match a patient's free-text complaint against
        service_recommendation_logic.rules and resolve the matched rule's
        service/sub-service ids to their customer-facing names. The sub-service
        name (e.g. "Post-operative physiotherapy") is preferred when present —
        it's more specific and useful than the generic parent service name
        (e.g. "Physiotherapy Services")."""
        complaint = (complaint or "").lower()
        if not complaint:
            return None
        rules = self.data.get("service_recommendation_logic", {}).get("rules", [])
        names = self._service_name_lookup()
        sub_names = self._sub_service_name_lookup()
        for rule in rules:
            terms = rule.get("trigger_terms", [])
            if any(term.lower() in complaint for term in terms):
                service_id = rule.get("recommend_service_id", "")
                sub_service_id = rule.get("recommend_sub_service_id")
                service_name = (
                    sub_names.get(sub_service_id) if sub_service_id else None
                ) or names.get(service_id, service_id)
                return ServiceMatch(
                    service_id=service_id,
                    service_name=service_name,
                    sub_service_id=sub_service_id,
                    follow_up_questions=rule.get("ask_follow_up", []),
                    requires_human_review=bool(rule.get("requires_human_review", False)),
                )
        return None
