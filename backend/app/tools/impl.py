"""Agent tools. Each one is registered with its permission, risk level and approval requirement and is only
reachable through the Tool Gateway."""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.compliance.gaps import detect_gaps
from app.compliance.readiness import posture, readiness, what_changed
from app.compliance.recurring import detect_recurring
from app.compliance.snapshot import OPEN_FINDING_STATUSES, _aware
from app.memory.service import recall, remember, serialize
from app.models import ApprovalRequest, Finding, RemediationPlan, RemediationTask
from app.rag.retrieval import RetrievalFilters, hybrid_search
from app.remediation import service as rem
from app.risk.engine import assess_control
from app.schemas.serializers import control_row, evidence_row, finding_row
from app.tools.gateway import ToolContext, ToolError, tool
from app.verification.service import verify_plan

CODE = r"^[A-Za-z]{1,5}-[A-Za-z0-9-]{1,20}$"


class NoArgs(BaseModel):
    pass


class ControlArg(BaseModel):
    control_code: str = Field(pattern=CODE)


class OptControl(BaseModel):
    control_code: str | None = Field(default=None, pattern=CODE)


def _cv(ctx: ToolContext, code: str):
    cv = ctx.snapshot().by_code(code)
    if cv is None:
        raise ToolError("NOT_FOUND", f"Control {code} not found.")
    return cv


# ---------------------------------------------------------------- read tools
class ReqArgs(BaseModel):
    query: str | None = Field(default=None, max_length=200)
    framework: str | None = Field(default=None, max_length=40)


@tool("search_requirements", description="List/search framework requirements in scope", permission="REQUIREMENTS_READ", args=ReqArgs)
def search_requirements(ctx: ToolContext, a: ReqArgs) -> dict:
    snap = ctx.snapshot()
    reqs = snap.in_scope_requirements()
    if a.framework:
        reqs = [r for r in reqs if snap.frameworks[r.framework_id].code == a.framework]
    if a.query:
        q = a.query.lower()
        reqs = [r for r in reqs if q in (r.title + r.description + r.code).lower()]
    unmapped = [r.code for r in reqs if not snap.req_to_controls.get(r.id)]
    changed = [r.code for r in reqs if r.status == "changed"]
    fws = sorted({snap.frameworks[r.framework_id].code for r in reqs})
    return {"count": len(reqs), "frameworks": fws, "unmapped": unmapped, "changed": changed,
            "_summary": f"{len(reqs)} requirements across {', '.join(fws) or '—'}"}


class ControlsArgs(BaseModel):
    status: str | None = Field(default=None, max_length=20)
    codes: list[str] | None = None


@tool("get_controls", description="Retrieve mapped controls with derived status and risk", permission="CONTROLS_READ", args=ControlsArgs)
def get_controls(ctx: ToolContext, a: ControlsArgs) -> dict:
    snap, cfg = ctx.snapshot(), ctx.risk_cfg()
    cvs = snap.in_scope_controls()
    if a.codes:
        cvs = [cv for cv in cvs if cv.control.code in a.codes]
    rows = [control_row(cv, assess_control(cv, cfg), snap) for cv in cvs]
    if a.status:
        rows = [r for r in rows if r["status"] == a.status]
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"count": len(rows), "status_counts": counts, "controls": rows,
            "_summary": f"{len(rows)} controls · " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))}


@tool("get_control_history", description="Control ownership, tests, findings and events over time", permission="CONTROLS_READ", args=ControlArg)
def get_control_history(ctx: ToolContext, a: ControlArg) -> dict:
    cv = _cv(ctx, a.control_code)
    return {"control": cv.control.code, "owner_history": cv.owner_history,
            "tests": [{"code": t.code, "at": _aware(t.tested_at).date().isoformat(), "result": t.result} for t in cv.tests],
            "findings": [{"code": f.code, "title": f.title, "status": f.status, "severity": f.severity,
                          "detected": _aware(f.detected_at).date().isoformat()} for f in cv.findings],
            "_summary": f"{len(cv.tests)} tests, {len(cv.findings)} findings"}


@tool("get_control_test_results", description="Latest control test results and test procedure", permission="CONTROLS_READ", args=ControlArg)
def get_control_test_results(ctx: ToolContext, a: ControlArg) -> dict:
    cv = _cv(ctx, a.control_code)
    t = cv.tests[0] if cv.tests else None
    return {"control": cv.control.code, "latest": {"code": t.code, "result": t.result, "at": _aware(t.tested_at).isoformat(),
                                                    "questions": t.questions, "notes": t.notes} if t else None,
            "days_since_test": cv.days_since_test, "frequency_days": cv.control.frequency_days,
            "_summary": f"latest {t.result if t else 'none'} · {cv.days_since_test} days ago"}


class EvArgs(BaseModel):
    control_code: str | None = Field(default=None, pattern=CODE)
    status: str | None = Field(default=None, max_length=20)


@tool("search_evidence", description="Evidence items with freshness and status", permission="EVIDENCE_READ", args=EvArgs)
def search_evidence(ctx: ToolContext, a: EvArgs) -> dict:
    snap = ctx.snapshot()
    items = [e for cv in snap.in_scope_controls() for e in cv.evidence
             if not a.control_code or cv.control.code == a.control_code]
    rows = [evidence_row(e, snap) for e in items]
    if a.status:
        rows = [r for r in rows if r["status"] == a.status]
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    missing = [cv.control.code for cv in snap.in_scope_controls() if not cv.evidence]
    return {"count": len(rows), "status_counts": counts, "missing_for_controls": missing, "evidence": rows,
            "_summary": f"{len(rows)} evidence items · " + ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))}


@tool("get_audit_history", description="Previous audits and their findings (audit memory)", permission="AUDITS_READ", args=OptControl)
def get_audit_history(ctx: ToolContext, a: OptControl) -> dict:
    snap = ctx.snapshot()
    audits = sorted([x for x in snap.audits if x.status == "completed"], key=lambda x: x.start_date, reverse=True)
    findings = snap.findings
    if a.control_code:
        cv = _cv(ctx, a.control_code)
        findings = cv.findings
    by_audit = {}
    for f in findings:
        if f.audit_id:
            by_audit.setdefault(f.audit_id, []).append(f)
    return {"audits": [{"code": x.code, "name": x.name, "date": x.start_date.isoformat(), "outcome": x.outcome,
                        "findings": [{"code": f.code, "title": f.title, "status": f.status} for f in by_audit.get(x.id, [])]}
                       for x in audits],
            "historical_findings": len(findings),
            "_summary": f"{len(audits)} previous audits, {len(findings)} historical findings"}


class FindArgs(BaseModel):
    status: str | None = Field(default=None, max_length=30)
    severity: str | None = Field(default=None, max_length=20)
    control_code: str | None = Field(default=None, pattern=CODE)
    open_only: bool = False


@tool("get_findings", description="Findings with recurrence flags", permission="FINDINGS_READ", args=FindArgs)
def get_findings(ctx: ToolContext, a: FindArgs) -> dict:
    snap = ctx.snapshot()
    ids = {cv.control.id for cv in snap.in_scope_controls()}
    fs = [f for f in snap.findings if f.control_id in ids]
    if a.open_only:
        fs = [f for f in fs if f.status in OPEN_FINDING_STATUSES]
    if a.status:
        fs = [f for f in fs if f.status == a.status]
    if a.severity:
        fs = [f for f in fs if f.severity == a.severity]
    if a.control_code:
        fs = [f for f in fs if snap.controls[f.control_id].control.code == a.control_code]
    rows = [finding_row(f, snap) for f in fs]
    return {"count": len(rows), "findings": rows, "_summary": f"{len(rows)} findings"}


class RemStatusArgs(BaseModel):
    finding_code: str | None = Field(default=None, pattern=CODE)


@tool("get_remediation_status", description="Remediation plans, tasks and overdue items", permission="REMEDIATION_READ", args=RemStatusArgs)
def get_remediation_status(ctx: ToolContext, a: RemStatusArgs) -> dict:
    snap = ctx.snapshot()
    plans = snap.plans
    if a.finding_code:
        f = next((x for x in snap.findings if x.code == a.finding_code), None)
        plans = [p for p in plans if f and p.finding_id == f.id]
    active = [p for p in plans if p.status not in ("COMPLETED", "CANCELLED")]
    overdue = [t for t in snap.tasks if any(p.id == t.plan_id for p in active) and rem.overdue(t)]
    return {"plans": len(plans), "active": len(active), "overdue_tasks": len(overdue),
            "overdue": [{"title": t.title, "due": t.due_date.isoformat()} for t in overdue],
            "_summary": f"{len(active)} active plans, {len(overdue)} overdue tasks"}


class GapArgs(BaseModel):
    pass


@tool("detect_compliance_gaps", description="Run the 16-check deterministic gap detection engine", permission="CONTROLS_READ", args=GapArgs)
def detect_compliance_gaps(ctx: ToolContext, a: GapArgs) -> dict:
    g = detect_gaps(ctx.snapshot())
    return {**g, "_summary": f"{g['gap_count']} potential gaps · {g['expiring_evidence']} evidence expiring"}


@tool("find_recurring_findings", description="Detect recurring findings across audits", permission="FINDINGS_READ", args=NoArgs)
def find_recurring_findings(ctx: ToolContext, a: NoArgs) -> dict:
    rec = detect_recurring(ctx.snapshot())
    return {"count": len(rec), "items": rec, "_summary": f"{len(rec)} recurring findings"}


@tool("assess_risk", description="Deterministic NovaTech Prototype Risk Model over in-scope controls", permission="CONTROLS_READ", args=OptControl)
def assess_risk(ctx: ToolContext, a: OptControl) -> dict:
    snap, cfg = ctx.snapshot(), ctx.risk_cfg()
    if a.control_code:
        cv = _cv(ctx, a.control_code)
        r = assess_control(cv, cfg)
        return {"control": cv.control.code, **r.as_dict(), "_summary": f"{cv.control.code} {r.category} ({r.score})"}
    p = posture(snap, cfg)
    return {"risk_counts": p["risk_counts"], "top_risks": p["top_risks"], "readiness": p["readiness"],
            "_summary": f"{p['critical_risks']} critical, {p['high_risks']} high-risk controls"}


@tool("calculate_readiness", description="Compute NovaTech Compliance Readiness Indicators", permission="AUDITS_READ", args=NoArgs)
def calculate_readiness(ctx: ToolContext, a: NoArgs) -> dict:
    r = readiness(ctx.snapshot())
    return {**r, "_summary": f"overall {r['overall']}%"}


@tool("compare_since_last_audit", description="What changed since the last completed audit", permission="AUDITS_READ", args=NoArgs)
def compare_since_last_audit(ctx: ToolContext, a: NoArgs) -> dict:
    w = what_changed(ctx.snapshot())
    return {**w, "_summary": ", ".join(f"{v} {k}" for k, v in w.get("counts", {}).items())}


class SearchArgs(BaseModel):
    query: str = Field(min_length=2, max_length=400)
    document_type: str | None = Field(default=None, max_length=30)


@tool("search_documents", description="Permission-filtered hybrid search over policies and evidence documents", permission="AGENT_USE", args=SearchArgs)
def search_documents(ctx: ToolContext, a: SearchArgs) -> dict:
    res = hybrid_search(ctx.db, ctx.principal, a.query, k=5, filters=RetrievalFilters(document_type=a.document_type))
    return {**res, "_summary": f"{len(res['results'])} passages in {res['latency_ms']}ms"}


class MemArgs(BaseModel):
    query: str | None = Field(default=None, max_length=300)
    subject_code: str | None = Field(default=None, pattern=CODE)
    category: str | None = Field(default=None, max_length=20)


@tool("search_compliance_memory", description="Recall persistent audit/remediation memory", permission="MEMORY_READ", args=MemArgs)
def search_compliance_memory(ctx: ToolContext, a: MemArgs) -> dict:
    rows = recall(ctx.db, ctx.company_id, subject_code=a.subject_code, category=a.category, query=a.query, limit=12)
    snap = ctx.snapshot()
    return {"count": len(rows), "records": [serialize(r, snap) for r in rows], "_summary": f"{len(rows)} memory records"}


# ---------------------------------------------------------------- write tools (backend-enforced risk)
class FindingArg(BaseModel):
    finding_code: str = Field(pattern=CODE)


def _finding(ctx: ToolContext, code: str) -> Finding:
    f = ctx.db.execute(select(Finding).where(Finding.company_id == ctx.company_id, Finding.code == code)).scalar_one_or_none()
    if not f:
        raise ToolError("NOT_FOUND", f"Finding {code} not found.")
    return f


@tool("create_remediation_task", description="Create a multi-step remediation plan for a finding", permission="REMEDIATION_CREATE",
      risk="MEDIUM", args=FindingArg, mutates=True, safe_to_retry=False)
def create_remediation_task(ctx: ToolContext, a: FindingArg) -> dict:
    f = _finding(ctx, a.finding_code)
    if f.status in ("CLOSED", "RISK_ACCEPTED"):
        raise ToolError("INVALID_STATE", f"{f.code} is already {f.status.lower()}.")
    plan = rem.create_plan(ctx.db, finding=f, user_id=ctx.principal.user_id, run_id=ctx.run_id)
    tasks = rem.tasks_for(ctx.db, plan)
    return {"plan": {"id": plan.id, "code": plan.code, "title": plan.title, "status": plan.status},
            "tasks": [{"seq": t.seq, "title": t.title, "risk": t.risk_level, "status": t.status} for t in tasks],
            "_summary": f"{plan.code} with {len(tasks)} tasks"}


class PlanArg(BaseModel):
    plan_code: str = Field(pattern=CODE)


def _plan(ctx: ToolContext, code: str) -> RemediationPlan:
    p = ctx.db.execute(select(RemediationPlan).where(RemediationPlan.company_id == ctx.company_id,
                                                     RemediationPlan.code == code)).scalar_one_or_none()
    if not p:
        raise ToolError("NOT_FOUND", f"Plan {code} not found.")
    return p


@tool("update_remediation_task", description="Advance a plan: run ready low-risk tasks, request approval for risky ones",
      permission="REMEDIATION_CREATE", risk="MEDIUM", args=PlanArg, mutates=True, safe_to_retry=False)
def update_remediation_task(ctx: ToolContext, a: PlanArg) -> dict:
    plan = _plan(ctx, a.plan_code)
    f = ctx.db.get(Finding, plan.finding_id)
    out = rem.advance_plan(ctx.db, plan=plan, finding=f, user_id=ctx.principal.user_id, run_id=ctx.run_id,
                           on_task=ctx.cache.get("on_task"))
    ap = out["approval"]
    return {"executed": out["executed"], "approval": ({"id": ap.id, "code": ap.code, "title": ap.title,
                                                       "risk_level": ap.risk_level, "reason": ap.reason,
                                                       "affected": ap.affected, "evidence_refs": ap.evidence_refs,
                                                       "required_permission": ap.required_permission} if ap else None),
            "_summary": f"{len(out['executed'])} low-risk task(s) executed" + (f"; approval {ap.code} required" if ap else "")}


class ExecArgs(BaseModel):
    task_id: int = Field(gt=0)


@tool("execute_remediation_action", description="Execute an approved remediation action via a connector",
      permission="REMEDIATION_EXECUTE", risk="HIGH", args=ExecArgs, mutates=True, safe_to_retry=False)
def execute_remediation_action(ctx: ToolContext, a: ExecArgs) -> dict:
    t = ctx.db.execute(select(RemediationTask).where(RemediationTask.company_id == ctx.company_id,
                                                     RemediationTask.id == a.task_id)).scalar_one_or_none()
    if not t:
        raise ToolError("NOT_FOUND", "Task not found.")
    approval = rem.approved_for_task(ctx.db, t)
    if t.risk_level != "LOW" and (approval is None or approval.id != ctx.approval_id):
        # backend-enforced: an approval recorded by a human, matched to this exact task
        raise ToolError("APPROVAL_REQUIRED", f"'{t.title}' is {t.risk_level} risk and requires approval.",
                        {"risk_level": t.risk_level})
    plan = ctx.db.get(RemediationPlan, t.plan_id)
    f = ctx.db.get(Finding, plan.finding_id)
    res = rem.execute_task(ctx.db, task=t, plan=plan, finding=f, user_id=ctx.principal.user_id, approval=approval)
    plan.status = "IN_PROGRESS"
    return {**res, "_summary": f"{t.title}: done"}


class ReqEvArgs(BaseModel):
    control_code: str = Field(pattern=CODE)
    reason: str = Field(min_length=3, max_length=300)


@tool("request_evidence", description="Send an evidence request to the control owner (Demo Notification)",
      permission="EVIDENCE_REQUEST", args=ReqEvArgs, mutates=True, safe_to_retry=False)
def request_evidence(ctx: ToolContext, a: ReqEvArgs) -> dict:
    from app.connectors.base import get_connector

    cv = _cv(ctx, a.control_code)
    r = get_connector("email", ctx.db, ctx.company_id).create_action(
        "send", title=f"Evidence requested: {cv.control.code} {cv.control.name}", body=a.reason, kind="evidence_request",
        user_id=cv.owner_id, link=f"/controls/{cv.control.id}")
    return {**r, "recipient": cv.owner_name, "control": cv.control.code, "_summary": f"Requested from {cv.owner_name}"}


@tool("verify_remediation", description="Verify remediation outcome (expected vs actual) and update status",
      permission="REMEDIATION_READ", args=PlanArg, mutates=True)
def verify_remediation(ctx: ToolContext, a: PlanArg) -> dict:
    plan = _plan(ctx, a.plan_code)
    out = verify_plan(ctx.db, plan=plan, user_id=ctx.principal.user_id, run_id=ctx.run_id, emit=ctx.cache.get("emit"))
    return {**out, "_summary": f"verification {out['result']}"}


class MemWriteArgs(BaseModel):
    subject_code: str = Field(pattern=CODE)
    category: str = Field(pattern=r"^(CONTROL|AUDIT|FINDING|REMEDIATION|EVIDENCE|POLICY|BEHAVIOR|VERIFICATION|REGULATORY)$")
    summary: str = Field(min_length=5, max_length=600)


@tool("update_compliance_memory", description="Persist a sourced memory record", permission="AGENT_USE", args=MemWriteArgs, mutates=True)
def update_compliance_memory(ctx: ToolContext, a: MemWriteArgs) -> dict:
    cv = ctx.snapshot().by_code(a.subject_code)
    rec = remember(ctx.db, company_id=ctx.company_id, category=a.category, subject_type="control" if cv else "other",
                   subject_id=cv.control.id if cv else None, subject_code=a.subject_code, summary=a.summary,
                   source_type="agent_run", source_id=ctx.run_id, source_label=f"Agent run #{ctx.run_id}")
    return {"id": rec.id, "_summary": "memory updated"}


class ReportArgs(BaseModel):
    audit_id: int | None = None


@tool("generate_audit_report", description="Generate an evidence-backed audit readiness report", permission="REPORTS_GENERATE",
      args=ReportArgs, mutates=True)
def generate_audit_report(ctx: ToolContext, a: ReportArgs) -> dict:
    from app.reports.builder import build_readiness_report

    rep = build_readiness_report(ctx.db, ctx.principal, audit_id=a.audit_id or ctx.audit_id, run_id=ctx.run_id)
    return {"report_id": rep.id, "code": rep.code, "title": rep.title, "_summary": f"{rep.code} generated"}


def pending_approvals(ctx: ToolContext) -> list[ApprovalRequest]:
    return ctx.db.execute(select(ApprovalRequest).where(ApprovalRequest.company_id == ctx.company_id,
                                                        ApprovalRequest.status == "PENDING")).scalars().all()


def now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- P4/P5 tools
class SimControlArgs(BaseModel):
    control_code: str = Field(pattern=r"^C-\d{3}$")
    test_result: str | None = Field(default="FAIL", pattern=r"^(PASS|FAIL|PARTIAL)$")
    evidence_state: str | None = Field(default=None, pattern=r"^(VALID|EXPIRED|MISSING|CONFLICTING)$")


@tool("simulate_control_failure", description="What-if: simulate a control failing (nothing is saved)", permission="AUDIT_RUN", args=SimControlArgs)
def simulate_control_failure(ctx: ToolContext, a: SimControlArgs) -> dict:
    from app.compliance.advanced import simulate_control

    try:
        out = simulate_control(ctx.company_id, a.control_code, a.test_result, a.evidence_state, None, ctx.risk_cfg())
    except ValueError:
        raise ToolError("NOT_FOUND", f"Control {a.control_code} not found.")
    return {**out, "_summary": f"{a.control_code}: {out['risk']['before']['category']} → {out['risk']['after']['category']}"}


class PolicySimArgs(BaseModel):
    policy_code: str = Field(default="POL-002", pattern=r"^POL-\d{3}$")
    proposed_interval_days: int = Field(ge=7, le=730)


@tool("simulate_policy_change", description="Policy Lab: simulate a policy review-interval change (nothing is saved)",
      permission="POLICIES_MANAGE", args=PolicySimArgs)
def simulate_policy_change(ctx: ToolContext, a: PolicySimArgs) -> dict:
    from app.compliance.advanced import simulate_policy_change as sim

    try:
        out = sim(ctx.company_id, a.policy_code, a.proposed_interval_days, ctx.risk_cfg())
    except ValueError:
        raise ToolError("NOT_FOUND", f"Policy {a.policy_code} not found.")
    return {**out, "_summary": out["summary"]}


@tool("detect_control_drift", description="Detect potential control drift", permission="CONTROLS_READ", args=NoArgs)
def detect_control_drift(ctx: ToolContext, a: NoArgs) -> dict:
    from app.compliance.advanced import control_drift

    items = control_drift(ctx.db, ctx.snapshot())
    return {"items": items, "count": len(items), "_summary": f"{len(items)} controls with potential drift"}


@tool("run_compliance_scan", description="Run a compliance scan: freshness, overdue tests, deadlines, alerts", permission="AUDIT_RUN",
      args=NoArgs, mutates=True, safe_to_retry=False)
def run_compliance_scan(ctx: ToolContext, a: NoArgs) -> dict:
    from app.services.scans import run_scan

    out = run_scan(ctx.db, ctx.company_id, trigger="agent", requested_by=ctx.principal.user_id)
    return {**out, "_summary": f"{out['alerts']} alerts, {len(out['new_findings'])} new findings"}


@tool("get_morning_brief", description="Proactive morning compliance brief", permission="AGENT_USE", args=NoArgs)
def get_morning_brief(ctx: ToolContext, a: NoArgs) -> dict:
    from app.services.scans import morning_brief

    out = morning_brief(ctx.db, ctx.principal)
    return {**out, "_summary": ", ".join(f"{i['count']} {i['label']}" for i in out["items"] if i["count"])}
