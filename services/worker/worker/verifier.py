"""Verification (hard rule 2): every citation must resolve to text retrieved in this run.

Deterministic checks run first; an independent LLM verifier prompt then checks the claims.
"""
from __future__ import annotations

import re

from common.models import Citation


def _n(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[‘’“”\"']", "", t)).strip().lower()


def quote_in_text(quote: str, text: str) -> bool:
    """Verbatim match after whitespace/quote/case normalisation; '...' separates fragments that must each appear."""
    frags = [f for f in re.split(r"\.\.\.|…", _n(quote)) if f.strip()]
    hay = _n(text)
    return bool(frags) and all(f.strip() in hay for f in frags)


def resolve_citations(raw: list[dict], retrieved: dict[str, dict]) -> tuple[list[Citation], list[str]]:
    """Return (resolved citations with doc_id/clause_ref taken from the corpus, issues)."""
    out: list[Citation] = []
    issues: list[str] = []
    for c in raw or []:
        cid = str(c.get("chunk_id", ""))
        chunk = retrieved.get(cid)
        if chunk is None:
            issues.append(f"citation {cid!r} was not retrieved in this run")
            continue
        quote = str(c.get("quote", ""))
        if not quote_in_text(quote, chunk["text"]):
            issues.append(f"quote for {cid} does not appear in the retrieved passage")
            continue
        if chunk["status"] == "superseded":
            issues.append(f"{chunk['doc_id']} is superseded and cannot be cited")
            continue
        out.append(Citation(doc_id=chunk["doc_id"], clause_ref=chunk["clause_ref"], chunk_id=cid, quote=quote))
    return out, issues
