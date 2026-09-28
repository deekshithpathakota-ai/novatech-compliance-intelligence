from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import orchestrator
from app.api.agent import run_json
from app.api.common import approval_json, iso, plan_json, snap_and_cfg
from app.auth.deps import Principal, PermissionDenied, require
from app.compliance.recurring import detect_recurring
from app.compliance.snapshot import OPEN_FINDING_STATUSES, evidence_status
from app.database.session import get_db
from app.models import (ApprovalRequest, AuditLog, ComplianceEvent, Finding, FindingComment, FindingHistory, RemediationPlan,
                        RemediationTask, User, VerificationRecord)
from app.remediation import service as rem
from app.risk.engine import assess_control
from app.schemas.serializers import finding_row
from app.services.audit import log_action
from app.services.tenancy import get_owned
from app.tools.gateway import ToolContext, ToolError, call_tool

router = APIRouter(prefix="/api", tags=["findings"])


@router.get("/findings")
def findings(status: str | None = None, severity: str | None = None, framework: str | None = None,
             recurring: bool | None = None, open_only: bool = False, department: str | None = None,
             p: Principal = Depends(require("FINDINGS_READ")), db: Session = Depends(get_db)):
    snap, cfg = snap_and_cfg(db, p.company_id)
    rec_codes = {r["latest_finding"] for r in detect_recurring(snap)}
    rows = []
    for f in snap.findings:
        r = finding_row(f, snap, rec_codes)
        cv = snap.controls[f.control_id]
        r["risk"] = assess_control(cv, cfg).category if f.status in OPEN_FINDING_STATUSES else None
        rows.append(r)
    if open_only:
        rows = [r for r in rows if r["status"] in OPEN_FINDING_STATUSES]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if severity:
        rows = [r for r in rows if r["severity"] == severity]
    if framework:
        rows = [r for r in rows if framework in r["frameworks"]]
    if department:
        rows = [r for r in rows if r["department"] == department]
    if recurring is not None:
        rows = [r for r in rows if r["recurring"] == recurring]
    return rows


@router.get("/findings/recurring")
def recurring(p: Principal = Depends(require("FINDINGS_READ")), db: Session = Depends(get_db)):
    snap, _ = snap_and_cfg(db, p.company_id)
    return detect_recurring(snap)


@router.get("/findings/{fid}")
def finding_detail(fid: int, p: Principal = Depends(require("FINDINGS_READ")), db: Session = Depends(get_db)):
    f = get_owned(db, Finding, fid, p.company_id, "Finding")
    snap, cfg = snap_and_cfg(db, p.company_id)
    cv = snap.controls[f.control_id]
    rec = next((x for x in detect_recurring(snap, include_closed=True) if x["control_code"] == cv.control.code and x["category"] == f.category), None)
    plans = [pl for pl in snap.plans if pl.finding_id == f.id]
    tasks = {pl.id: [t for t in snap.tasks if t.plan_id == pl.id] for pl in plans}
    for v in tasks.values():
        v.sort(key=lambda t: t.seq)
    approvals = [a for a in snap.approvals if a.plan_id in {pl.id for pl in plans}]
    verifs = [v for v in snap.verifications if v.finding_id == f.id]
    hist = db.execute(select(FindingHistory).where(FindingHistory.finding_id == f.id).order_by(FindingHistory.at)).scalars().all()
    comments = db.execute(select(FindingComment, User).join(User, User.id == FindingComment.user_id, isouter=True)
                          .where(FindingComment.finding_id == f.id).order_by(FindingComment.id)).all()
    trail = db.execute(select(AuditLog).where(AuditLog.company_id == p.company_id, AuditLog.resource.in_(
        [f.code] + [pl.code for pl in plans] + [a.code for a in approvals])).order_by(AuditLog.created_at.desc()).limit(30)).scalars().all()
    risk = assess_control(cv, cfg)
    history_same = [finding_row(x, snap) for x in cv.findings if x.category == f.category and x.id != f.id]
    return {
        **finding_row(f, snap),
        "risk": risk.as_dict(),
        "control": {"id": cv.control.id, "code": cv.control.code, "name": cv.control.name, "status": cv.status,
                    "owner": cv.owner_name, "frequency_days": cv.control.frequency_days, "days_since_test": cv.days_since_test},
        "requirement": next(({"id": r.id, "code": r.code, "title": r.title} for r in snap.requirements.values() if r.id == f.requirement_id), None),
        "evidence": [{"id": e.id, "code": e.code, "name": e.name, "status": evidence_status(e, snap.now)}
                     for e in cv.evidence],
        "historical_findings": history_same,
        "recurrence": rec,
        "plans": [plan_json(pl, tasks[pl.id]) for pl in plans],
        "approvals": [approval_json(a, p) for a in approvals],
        "verifications": [{"code": v.code, "result": v.result, "at": iso(v.verified_at), "checks": v.checks, "notes": v.notes} for v in verifs],
        "history": [{"event": h.event, "from": h.from_status, "to": h.to_status, "at": iso(h.at), "note": h.note,
                     "actor_type": h.actor_type} for h in hist],
        "comments": [{"id": c.id, "body": c.body, "user": u.name if u else "System", "at": iso(c.created_at)} for c, u in comments],
        "audit_trail": [{"at": iso(a.created_at), "actor": a.actor_label, "action": a.action, "result": a.result,
                         "authorization": a.authorization_result} for a in trail],
        "can_close": any(v.result == "PASSED" for v in verifs) and f.status == "READY_FOR_CLOSURE",
    }


@router.post("/findings/{fid}/remediation")
def generate_remediation(fid: int, p: Principal = Depends(require("REMEDIATION_CREATE", "AGENT_USE")), db: Session = Depends(get_db)):
    """Agent-generated remediation: runs the remediation workflow and streams it."""
    f = get_owned(db, Finding, fid, p.company_id, "Finding")
    if f.status in ("CLOSED", "RISK_ACCEPTED"):
        raise HTTPException(409, {"code": "INVALID_STATE", "message": f"{f.code} is already {f.status.lower()}."})
    run = orchestrator.start_run(db, p, f"Create a remediation plan for {f.code}", None,
                                 {"intent": "remediation_plan", "finding_code": f.code})
    return run_json(run)


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


@router.post("/findings/{fid}/comments")
def comment(fid: int, body: CommentIn, p: Principal = Depends(require("FINDINGS_RESPOND")), db: Session = Depends(get_db)):
    f = get_owned(db, Finding, fid, p.company_id, "Finding")
    db.add(FindingComment(company_id=p.company_id, finding_id=f.id, user_id=p.user_id, body=body.body))
    log_action(db, company_id=p.company_id, principal=p, action=f"Commented on {f.code}", resource=f.code, resource_type="finding", result="OK")
    db.commit()
    return {"ok": True}


class AssignIn(BaseModel):
    user_id: int


@router.post("/findings/{fid}/assign")
def assign(fid: int, body: AssignIn, p: Principal = Depends(require("FINDINGS_MANAGE")), db: Session = Depends(get_db)):
    f = get_owned(db, Finding, fid, p.company_id, "Finding")
    u = get_owned(db, User, body.user_id, p.company_id, "User")
    f.owner_id = u.id
    db.add(FindingHistory(company_id=p.company_id, finding_id=f.id, event="owner_assigned", actor_id=p.user_id, note=u.name))
    log_action(db, company_id=p.company_id, principal=p, action=f"Assigned {f.code} to {u.name}", resource=f.code, resource_type="finding", result="OK")
    db.commit()
    return {"ok": True}


@router.post("/findings/{fid}/close")
def close_finding(fid: int, p: Principal = Depends(require("FINDINGS_MANAGE")), db: Session = Depends(get_db)):
    f = get_owned(db, Finding, fid, p.company_id, "Finding")
    passed = db.execute(select(VerificationRecord).where(VerificationRecord.finding_id == f.id, VerificationRecord.result == "PASSED",
                                                         VerificationRecord.company_id == p.company_id)).scalars().first()
    open_plans = db.execute(select(RemediationPlan).where(RemediationPlan.finding_id == f.id,
                                                          RemediationPlan.status.notin_(["COMPLETED", "CANCELLED"]))).scalars().all()
    if not passed or open_plans or f.status != "READY_FOR_CLOSURE":
        raise HTTPException(409, {"code": "VERIFICATION_REQUIRED",
                                  "message": "A finding can only be closed after remediation is completed and verification has passed."})
    prev = f.status
    f.status, f.closed_at = "CLOSED", datetime.now(timezone.utc)
    db.add(FindingHistory(company_id=p.company_id, finding_id=f.id, event="closed", from_status=prev, to_status="CLOSED",
                          actor_id=p.user_id, note=f"Closed with verification {passed.code}"))
    db.add(ComplianceEvent(company_id=p.company_id, event_type="finding_closed", title=f"Finding closed: {f.title}",
                           entity_type="finding", entity_code=f.code, entity_id=f.id, control_id=f.control_id,
                           occurred_at=f.closed_at, actor_id=p.user_id))
    from app.memory.service import remember

    remember(db, company_id=p.company_id, category="FINDING", subject_type="control", subject_id=f.control_id,
             subject_code=f.control.code, summary=f"{f.code} closed after verification {passed.code}.", source_type="finding",
             source_id=f.id, source_label=f.code, outcome="CLOSED", verification="PASSED")
    log_action(db, company_id=p.company_id, principal=p, action=f"Closed finding {f.code}", resource=f.code, resource_type="finding",
               result="CLOSED", evidence_reference=passed.code)
    db.commit()
    return {"ok": True, "status": "CLOSED"}


class ReqEvidenceIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


@router.post("/findings/{fid}/request-evidence")
def request_evidence(fid: int, body: ReqEvidenceIn, p: Principal = Depends(require("EVIDENCE_REQUEST")), db: Session = Depends(get_db)):
    f = get_owned(db, Finding, fid, p.company_id, "Finding")
    try:
        out = call_tool(ToolContext(db=db, principal=p), "request_evidence", {"control_code": f.control.code, "reason": body.reason})
    except ToolError as e:
        raise HTTPException(403 if e.code == "PERMISSION_DENIED" else 400, {"code": e.code, "message": e.message, "why": e.detail})
    db.commit()
    return out


# ---------------------------------------------------------------- remediation
@router.get("/remediation")
def remediation(p: Principal = Depends(require("REMEDIATION_READ", "TASKS_READ_ASSIGNED", any_of=True)), db: Session = Depends(get_db)):
    snap, _ = snap_and_cfg(db, p.company_id)
    fmap = {f.id: f for f in snap.findings}
    out = []
    for pl in sorted(snap.plans, key=lambda x: x.created_at, reverse=True):
        tasks = sorted([t for t in snap.tasks if t.plan_id == pl.id], key=lambda t: t.seq)
        if not p.has("REMEDIATION_READ") and not any(t.owner_id == p.user_id for t in tasks):
            continue
        out.append(plan_json(pl, tasks, fmap.get(pl.finding_id)))
    return out


class ManualPlanIn(BaseModel):
    finding_id: int


@router.post("/remediation")
def create_remediation(body: ManualPlanIn, p: Principal = Depends(require("REMEDIATION_CREATE")), db: Session = Depends(get_db)):
    f = get_owned(db, Finding, body.finding_id, p.company_id, "Finding")
    plan = rem.create_plan(db, finding=f, user_id=p.user_id, run_id=None, by_agent=False)
    log_action(db, company_id=p.company_id, principal=p, action=f"Created remediation plan {plan.code}", resource=plan.code,
               resource_type="remediation", result="CREATED", risk_level="MEDIUM")
    db.commit()
    return plan_json(plan, rem.tasks_for(db, plan), f)


class TaskUpdateIn(BaseModel):
    status: str = Field(pattern=r"^(IN_PROGRESS|COMPLETED)$")


@router.post("/remediation/tasks/{tid}")
def update_task(tid: int, body: TaskUpdateIn, p: Principal = Depends(require("REMEDIATION_EXECUTE")), db: Session = Depends(get_db)):
    t = get_owned(db, RemediationTask, tid, p.company_id, "Task")
    if t.risk_level != "LOW" and body.status == "COMPLETED" and not rem.approved_for_task(db, t) and t.status != "IN_PROGRESS":
        raise HTTPException(409, {"code": "APPROVAL_REQUIRED", "message": f"This {t.risk_level.lower()}-risk task needs approval first."})
    if t.owner_id != p.user_id and not p.has("REMEDIATION_CREATE"):
        raise PermissionDenied(p, "REMEDIATION_CREATE", f"task {tid}")
    t.status = body.status
    if body.status == "COMPLETED":
        t.completed_at = datetime.now(timezone.utc)
    log_action(db, company_id=p.company_id, principal=p, action=f"Task '{t.title}' → {body.status}", resource=str(t.id),
               resource_type="remediation_task", result=body.status)
    db.commit()
    return {"ok": True}


@router.post("/remediation/{plan_id}/verify")
def verify(plan_id: int, p: Principal = Depends(require("REMEDIATION_READ")), db: Session = Depends(get_db)):
    plan = get_owned(db, RemediationPlan, plan_id, p.company_id, "Remediation plan")
    try:
        out = call_tool(ToolContext(db=db, principal=p), "verify_remediation", {"plan_code": plan.code})
    except ToolError as e:
        raise HTTPException(400, {"code": e.code, "message": e.message})
    db.commit()
    return out


# ---------------------------------------------------------------- approvals (risk-based human-in-the-loop)
@router.get("/approvals")
def approvals(status: str | None = None, p: Principal = Depends(require("REMEDIATION_READ", "APPROVAL_MEDIUM", any_of=True)),
              db: Session = Depends(get_db)):
    q = select(ApprovalRequest).where(ApprovalRequest.company_id == p.company_id)
    if status:
        q = q.where(ApprovalRequest.status == status)
    rows = db.execute(q.order_by(ApprovalRequest.created_at.desc())).scalars().all()
    out = []
    for a in rows:
        j = approval_json(a, p)
        if a.plan_id:
            pl = db.get(RemediationPlan, a.plan_id)
            f = db.get(Finding, pl.finding_id)
            j["plan"] = {"id": pl.id, "code": pl.code, "title": pl.title}
            j["finding"] = {"id": f.id, "code": f.code, "title": f.title, "control_code": f.control.code, "control_id": f.control_id}
        out.append(j)
    return out


class ApprovalCreateIn(BaseModel):
    task_id: int
    reason: str = Field(min_length=3, max_length=500)


@router.post("/approvals")
def create_approval(body: ApprovalCreateIn, p: Principal = Depends(require("REMEDIATION_CREATE")), db: Session = Depends(get_db)):
    t = get_owned(db, RemediationTask, body.task_id, p.company_id, "Task")
    plan = db.get(RemediationPlan, t.plan_id)
    if t.risk_level == "LOW":
        raise HTTPException(409, {"code": "NOT_REQUIRED", "message": "Low-risk tasks execute without approval."})
    a = rem.request_approval(db, task=t, plan=plan, run_id=None, reason=body.reason, affected={}, evidence_refs=[])
    a.requested_by, a.requested_by_agent = p.user_id, False
    db.commit()
    return approval_json(a, p)


class DecisionIn(BaseModel):
    note: str = Field(default="", max_length=500)


def _decide(aid: int, decision: str, body: DecisionIn, p: Principal, db: Session):
    a = get_owned(db, ApprovalRequest, aid, p.company_id, "Approval")
    try:
        rem.decide(db, approval=a, principal=p, decision=decision, note=body.note)
    except PermissionError:
        log_action(db, company_id=p.company_id, principal=p, action=f"Attempted to {decision} {a.code}", resource=a.code,
                   resource_type="approval", authorization_result="DENIED", risk_level=a.risk_level, approval_id=a.id,
                   result="DENIED", reason=f"missing {a.required_permission}")
        db.commit()
        raise PermissionDenied(p, a.required_permission, a.code)
    except ValueError as e:
        raise HTTPException(409, {"code": "INVALID_STATE", "message": str(e)})
    log_action(db, company_id=p.company_id, principal=p, action=f"{decision.title()} {a.code}: {a.title}", resource=a.code,
               resource_type="approval", risk_level=a.risk_level, approval_id=a.id, result=a.status)
    db.add(ComplianceEvent(company_id=p.company_id, event_type=f"approval_{a.status.lower()}", title=f"{a.code} {a.status.lower()} by {p.name}",
                           entity_type="approval", entity_code=a.code, occurred_at=datetime.now(timezone.utc), actor_id=p.user_id))
    db.commit()
    run = None
    if decision == "approve":
        t = db.get(RemediationTask, a.task_id) if a.task_id else None
        if t and t.action_type:
            run = orchestrator.start_approval_execution(db, p, a)
        elif t:
            t.status = "IN_PROGRESS"
            db.commit()
    return {"approval": approval_json(a, p), "run": run_json(run) if run else None,
            "message": None if run or decision != "approve" else "Manual action authorised — the task owner performs it; verification runs when evidence is provided."}


@router.post("/approvals/{aid}/approve")
def approve(aid: int, body: DecisionIn = DecisionIn(), p: Principal = Depends(require("AGENT_USE")), db: Session = Depends(get_db)):
    return _decide(aid, "approve", body, p, db)


@router.post("/approvals/{aid}/reject")
def reject(aid: int, body: DecisionIn = DecisionIn(), p: Principal = Depends(require("AGENT_USE")), db: Session = Depends(get_db)):
    return _decide(aid, "reject", body, p, db)


@router.post("/approvals/{aid}/request-changes")
def request_changes(aid: int, body: DecisionIn = DecisionIn(), p: Principal = Depends(require("AGENT_USE")), db: Session = Depends(get_db)):
    return _decide(aid, "changes", body, p, db)
