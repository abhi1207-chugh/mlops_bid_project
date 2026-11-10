"""Deterministic safety checks for untrusted bid text and model-facing summaries."""
from __future__ import annotations

import re

_TOXIC = re.compile(r"\b(kill|threaten|hate\s+you|idiot|moron)\b", re.I)
_DETERMINATION = re.compile(r"\b(?:system|service|we)\s+(?:(?:has|have)\s+)?(?:accepted|approved|rejected|disqualified)\b", re.I)


def unsafe_input_reason(text: str) -> str | None:
    return "contains abusive or threatening language" if _TOXIC.search(text) else None


def unsafe_output_reason(text: str) -> str | None:
    if _TOXIC.search(text):
        return "contains abusive or threatening language"
    if _DETERMINATION.search(text):
        return "states an autonomous bid determination instead of a screening finding"
    return None
