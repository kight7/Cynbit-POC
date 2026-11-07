"""Pydantic data contracts for every stage of the pipeline."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from .config import taxonomy

Urgency = Literal["low", "medium", "high", "unknown"]
CompanySize = Literal["startup", "smb", "mid_market", "enterprise", "unknown"]


def _allowed(key: str) -> set[str]:
    return set(taxonomy()[key].keys())


class LeadFields(BaseModel):
    """Structured fields extracted from an unstructured inbound inquiry."""

    company_name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_role: Optional[str] = None
    industry: Optional[str] = Field(None, description="One of taxonomy.industries, 'other', or null")
    need_types: list[str] = Field(default_factory=list, description="Subset of taxonomy.need_types")
    need_summary: Optional[str] = Field(None, description="One sentence: what the client wants built")
    budget_signal: Optional[str] = Field(None, description="Budget phrase verbatim, e.g. '$40-60k'")
    budget_amount_usd: Optional[float] = Field(None, description="Upper bound converted to USD, if a number is given")
    timeline: Optional[str] = Field(None, description="Timeline phrase verbatim")
    timeline_months: Optional[float] = Field(None, description="Months until the desired delivery/launch")
    urgency: Urgency = "unknown"
    company_size: CompanySize = "unknown"
    decision_maker_present: bool = False
    region: Optional[str] = Field(None, description="One of taxonomy.regions, 'other', or null")
    off_scope: bool = Field(False, description="True if the request is not something a software/IT services firm does")
    missing_info: list[str] = Field(default_factory=list, description="Important facts the client did not state")

    @field_validator("industry", "region", mode="before")
    @classmethod
    def _norm_lower(cls, v):
        if v is None:
            return None
        v = str(v).strip().lower().replace(" ", "_").replace("-", "_")
        return v or None

    @field_validator("industry")
    @classmethod
    def _check_industry(cls, v):
        if v is None or v in _allowed("industries") or v == "other":
            return v
        return "other"

    @field_validator("region")
    @classmethod
    def _check_region(cls, v):
        if v is None or v in _allowed("regions") or v == "other":
            return v
        return "other"

    @field_validator("need_types", mode="before")
    @classmethod
    def _check_needs(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            v = [v]
        allowed = _allowed("need_types")
        out = []
        for item in v:
            item = str(item).strip().lower().replace(" ", "_").replace("-", "_")
            if item in allowed and item not in out:
                out.append(item)
        return out

    @field_validator("urgency", "company_size", mode="before")
    @classmethod
    def _lower(cls, v):
        if v is None:
            return "unknown"
        return str(v).strip().lower().replace(" ", "_").replace("-", "_")


class ScoreItem(BaseModel):
    factor: str
    label: str
    points: int
    max_points: int
    reason: str


class LeadScore(BaseModel):
    total: int
    tier: Literal["hot", "warm", "cold"]
    breakdown: list[ScoreItem]


class Route(BaseModel):
    rule: str
    team: str
    owner: str
    sla: str


class Chunk(BaseModel):
    chunk_id: str
    case_id: str
    section: str
    text: str
    metadata: dict


class RetrievedCase(BaseModel):
    case_id: str
    title: str
    client: str
    industry: str
    source_url: str
    score: float
    confidence: float
    metrics: list[str]
    chunks: list[dict]  # {"chunk_id", "section", "text", "score"}


class GuardrailReport(BaseModel):
    numbers_total: int
    numbers_verified: int
    unverified_numbers: list[str]
    citations_used: list[str]
    invalid_citations: list[str]
    faithfulness: float  # verified / total (1.0 if no numbers)
    passed: bool


class CopilotResult(BaseModel):
    inquiry: str
    mode: str  # "groq:<model>", "gemini:<model>", or "offline"
    fields: LeadFields
    score: LeadScore
    route: Route
    retrieved: list[RetrievedCase]
    proposal_markdown: str
    guardrail: GuardrailReport
    latency_ms: dict
    notices: list[str] = Field(default_factory=list)
