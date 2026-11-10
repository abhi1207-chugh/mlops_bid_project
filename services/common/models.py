"""Pydantic models for everything that crosses a service boundary."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Route = Literal["pass_to_technical_evaluation", "seek_clarification", "reject_with_cited_condition", "escalate_to_human"]
RunStatus = Literal["queued", "running", "done", "escalated", "failed"]
DISCLAIMER = "Screening finding only. A tender committee decides; this system never rejects or qualifies a bid on its own authority."


class Citation(BaseModel):
    doc_id: str
    clause_ref: str
    chunk_id: str
    quote: str = ""


class ConditionFinding(BaseModel):
    condition: str
    clause_ref: str | None = None
    status: Literal["met", "unmet", "unclear"]
    evidence: str = ""
    citations: list[Citation] = Field(default_factory=list)


class Verification(BaseModel):
    passed: bool
    attempts: int
    issues: list[str] = Field(default_factory=list)


class UsageRecord(BaseModel):
    step: str
    prompt_version: str
    prompt_tokens: int
    completion_tokens: int
    cost: float
    latency_ms: float


class Finding(BaseModel):
    run_id: str
    route: Route
    summary: str
    conditions: list[ConditionFinding] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    committee_questions: list[str] = Field(default_factory=list)
    escalation_reason: str | None = None
    verification: Verification | None = None
    bidder_category: str | None = None
    steps: int = 0
    tool_calls: int = 0
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    usage: list[UsageRecord] = Field(default_factory=list)
    disclaimer: str = DISCLAIMER


class RunRecord(BaseModel):
    run_id: str
    status: RunStatus
    created_at: float
    updated_at: float
    bid: dict
    flags: list[str] = Field(default_factory=list)
    finding: Finding | None = None
    trace: list[dict] = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    """Committee feedback on a screening finding; never changes the original finding."""
    satisfactory: bool
    reason: str = Field(min_length=1, max_length=2000)
