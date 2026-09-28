"""NovaTech Prototype Risk Model — deterministic, configurable, explainable.

    score = 100 x Severity x Likelihood x Criticality x EvidenceFreshnessFactor x RecurrenceMultiplier

Every factor is normalised to (0, 1] (recurrence is a multiplier >= 1). Weights are exponents applied
to each factor, so a weight of 0 removes a factor and >1 amplifies it. The LLM may *explain* this output
but never overrides it. This is NOT an official regulatory scoring formula.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from app.compliance.snapshot import ControlView

MODEL_VERSION = "novatech-prototype-risk-v1"

DEFAULT_RISK_CONFIG: dict = {
    "weights": {"severity": 1.0, "likelihood": 1.0, "criticality": 1.0, "freshness": 1.0, "recurrence": 1.0},
    "thresholds": {"CRITICAL": 80, "HIGH": 50, "MEDIUM": 25},
    "severity_by_status": {"FAIL": 1.0, "OVERDUE": 0.75, "EXPIRED": 0.75, "PARTIAL": 0.5, "NOT_TESTED": 0.5,
                           "AT_RISK": 0.4, "PASS": 0.1},
    "severity_by_finding": {"CRITICAL": 1.0, "HIGH": 0.75, "MEDIUM": 0.5, "LOW": 0.25},
    "freshness_factor": {"VALID": 0.7, "EXPIRING": 0.85, "UNVERIFIED": 0.9, "CONFLICTING": 0.9,
                         "PARTIALLY_EXPIRED": 0.9, "EXPIRED": 1.0, "MISSING": 1.0},
    "recurrence_step": 0.1,
    "recurrence_cap": 1.3,
}


def merged_config(company_settings: dict | None) -> dict:
    cfg = deepcopy(DEFAULT_RISK_CONFIG)
    override = (company_settings or {}).get("risk_model") or {}
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    return cfg


@dataclass
class RiskResult:
    score: float
    category: str
    factors: dict
    explanation: list[str]

    def as_dict(self) -> dict:
        return {"score": self.score, "category": self.category, "factors": self.factors,
                "explanation": self.explanation, "model": MODEL_VERSION,
                "label": "NovaTech Prototype Risk Model"}


def categorize(score: float, cfg: dict) -> str:
    t = cfg["thresholds"]
    if score >= t["CRITICAL"]:
        return "CRITICAL"
    if score >= t["HIGH"]:
        return "HIGH"
    if score >= t["MEDIUM"]:
        return "MEDIUM"
    return "LOW"


def prior_occurrences(cv: ControlView) -> int:
    """Previous findings on this control sharing a category with a currently open finding."""
    open_cats = {f.category for f in cv.active_findings}
    return sum(1 for f in cv.findings if f.category in open_cats and f.status not in
               {"OPEN", "IN_REMEDIATION", "READY_FOR_CLOSURE"})


def assess_control(cv: ControlView, cfg: dict | None = None) -> RiskResult:
    cfg = cfg or DEFAULT_RISK_CONFIG
    w = cfg["weights"]
    c = cv.control
    why: list[str] = []

    # Severity: worst of current status and open finding severity
    sev_status = cfg["severity_by_status"].get(cv.status, 0.4)
    sev_find = max((cfg["severity_by_finding"].get(f.severity, 0.25) for f in cv.active_findings), default=0.0)
    severity = max(sev_status, sev_find)
    why.append(f"Severity {severity:.2f}: status {cv.status}" + (
        f", open finding severity {max(cv.active_findings, key=lambda f: cfg['severity_by_finding'].get(f.severity, 0)).severity}"
        if cv.active_findings else ""))

    # Likelihood: how likely the control is not operating right now
    parts = {"test_interval": 0.2}
    if cv.days_since_test is None:
        parts["never_tested"] = 1.0
    else:
        ratio = cv.days_since_test / max(c.frequency_days, 1)
        parts["test_interval"] = round(min(max(ratio, 0.2), 1.5) / 1.5, 3)
    if cv.status == "FAIL":
        parts["failed_test"] = 1.0
    if cv.evidence_state in ("MISSING", "EXPIRED"):
        parts["evidence_gap"] = 0.8
    if cv.requirement_changed or cv.misaligned:
        parts["requirement_changed"] = 0.9
    if cv.status == "PARTIAL":
        parts["partial_test"] = 0.7
    likelihood = max(parts.values())
    driver = max(parts, key=parts.get)
    why.append(f"Likelihood {likelihood:.2f}: driven by {driver.replace('_', ' ')}"
               + (f" ({cv.days_since_test} days since last test vs {c.frequency_days}-day frequency)"
                  if cv.days_since_test is not None else " (never tested)"))

    criticality = max(min(c.criticality, 5), 1) / 5
    why.append(f"Criticality {criticality:.2f}: control criticality {c.criticality}/5")

    freshness = cfg["freshness_factor"].get(cv.evidence_state, 1.0)
    why.append(f"Evidence freshness factor {freshness:.2f}: evidence {cv.evidence_state}")

    prior = prior_occurrences(cv)
    recurrence = min(1 + cfg["recurrence_step"] * prior, cfg["recurrence_cap"])
    if prior:
        why.append(f"Recurrence multiplier {recurrence:.2f}: {prior} previous occurrence(s) of the same finding")

    raw = (severity ** w["severity"]) * (likelihood ** w["likelihood"]) * (criticality ** w["criticality"]) \
        * (freshness ** w["freshness"]) * (recurrence ** w["recurrence"])
    score = round(min(raw * 100, 100), 1)
    return RiskResult(
        score=score,
        category=categorize(score, cfg),
        factors={"severity": round(severity, 3), "likelihood": round(likelihood, 3),
                 "criticality": round(criticality, 3), "freshness": freshness, "recurrence": round(recurrence, 3),
                 "likelihood_components": parts, "prior_occurrences": prior},
        explanation=why,
    )
