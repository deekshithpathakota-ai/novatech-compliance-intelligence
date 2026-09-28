"""P4–P5 routes: Policy Lab, Compliance Simulator, Audit Replay, Compliance Graph, Control Drift, Regulatory impact,
scheduled scans, Morning Brief, evidence requests, role workspaces and observability."""
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import mean

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import iso, snap_and_cfg, task_json
from app.auth.deps import Principal, get_principal, require
from app.compliance import advanced
from app.compliance.snapshot import OPEN_FINDING_STATUSES, _aware
from app.connectors.base import get_connector
from app.database.session import get_db
from app.models import (AgentRun, AgentStep, ApprovalRequest, Company, ComplianceEvent, Control, EvidenceRequest, RegulatoryChange,
                        ToolCall, User, VerificationRecord)
from app.risk.engine import assess_control
from app.schemas.serializers import control_row, evidence_row, finding_row
from app.services import scans
from app.services.audit import log_action
from app.services.tenancy import get_owned

router = APIRouter(prefix="/api", tags=["advanced"])


# ---------------------------------------------------------------- P4: Policy Lab
class PolicySimIn(BaseModel):
    policy_code: str = Field(pattern=r"^POL-\d{3}$")
    proposed_interval_days: int = Field(ge=7, le=730)


@router.post("/policies/simulate-change")
def simulate_policy(body: PolicySimIn, p: Principal = Depends(require("POLICIES_MANAGE")), db: Session = Depends(get_db)):
    _, cfg = snap_and_cfg(db, p.company_id)
    try:
        out = advanced.simulate_policy_change(p.company_id, body.policy_code, body.proposed_interval_days, cfg)
    except ValueError as e:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": str(e)})
    log_action(db, company_id=p.company_id, principal=p, action=f"Policy Lab simulation {body.policy_code} → {body.proposed_interval_days} days",
               resource=body.policy_code, resource_type="policy", result=out["summary"])
    db.commit()
    return out


# ---------------------------------------------------------------- P4: Compliance Simulator
class ControlSimIn(BaseModel):
    control_code: str = Field(pattern=r"^C-\d{3}$")
    test_result: str | None = Field(default=None, pattern=r"^(PASS|FAIL|PARTIAL)$")
    evidence_state: str | None = Field(default=None, pattern=r"^(VALID|EXPIRED|MISSING|CONFLICTING)$")
    frequency_days: int | None = Field(default=None, ge=7, le=730)


@router.post("/simulate/control")
def simulate_control(body: ControlSimIn, p: Principal = Depends(require("AUDIT_RUN")), db: Session = Depends(get_db)):
    _, cfg = snap_and_cfg(db, p.company_id)
    try:
        out = advanced.simulate_control(p.company_id, body.control_code, body.test_result, body.evidence_state, body.frequency_days, cfg)
    except ValueError as e:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": str(e)})
    log_action(db, company_id=p.company_id, principal=p, action=f"Compliance Simulator: {body.control_code} ({', '.join(out['changes']) or 'no change'})",
               resource=body.control_code, resource_type="control", result=f"{out['risk']['before']['category']}→{out['risk']['after']['category']}")
    db.commit()
    return out


# ---------------------------------------------------------------- P4: Audit Replay / Graph / Drift / Regulatory impact
@router.get("/audits/{aid}/replay")
def replay(aid: int, p: Principal = Depends(require("AUDITS_READ")), db: Session = Depends(get_db)):
    try:
        return advanced.audit_replay(db, p.company_id, aid)
    except ValueError:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Audit not found."})


@router.get("/graph")
def graph(focus: str | None = None, framework: str | None = None, attention_only: bool = True,
          p: Principal = Depends(require("CONTROLS_READ")), db: Session = Depends(get_db)):
    snap, cfg = snap_and_cfg(db, p.company_id)
    return advanced.compliance_graph(snap, cfg, focus=focus, framework=framework, only_attention=attention_only)


@router.get("/drift")
def drift(p: Principal = Depends(require("CONTROLS_READ")), db: Session = Depends(get_db)):
    snap, _ = snap_and_cfg(db, p.company_id)
    return advanced.control_drift(db, snap)


class ImpactIn(BaseModel):
    change_id: int


@router.post("/regulatory-changes/analyze")
def analyze_change(body: ImpactIn, p: Principal = Depends(require("REQUIREMENTS_READ")), db: Session = Depends(get_db)):
    snap, cfg = snap_and_cfg(db, p.company_id)
    try:
        out = advanced.regulatory_impact(db, snap, body.change_id, cfg)
    except ValueError:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": "Regulatory change not found."})
    ch = db.get(RegulatoryChange, body.change_id)
    if p.has("POLICIES_MANAGE") and ch.status in ("IMPACT_ASSESSMENT_REQUIRED", "NEW"):
        ch.status = "UNDER_REVIEW"
    log_action(db, company_id=p.company_id, principal=p, action=f"Impact analysis {out['change']['code']}", resource=out["change"]["code"],
               resource_type="regulatory_change", result=out["new_risk"])
    db.commit()
    return out


# ---------------------------------------------------------------- P5: scans + brief
@router.get("/scans")
def scans_state(p: Principal = Depends(require("AUDITS_READ")), db: Session = Depends(get_db)):
    c = db.get(Company, p.company_id)
    runs = db.execute(select(AgentRun).where(AgentRun.company_id == p.company_id, AgentRun.intent == "scheduled_scan")
                      .order_by(AgentRun.id.desc()).limit(20)).scalars().all()
    return {"schedule": scans.get_schedule(c), "label": "Prototype in-process scheduler",
            "history": [{"id": r.id, "trigger": (r.result or {}).get("trigger"), "status": r.status, "at": iso(r.started_at),
                         "duration_ms": r.duration_ms, "summary": (r.result or {}).get("summary")} for r in runs]}


class ScheduleIn(BaseModel):
    frequency: str = Field(pattern=r"^(daily|weekly|monthly)$")
    enabled: bool = True


@router.put("/scans/schedule")
def set_schedule(body: ScheduleIn, p: Principal = Depends(require("SETTINGS_MANAGE", "AUDIT_RUN", any_of=True)), db: Session = Depends(get_db)):
    s = scans.set_schedule(db, db.get(Company, p.company_id), frequency=body.frequency, enabled=body.enabled)
    log_action(db, company_id=p.company_id, principal=p, action=f"Scan schedule set to {body.frequency} ({'on' if body.enabled else 'off'})",
               resource="scan_schedule", resource_type="settings", result="UPDATED")
    db.commit()
    return s


@router.post("/scans/run")
def run_scan_now(p: Principal = Depends(require("AUDIT_RUN")), db: Session = Depends(get_db)):
    out = scans.run_scan(db, p.company_id, trigger="manual", requested_by=p.user_id)
    log_action(db, company_id=p.company_id, principal=p, action="Ran compliance scan", resource=f"run {out['run_id']}",
               resource_type="scan", result=f"{out['alerts']} alerts", agent_run_id=out["run_id"])
    db.commit()
    return out


@router.get("/brief")
def brief(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return scans.morning_brief(db, p)


# ---------------------------------------------------------------- P5: evidence request workflow
class EvReqIn(BaseModel):
    control_id: int
    evidence_required: str = Field(min_length=3, max_length=250)
    reason: str = Field(min_length=3, max_length=500)
    due_date: date


def evreq_json(r: EvidenceRequest, db: Session) -> dict:
    c = db.get(Control, r.control_id)
    rec = db.get(User, r.recipient_id) if r.recipient_id else None
    by = db.get(User, r.requested_by) if r.requested_by else None
    return {"id": r.id, "code": r.code, "control": {"id": c.id, "code": c.code, "name": c.name},
            "recipient": rec.name if rec else None, "recipient_id": r.recipient_id,
            "requested_by": "Compliance Agent" if r.requested_by_agent else (by.name if by else None),
            "evidence_required": r.evidence_required, "reason": r.reason, "due_date": iso(r.due_date), "status": r.status,
            "overdue": r.status == "OPEN" and r.due_date < date.today(), "created_at": iso(r.created_at),
            "delivery": "Demo Notification"}


@router.get("/evidence-requests")
def list_requests(p: Principal = Depends(require("EVIDENCE_READ", "EVIDENCE_UPLOAD", any_of=True)), db: Session = Depends(get_db)):
    q = select(EvidenceRequest).where(EvidenceRequest.company_id == p.company_id)
    if not p.has("EVIDENCE_REQUEST"):
        q = q.where(EvidenceRequest.recipient_id == p.user_id)
    return [evreq_json(r, db) for r in db.execute(q.order_by(EvidenceRequest.id.desc())).scalars()]


@router.post("/evidence-requests")
def create_request(body: EvReqIn, p: Principal = Depends(require("EVIDENCE_REQUEST")), db: Session = Depends(get_db)):
    c = get_owned(db, Control, body.control_id, p.company_id, "Control")
    snap, _ = snap_and_cfg(db, p.company_id)
    cv = snap.controls[c.id]
    if body.due_date < date.today():
        raise HTTPException(422, {"code": "INVALID_INPUT", "message": "Due date must be today or later."})
    n = len(db.execute(select(EvidenceRequest.id).where(EvidenceRequest.company_id == p.company_id)).all())
    note = get_connector("email", db, p.company_id).create_action(
        "send", title=f"Evidence requested: {c.code} {c.name}", body=f"{body.evidence_required} — {body.reason}",
        kind="evidence_request", user_id=cv.owner_id, link="/my-work", severity="warning")
    r = EvidenceRequest(company_id=p.company_id, code=f"EVR-{date.today().year}-{n + 1:03d}", control_id=c.id,
                        requested_by=p.user_id, recipient_id=cv.owner_id, evidence_required=body.evidence_required,
                        reason=body.reason, due_date=body.due_date, notification_id=note["notification_id"])
    db.add(r)
    db.add(ComplianceEvent(company_id=p.company_id, event_type="evidence_requested", title=f"Evidence requested: {c.code} {body.evidence_required}",
                           entity_type="evidence_request", entity_code=r.code, control_id=c.id,
                           occurred_at=datetime.now(timezone.utc), actor_id=p.user_id))
    log_action(db, company_id=p.company_id, principal=p, action=f"Requested evidence for {c.code} from {cv.owner_name}", resource=c.code,
               resource_type="evidence_request", result="SENT (Demo Notification)")
    db.commit()
    return evreq_json(r, db)


@router.post("/evidence-requests/{rid}/cancel")
def cancel_request(rid: int, p: Principal = Depends(require("EVIDENCE_REQUEST")), db: Session = Depends(get_db)):
    r = get_owned(db, EvidenceRequest, rid, p.company_id, "Evidence request")
    r.status = "CANCELLED"
    log_action(db, company_id=p.company_id, principal=p, action=f"Cancelled {r.code}", resource=r.code, resource_type="evidence_request", result="CANCELLED")
    db.commit()
    return evreq_json(r, db)


# ---------------------------------------------------------------- P5: role workspaces
@router.get("/workspace/me")
def my_workspace(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    snap, cfg = snap_and_cfg(db, p.company_id)
    mine = [cv for cv in snap.controls.values() if cv.owner_id == p.user_id]
    ids = {cv.control.id for cv in mine}
    active = {pl.id for pl in snap.plans if pl.status not in ("COMPLETED", "CANCELLED")}
    tasks = sorted([t for t in snap.tasks if t.plan_id in active and t.owner_id == p.user_id], key=lambda t: (t.due_date or date.max))
    reqs = db.execute(select(EvidenceRequest).where(EvidenceRequest.company_id == p.company_id, EvidenceRequest.recipient_id == p.user_id,
                                                    EvidenceRequest.status == "OPEN")).scalars().all()
    upcoming = sorted([(cv, _aware(cv.tests[0].tested_at) + timedelta(days=cv.control.frequency_days)) for cv in mine if cv.tests],
                      key=lambda x: x[1])
    return {
        "controls": [control_row(cv, assess_control(cv, cfg), snap) for cv in mine],
        "evidence_requests": [evreq_json(r, db) for r in reqs],
        "open_findings": [finding_row(f, snap) for f in snap.findings if f.control_id in ids and f.status in OPEN_FINDING_STATUSES],
        "tasks": [task_json(t) | {"plan_id": t.plan_id} for t in tasks if t.status not in ("COMPLETED", "CANCELLED")],
        "upcoming_tests": [{"control_id": cv.control.id, "code": cv.control.code, "name": cv.control.name, "due": due.date().isoformat(),
                            "overdue": due < snap.now} for cv, due in upcoming],
        "evidence": [evidence_row(e, snap) for cv in mine for e in cv.evidence],
    }


# ---------------------------------------------------------------- P5: observability
@router.get("/observability")
def observability(p: Principal = Depends(require("DASHBOARD_READ")), db: Session = Depends(get_db)):
    runs = db.execute(select(AgentRun).where(AgentRun.company_id == p.company_id)).scalars().all()
    tools = db.execute(select(ToolCall).where(ToolCall.company_id == p.company_id)).scalars().all()
    vers = db.execute(select(VerificationRecord).where(VerificationRecord.company_id == p.company_id,
                                                       VerificationRecord.verified_by_agent.is_(True))).scalars().all()
    approvals = db.execute(select(ApprovalRequest).where(ApprovalRequest.company_id == p.company_id,
                                                         ApprovalRequest.decided_at.isnot(None))).scalars().all()
    done = [r for r in runs if r.status in ("COMPLETED", "AWAITING_APPROVAL")]
    durs = sorted(r.duration_ms for r in runs if r.duration_ms)
    by_tool: dict[str, list[ToolCall]] = defaultdict(list)
    for t in tools:
        by_tool[t.tool_name].append(t)
    retrieval = [t.duration_ms for t in by_tool.get("search_documents", [])]
    per_day = Counter(_aware(r.started_at).date().isoformat() for r in runs)
    waits = [(_aware(a.decided_at) - _aware(a.created_at)).total_seconds() / 60 for a in approvals if a.requested_by_agent]
    steps = db.execute(select(AgentStep.event_type).where(AgentStep.company_id == p.company_id)).scalars().all()
    tok_in, tok_out = sum(r.tokens_in for r in runs), sum(r.tokens_out for r in runs)
    return {
        "label": "OpenTelemetry-compatible spans + DB-backed run metrics · prompt contents are never recorded",
        "kpis": {"agent_runs": len(runs), "success_rate": round(len(done) / len(runs) * 100) if runs else None,
                 "avg_run_ms": round(mean(durs)) if durs else None, "p95_run_ms": durs[max(0, math.ceil(len(durs) * 0.95) - 1)] if durs else None,
                 "tool_calls": len(tools), "tool_failures": sum(t.status == "FAILED" for t in tools),
                 "tool_denials": sum(t.status == "DENIED" for t in tools),
                 "verification_failures": sum(v.result != "PASSED" for v in vers), "verifications": len(vers),
                 "retrieval_avg_ms": round(mean(retrieval), 1) if retrieval else None,
                 "approval_wait_min": round(mean(waits), 1) if waits else None,
                 "llm_calls": sum(r.llm_calls for r in runs), "tokens_in": tok_in, "tokens_out": tok_out,
                 "estimated_cost_usd": round((tok_in * 1.25 + tok_out * 10) / 1_000_000, 4)},
        "cost_label": "Prototype estimate",
        "runs_by_intent": [{"intent": k, "count": v} for k, v in Counter(r.intent for r in runs).most_common()],
        "runs_per_day": [{"date": d, "runs": per_day.get(d, 0)} for d in
                         [(date.today() - timedelta(days=i)).isoformat() for i in range(13, -1, -1)]],
        "tools": sorted([{"tool": k, "calls": len(v), "failures": sum(t.status == "FAILED" for t in v),
                          "denials": sum(t.status == "DENIED" for t in v), "avg_ms": round(mean(t.duration_ms for t in v), 1)}
                         for k, v in by_tool.items()], key=lambda x: -x["calls"]),
        "events": [{"event": k, "count": v} for k, v in Counter(steps).most_common(12)],
        "recent_runs": [{"id": r.id, "intent": r.intent, "status": r.status, "engine": r.engine, "started_at": iso(r.started_at),
                         "duration_ms": r.duration_ms, "objective": r.objective[:120]}
                        for r in sorted(runs, key=lambda r: r.id, reverse=True)[:15]],
    }
