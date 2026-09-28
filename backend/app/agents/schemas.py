"""Structured agent outputs (used for both LLM structured outputs and deterministic results)."""
from typing import Literal

from pydantic import BaseModel, Field

Intent = Literal[
    "audit_readiness", "explain_control", "investigate_control", "recurring_findings", "what_changed",
    "remediation_plan", "memory_search", "expiring_evidence", "controls_at_risk", "untested_controls",
    "open_findings", "generate_report", "document_question", "general", "simulate_control", "policy_lab",
    "compliance_scan", "morning_brief", "control_drift",
]


class IntentClassification(BaseModel):
    intent: Intent
    control_code: str | None = Field(default=None, description="Control code like C-017 if referenced")
    finding_code: str | None = None
    framework: str | None = None


class PlanStep(BaseModel):
    id: int
    title: str
    tool: str | None = None
    phase: Literal["UNDERSTAND", "PLAN", "RETRIEVE", "ASSESS", "DETECT", "INVESTIGATE", "REMEDIATE", "VERIFY", "REMEMBER"]


class AgentPlan(BaseModel):
    objective: str
    steps: list[PlanStep]


class Citation(BaseModel):
    chunk_id: int
    quote: str = Field(description="Short supporting quote copied from the passage")


class GroundedAnswer(BaseModel):
    answer: str = Field(description="Concise answer grounded ONLY in the passages")
    citations: list[Citation]
    insufficient_evidence: bool = False


class AuditReadinessNarrative(BaseModel):
    headline: str
    summary: str = Field(description="3 sentences max, only facts from input")
    top_priority: str


class RiskExplanation(BaseModel):
    summary: str = Field(description="2-3 sentences explaining the deterministic risk result; do not change the score")
