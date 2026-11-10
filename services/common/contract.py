"""Bid summary data contract (F1, F2, D1). Mirrors contracts/bid_summary.schema.json.

validate_bid() returns either a model or field-level errors; the API quarantines on errors
and never starts an agent run for them (hard rule 4).
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from common.safety import unsafe_input_reason

_INJECTION_PATTERNS = (
    r"\b(?:ignore|disregard|override)\b.{0,80}\b(?:previous|prior|system|above)\b.{0,80}\b(?:instruction|prompt|rule)s?\b",
    r"\b(?:system prompt|developer message|jailbreak)\b",
)

Category = Literal["large_enterprise", "mse", "startup", "consortium", "foreign", "unknown"]
DocName = Literal[
    "legal_status", "pan", "gst", "tender_acceptance_letter", "bid_security_declaration",
    "oem_authorization", "experience_proof", "turnover_proof", "data_sheet", "escalation_matrix",
    "warranty_declaration", "emd_proof", "dpiit_certificate", "udyam_certificate",
]


class BidSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tender_id: str = Field(pattern=r"^[A-Za-z0-9_\-]+$", max_length=64)
    bidder_name: str = Field(min_length=1, max_length=200)
    bidder_category_claimed: Category
    dpiit_recognition_number: str | None = Field(default=None, max_length=64)
    udyam_registration_number: str | None = Field(default=None, max_length=64)
    avg_annual_turnover_inr: float = Field(ge=0, le=1_000_000_000_000)
    turnover_years_reported: int | None = Field(default=None, ge=1, le=10)
    turnover_certificate_covers_three_years: bool | None = None
    emd_paid_inr: float = Field(ge=0)
    emd_exemption_claimed: bool = False
    similar_work_experience_count: int = Field(default=0, ge=0)
    documents_submitted: list[DocName]
    is_trader: bool = False
    manufacturer_or_distributor: Literal["manufacturer", "authorised_distributor", "other"] | None = None
    item_category: str | None = Field(default=None, max_length=100)
    preference_claimed: str | None = Field(default=None, max_length=100)
    remarks: str | None = Field(default=None, max_length=1000)  # untrusted free text

    @model_validator(mode="after")
    def cross_field_rules(self) -> "BidSummary":
        if len(set(self.documents_submitted)) != len(self.documents_submitted):
            raise ValueError("documents_submitted: duplicate entries")
        if self.emd_exemption_claimed and self.bidder_category_claimed not in ("startup", "mse"):
            raise ValueError("emd_exemption_claimed: only startup or mse bidders can claim an EMD exemption")
        if self.emd_paid_inr > 0 and "emd_proof" not in self.documents_submitted:
            raise ValueError("documents_submitted: emd_paid_inr > 0 requires 'emd_proof'")
        return self

    def flags(self) -> list[str]:
        """Soft inconsistencies: not rejected at the boundary, surfaced to the agents (e.g. B8 -> clarification)."""
        out: list[str] = []
        if self.bidder_category_claimed == "startup" and not (
            self.dpiit_recognition_number or "dpiit_certificate" in self.documents_submitted
        ):
            out.append("startup claimed without DPIIT recognition number or certificate")
        if self.bidder_category_claimed == "mse" and not (
            self.udyam_registration_number or "udyam_certificate" in self.documents_submitted
        ):
            out.append("mse claimed without Udyam registration number or certificate")
        return out


def _field_path(loc: tuple) -> str:
    return ".".join(str(p) for p in loc) if loc else "(body)"


def validate_bid(payload: Any) -> tuple[BidSummary | None, list[dict]]:
    """Return (model, []) or (None, field_errors)."""
    if not isinstance(payload, dict):
        return None, [{"field": "(body)", "message": "request body must be a JSON object", "type": "type_error"}]
    try:
        model = BidSummary.model_validate(payload)
        remarks = model.remarks or ""
        if any(re.search(pattern, remarks, re.IGNORECASE | re.DOTALL) for pattern in _INJECTION_PATTERNS):
            return None, [{"field": "remarks", "message": "contains a prompt-injection pattern; request was blocked before an agent run", "type": "prompt_injection"}]
        if reason := unsafe_input_reason(remarks):
            return None, [{"field": "remarks", "message": f"{reason}; request was blocked before an agent run", "type": "unsafe_content"}]
        return model, []
    except ValidationError as exc:
        errors = []
        for e in exc.errors():
            msg = str(e.get("msg", "invalid")).removeprefix("Value error, ")
            errors.append({"field": _field_path(e.get("loc", ())), "message": msg, "type": e.get("type", "invalid")})
        return None, errors
