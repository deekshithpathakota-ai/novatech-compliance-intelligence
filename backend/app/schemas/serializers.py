"""Shared JSON shapes for API responses and agent tool output."""
from __future__ import annotations

from datetime import timedelta

from app.compliance.snapshot import ControlView, Snapshot, _aware, evidence_freshness, evidence_status
from app.models import Evidence, Finding
from app.risk.engine import RiskResult


def iso(dt):
    return _aware(dt).isoformat() if hasattr(dt, "tzinfo") and dt is not None else (dt.isoformat() if dt else None)


def evidence_row(e: Evidence, snap: Snapshot) -> dict:
    cv = snap.controls.get(e.control_id)
    return {
        "id": e.id, "code": e.code, "name": e.name, "description": e.description,
        "control_id": e.control_id, "control_code": cv.control.code if cv else None,
        "control_name": cv.control.name if cv else None,
        "frameworks": cv.framework_codes if cv else [],
        "owner": cv.owner_name if cv else None, "source": e.source,
        "collected_at": iso(e.collected_at), "valid_until": iso(e.valid_until),
        "status": evidence_status(e, snap.now), "freshness": evidence_freshness(e, snap.now),
        "verification": e.verification_status, "sha256": e.sha256, "document_id": e.document_id, "page": e.page,
        "audit_id": e.audit_id, "completeness": e.completeness, "is_current": e.is_current, "extracted": e.extracted,
    }


def control_row(cv: ControlView, risk: RiskResult | None, snap: Snapshot) -> dict:
    c = cv.control
    latest = cv.tests[0] if cv.tests else None
    nxt = (_aware(latest.tested_at) + timedelta(days=c.frequency_days)) if latest else None
    return {
        "id": c.id, "code": c.code, "name": c.name, "description": c.description, "domain": c.domain,
        "department": c.department.name if c.department else None, "owner": cv.owner_name, "owner_id": cv.owner_id,
        "frameworks": cv.framework_codes, "requirements": cv.requirement_codes, "frequency_days": c.frequency_days,
        "criticality": c.criticality, "automation": c.automation,
        "last_tested": iso(latest.tested_at) if latest else None, "last_result": latest.result if latest else None,
        "days_since_test": cv.days_since_test, "next_test": nxt.isoformat() if nxt else None,
        "next_test_overdue": bool(nxt and nxt < snap.now),
        "evidence_status": cv.evidence_state, "evidence_count": len(cv.evidence),
        "historical_failures": sum(1 for t in cv.tests if t.result in ("FAIL", "PARTIAL")),
        "findings_total": len(cv.findings), "open_findings": len(cv.open_findings),
        "status": cv.status, "risk": risk.as_dict() if risk else None,
        "risk_category": risk.category if risk else None, "risk_score": risk.score if risk else None,
        "requirement_changed": cv.requirement_changed, "misaligned": cv.misaligned,
    }


def finding_row(f: Finding, snap: Snapshot, recurring_codes: set[str] | None = None) -> dict:
    cv = snap.controls.get(f.control_id)
    audit = next((a for a in snap.audits if a.id == f.audit_id), None)
    prior = [x for x in (cv.findings if cv else []) if x.category == f.category and x.id != f.id
             and _aware(x.detected_at) < _aware(f.detected_at)]
    return {
        "id": f.id, "code": f.code, "title": f.title, "description": f.description, "category": f.category,
        "control_id": f.control_id, "control_code": cv.control.code if cv else None,
        "control_name": cv.control.name if cv else None, "frameworks": cv.framework_codes if cv else [],
        "department": cv.control.department.name if cv and cv.control.department else None,
        "severity": f.severity, "status": f.status, "owner": f.owner.name if f.owner else None,
        "due_date": f.due_date.isoformat() if f.due_date else None, "detected_at": iso(f.detected_at),
        "closed_at": iso(f.closed_at), "updated_at": iso(f.updated_at), "root_cause": f.root_cause,
        "source": f.source, "audit": {"id": audit.id, "code": audit.code, "name": audit.name} if audit else None,
        "recurring": bool(prior) or (recurring_codes is not None and f.code in recurring_codes),
        "prior_occurrences": len(prior),
    }
