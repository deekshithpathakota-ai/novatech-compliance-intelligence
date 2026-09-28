"""Prototype Security Analytics — lightweight rule-based anomaly detection (not a production ML system)."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, SecurityEvent

LABEL = "Prototype Security Analytics"
RULES = [
    {"key": "repeated_denials", "window_min": 5, "threshold": 5, "severity": "HIGH", "text": "{n} denied access attempts in 5 minutes"},
    {"key": "excessive_tool_calls", "window_min": 5, "threshold": 60, "severity": "MEDIUM", "text": "{n} agent tool calls in 5 minutes"},
    {"key": "bulk_document_access", "window_min": 10, "threshold": 10, "severity": "MEDIUM", "text": "{n} confidential documents opened in 10 minutes"},
    {"key": "failed_authentication", "window_min": 15, "threshold": 5, "severity": "MEDIUM", "text": "{n} failed sign-in attempts in 15 minutes"},
]


def analyze(db: Session, company_id: int) -> list[dict]:
    now = datetime.now(timezone.utc)
    raised = []

    def since(m):
        return now - timedelta(minutes=m)

    counts: dict[str, Counter] = {}
    counts["repeated_denials"] = Counter(db.execute(select(AuditLog.user_id).where(
        AuditLog.company_id == company_id, AuditLog.authorization_result == "DENIED", AuditLog.created_at >= since(5))).scalars())
    counts["excessive_tool_calls"] = Counter(db.execute(select(AuditLog.user_id).where(
        AuditLog.company_id == company_id, AuditLog.tool_name.isnot(None), AuditLog.created_at >= since(5))).scalars())
    counts["bulk_document_access"] = Counter(db.execute(select(AuditLog.user_id).where(
        AuditLog.company_id == company_id, AuditLog.action.like("Viewed confidential document%"), AuditLog.created_at >= since(10))).scalars())
    counts["failed_authentication"] = Counter(db.execute(select(SecurityEvent.user_id).where(
        SecurityEvent.company_id == company_id, SecurityEvent.event_type == "failed_login", SecurityEvent.created_at >= since(15))).scalars())
    for rule in RULES:
        for uid, n in counts[rule["key"]].items():
            if uid is None or n < rule["threshold"]:
                continue
            exists = db.execute(select(SecurityEvent).where(
                SecurityEvent.company_id == company_id, SecurityEvent.user_id == uid, SecurityEvent.event_type == rule["key"],
                SecurityEvent.created_at >= since(rule["window_min"] * 2))).scalars().first()
            if exists:
                continue
            ev = SecurityEvent(company_id=company_id, user_id=uid, event_type=rule["key"], severity=rule["severity"],
                               description=rule["text"].format(n=n), status="OPEN", details={"count": n, "label": LABEL})
            db.add(ev)
            raised.append(rule["key"])
    db.flush()
    return raised

