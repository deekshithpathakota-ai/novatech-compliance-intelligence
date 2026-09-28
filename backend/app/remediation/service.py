"""Remediation planning and execution. Risk-based approval is enforced here, in backend code."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.authorization.permissions import APPROVAL_PERMISSION_BY_RISK
from app.compliance.snapshot import _aware
from app.connectors.base import get_connector
from app.models import (
    ApprovalRequest,
    Control,
    ControlOwner,
    Evidence,
    Finding,
    FindingHistory,
    RemediationAction,
    RemediationPlan,
    RemediationTask,
)

RISK_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


def _count(db: Session, model, company_id: int) -> int:
    return db.execute(select(func.count(model.id)).where(model.company_id == company_id)).scalar_one()


def next_code(db: Session, model, company_id: int, prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).year}-{_count(db, model, company_id) + 1:03d}"


def _owner_id(db: Session, control: Control) -> int | None:
    o = db.execute(select(ControlOwner).where(ControlOwner.control_id == control.id,
                                              ControlOwner.unassigned_at.is_(None))).scalars().first()
    return o.user_id if o else None


def build_playbook(db: Session, finding: Finding) -> tuple[str, str, list[dict]]:
    """Returns (title, rationale, tasks). Access-review playbooks read live counts from the IAM demo connector."""
    ctrl = finding.control
    cat = finding.category
    if cat in ("access_review_overdue", "privileged_access_review_failed"):
        rep = get_connector("iam", db, finding.company_id).get_data("access_report")
        n, priv = rep["inactive_accounts"], rep["privileged_accounts"]
        high = "CRITICAL" if cat == "privileged_access_review_failed" else "HIGH"
        return (
            f"Restore {ctrl.name} and remove stale access",
            "Perform the overdue review now, remove confirmed inactive access, and re-test the control with fresh evidence.",
            [
                {"title": "Generate current access report", "risk": "LOW", "action": "iam.access_report",
                 "evidence": "System access export", "days": 1},
                {"title": f"Review inactive accounts ({n} identified)", "risk": "LOW", "action": "iam.review_inactive",
                 "evidence": "Inactive account list", "days": 2, "dep": 1},
                {"title": f"Review privileged accounts ({priv} active)", "risk": "LOW", "action": "iam.review_privileged",
                 "evidence": "Privileged account list", "days": 2, "dep": 1},
                {"title": "Request manager approval of review results", "risk": "LOW", "action": "notify.manager_review",
                 "evidence": "Manager sign-off (Demo Notification)", "days": 3, "dep": 2},
                {"title": f"Disable {n} confirmed inactive accounts", "risk": high, "action": "iam.disable_accounts",
                 "evidence": "Disablement log", "days": 4, "dep": 4, "params": {"count": n}},
                {"title": "Collect post-remediation access evidence", "risk": "LOW", "action": "evidence.collect_access_report",
                 "evidence": "Access Review Report (post-remediation)", "days": 5, "dep": 5},
                {"title": "Re-test control and verify outcome", "risk": "LOW", "action": "control.retest",
                 "evidence": "Control test record", "days": 5, "dep": 6},
            ],
        )
    if cat == "vendor_assessment_missing":
        return (f"Complete {ctrl.name} for in-scope vendors",
                "Missing assessment evidence; obtain questionnaires/SOC reports and re-test.",
                [{"title": "Request vendor assessment evidence from control owner", "risk": "LOW", "action": "evidence.request",
                  "evidence": "Vendor questionnaires", "days": 5},
                 {"title": "Review returned vendor assessments", "risk": "LOW", "action": None, "evidence": "Review notes", "days": 10, "dep": 1},
                 {"title": "Re-test control and verify outcome", "risk": "LOW", "action": "control.retest", "evidence": "Control test record", "days": 12, "dep": 2}])
    return (f"Remediate: {finding.title}", "Investigate root cause, implement fix, collect evidence, re-test.",
            [{"title": "Confirm root cause with control owner", "risk": "LOW", "action": None, "evidence": "Root cause note", "days": 5},
             {"title": "Implement corrective action", "risk": "MEDIUM", "action": None, "evidence": "Change record", "days": 14, "dep": 1},
             {"title": "Collect updated evidence", "risk": "LOW", "action": "evidence.request", "evidence": "Updated evidence", "days": 16, "dep": 2},
             {"title": "Re-test control and verify outcome", "risk": "LOW", "action": "control.retest", "evidence": "Control test record", "days": 18, "dep": 3}])


def create_plan(db: Session, *, finding: Finding, user_id: int | None, run_id: int | None, by_agent: bool = True) -> RemediationPlan:
    existing = db.execute(select(RemediationPlan).where(
        RemediationPlan.finding_id == finding.id,
        RemediationPlan.status.in_(["DRAFT", "PENDING_APPROVAL", "IN_PROGRESS", "VERIFYING"]),
        RemediationPlan.created_by_agent.is_(True))).scalars().first()
    if existing:
        return existing
    title, rationale, steps = build_playbook(db, finding)
    plan = RemediationPlan(company_id=finding.company_id, code=next_code(db, RemediationPlan, finding.company_id, "REM"),
                           finding_id=finding.id, title=title, rationale=rationale, status="IN_PROGRESS",
                           created_by=user_id, created_by_agent=by_agent, agent_run_id=run_id)
    db.add(plan)
    db.flush()
    owner = _owner_id(db, finding.control)
    today = date.today()
    for i, s in enumerate(steps, start=1):
        db.add(RemediationTask(company_id=finding.company_id, plan_id=plan.id, seq=i, title=s["title"],
                               owner_id=owner, priority="HIGH" if finding.severity in ("HIGH", "CRITICAL") else "MEDIUM",
                               due_date=today + timedelta(days=s["days"]), status="PENDING", depends_on_seq=s.get("dep"),
                               evidence_required=s["evidence"], risk_level=s["risk"], action_type=s["action"],
                               action_params=s.get("params", {})))
    prev = finding.status
    finding.status = "IN_REMEDIATION"
    db.add(FindingHistory(company_id=finding.company_id, finding_id=finding.id, event="remediation_plan_created",
                          from_status=prev, to_status="IN_REMEDIATION", actor_id=user_id,
                          actor_type="agent" if by_agent else "user", note=f"{plan.code}: {title}"))
    db.flush()
    return plan


def tasks_for(db: Session, plan: RemediationPlan) -> list[RemediationTask]:
    return db.execute(select(RemediationTask).where(RemediationTask.plan_id == plan.id).order_by(RemediationTask.seq)).scalars().all()


def approved_for_task(db: Session, task: RemediationTask) -> ApprovalRequest | None:
    return db.execute(select(ApprovalRequest).where(ApprovalRequest.task_id == task.id,
                                                    ApprovalRequest.status == "APPROVED")).scalars().first()


def request_approval(db: Session, *, task: RemediationTask, plan: RemediationPlan, run_id: int | None,
                     reason: str, affected: dict, evidence_refs: list[str]) -> ApprovalRequest:
    existing = db.execute(select(ApprovalRequest).where(ApprovalRequest.task_id == task.id,
                                                        ApprovalRequest.status == "PENDING")).scalars().first()
    if existing:
        return existing
    ar = ApprovalRequest(company_id=task.company_id, code=next_code(db, ApprovalRequest, task.company_id, "APR"),
                         run_id=run_id, plan_id=plan.id, task_id=task.id, action_type=task.action_type or "manual",
                         title=task.title, reason=reason, risk_level=task.risk_level, affected=affected,
                         evidence_refs=evidence_refs,
                         required_permission=APPROVAL_PERMISSION_BY_RISK[task.risk_level] or "APPROVAL_MEDIUM",
                         status="PENDING", requested_by_agent=True)
    db.add(ar)
    task.status = "AWAITING_APPROVAL"
    plan.status = "PENDING_APPROVAL"
    db.flush()
    return ar


def execute_task(db: Session, *, task: RemediationTask, plan: RemediationPlan, finding: Finding, user_id: int | None,
                 approval: ApprovalRequest | None = None) -> dict:
    """Executes one task's action through connectors. HIGH/CRITICAL/MEDIUM tasks require an APPROVED request."""
    if task.risk_level != "LOW":
        approval = approval or approved_for_task(db, task)
        if approval is None or approval.status not in ("APPROVED",):
            raise PermissionError(f"Task '{task.title}' is {task.risk_level} risk and has no approval.")
    iam = get_connector("iam", db, task.company_id)
    at, result, connector = task.action_type, {}, ""
    ctx = plan_context(db, plan)
    if at == "iam.access_report":
        result, connector = iam.get_data("access_report"), iam.name
        ctx["access_report_before"] = {k: result[k] for k in ("inactive_accounts", "privileged_accounts", "total_accounts")}
        ctx["inactive_account_ids"] = result["inactive_account_ids"]
        result = {k: v for k, v in result.items() if k != "inactive_account_ids"}
    elif at == "iam.review_inactive":
        rep = iam.get_data("access_report")
        result, connector = {"inactive_accounts": rep["inactive_accounts"], "sample": rep["inactive_sample"][:10],
                             "terminated_still_active": rep["terminated_still_active"]}, iam.name
    elif at == "iam.review_privileged":
        result, connector = iam.get_data("privileged_accounts"), iam.name
    elif at == "notify.manager_review":
        n = get_connector("email", db, task.company_id)
        result, connector = n.create_action("send", title=f"Manager review requested: {finding.control.name}",
                                            body="Please confirm the inactive accounts list for disablement.",
                                            kind="request", link=f"/findings/{finding.id}"), n.name
    elif at == "iam.disable_accounts":
        ids = ctx.get("inactive_account_ids") or iam.get_data("access_report")["inactive_account_ids"]
        result, connector = iam.create_action("disable_accounts", account_ids=ids), iam.name
        ctx["disabled_accounts"] = result["disabled"]
    elif at == "evidence.request":
        n = get_connector("email", db, task.company_id)
        result, connector = n.create_action("send", title=f"Evidence requested: {finding.control.code} {finding.control.name}",
                                            body=f"Please upload: {task.evidence_required}", kind="evidence_request",
                                            user_id=task.owner_id, link=f"/controls/{finding.control_id}"), n.name
    elif at in ("evidence.collect_access_report", "control.retest"):
        result = {"deferred_to": "verification"}  # executed by the verification service
    else:
        result = {"manual": True, "note": "Manual task — completed by the task owner."}
    if at is not None:
        task.status, task.completed_at = "COMPLETED", datetime.now(timezone.utc)
    act = RemediationAction(company_id=task.company_id, task_id=task.id, action_type=at or "manual", connector=connector,
                            executed_by=user_id, executed_by_agent=True, status="SUCCEEDED", result=result,
                            approval_id=approval.id if approval else None, is_simulated=True)
    db.add(act)
    if approval and approval.status == "APPROVED":
        approval.status = "EXECUTED"
    save_plan_context(plan, ctx)
    db.flush()
    return {"task": task.title, "action": at, "result": result, "connector": connector, "simulated": True}


def plan_context(db: Session, plan: RemediationPlan) -> dict:
    return dict(plan.context or {})


def save_plan_context(plan: RemediationPlan, ctx: dict) -> None:
    plan.context = dict(ctx)  # reassign so SQLAlchemy detects the JSON change


def advance_plan(db: Session, *, plan: RemediationPlan, finding: Finding, user_id: int | None, run_id: int | None,
                 on_task=None) -> dict:
    """Execute ready LOW-risk tasks in order; stop at the first task needing approval."""
    executed, approval = [], None
    for t in tasks_for(db, plan):
        if t.status in ("COMPLETED", "CANCELLED"):
            continue
        if t.action_type in ("evidence.collect_access_report", "control.retest"):
            break  # verification phase
        if t.risk_level != "LOW" and not approved_for_task(db, t):
            reason = f"Remediation of {finding.code} ({finding.title})"
            before = plan_context(db, plan).get("access_report_before", {})
            ev = db.execute(select(Evidence).where(Evidence.control_id == finding.control_id, Evidence.is_current.is_(True))).scalars().first()
            approval = request_approval(db, task=t, plan=plan, run_id=run_id, reason=reason,
                                        affected={"accounts": t.action_params.get("count", before.get("inactive_accounts")),
                                                  "control": finding.control.code, "finding": finding.code},
                                        evidence_refs=[ev.code] if ev else [])
            break
        if t.action_type is None:
            break  # manual task for the owner
        res = execute_task(db, task=t, plan=plan, finding=finding, user_id=user_id)
        executed.append(res)
        if on_task:
            on_task(t, res)
    return {"executed": executed, "approval": approval}


def decide(db: Session, *, approval: ApprovalRequest, principal, decision: str, note: str = "") -> ApprovalRequest:
    need = approval.required_permission
    if not principal.has(need):
        raise PermissionError(need)
    if approval.status != "PENDING":
        raise ValueError(f"Approval is already {approval.status.lower()}.")
    approval.status = {"approve": "APPROVED", "reject": "REJECTED", "changes": "CHANGES_REQUESTED"}[decision]
    approval.decided_by, approval.decided_at, approval.decision_note = principal.user_id, datetime.now(timezone.utc), note
    task = db.get(RemediationTask, approval.task_id) if approval.task_id else None
    plan = db.get(RemediationPlan, approval.plan_id) if approval.plan_id else None
    if decision != "approve" and task:
        task.status = "BLOCKED"
        if plan:
            plan.status = "IN_PROGRESS"
    db.flush()
    return approval


def overdue(t: RemediationTask) -> bool:
    return t.status not in ("COMPLETED", "CANCELLED") and t.due_date is not None and t.due_date < date.today()


def finding_ctrl(db: Session, finding_id: int) -> Control:
    f = db.get(Finding, finding_id)
    return f.control


__all__ = ["create_plan", "advance_plan", "decide", "execute_task", "tasks_for", "_aware"]
