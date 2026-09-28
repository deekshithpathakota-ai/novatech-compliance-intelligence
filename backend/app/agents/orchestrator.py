"""Compliance & Audit Agent orchestrator.

UNDERSTAND -> PLAN -> RETRIEVE -> ASSESS -> DETECT -> INVESTIGATE -> REMEDIATE -> VERIFY -> REMEMBER

The agent selects and sequences tools; every tool executes through the Tool Gateway (authZ, risk, approval,
audit). Each step is persisted to `agent_steps` and streamed to the UI over SSE. Only concise action/status
summaries are shown — never private chain-of-thought.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import llm
from app.agents.schemas import AuditReadinessNarrative, GroundedAnswer, IntentClassification
from app.auth.deps import Principal
from app.compliance.snapshot import OPEN_FINDING_STATUSES, _aware, next_upcoming_audit
from app.config import get_settings
from app.database.session import SessionLocal
from app.memory.service import remember
from app.models import AgentRun, AgentStep, ApprovalRequest, Conversation, Finding, Message, RemediationPlan, RemediationTask
from app.security.dlp import redact_obj
from app.tools import impl  # noqa: F401  (registers tools)
from app.tools.gateway import ToolContext, ToolError, call_tool

log = logging.getLogger("novatech.agent")

CONTROL_RE = re.compile(r"\b[Cc]-\d{3}\b")
FINDING_RE = re.compile(r"\b(?:FND|AUD)-\d{4}-\d{3}\b", re.I)

INTENT_RULES: list[tuple[str, re.Pattern]] = [
    ("morning_brief", re.compile(r"(?i)morning brief|brief me|what needs my attention")),
    ("compliance_scan", re.compile(r"(?i)\brun (a |the )?(compliance )?scan|scan (now|the controls)")),
    ("control_drift", re.compile(r"(?i)\bdrift")),
    ("policy_lab", re.compile(r"(?i)(policy|review).{0,40}\b(\d{2,3})\s*days|policy lab")),
    ("simulate_control", re.compile(r"(?i)what (happens|would happen)\b.{0,30}\bfail|what if\b.{0,40}\bfail|simulate\b.{0,20}\b(c-\d{3}|control)")),
    ("what_changed", re.compile(r"(?i)what('s| has)? changed|since (the |our )?(previous|last) (audit|policy)|changed since")),
    ("recurring_findings", re.compile(r"(?i)recurring|repeat(ed|ing)? (finding|issue)")),
    ("memory_search", re.compile(r"(?i)seen (this|it|that) before|happened before|in the previous audit|present in the previous|have we (had|seen)")),
    ("investigate_control", re.compile(r"(?i)\binvestigat")),
    ("remediation_plan", re.compile(r"(?i)remediation plan|remediate|generate remediation|fix (the|this)|create (a )?plan")),
    ("explain_control", re.compile(r"(?i)\bwhy\b.*\b(risk|fail|overdue|high|critical)|explain .*risk|why did")),
    ("generate_report", re.compile(r"(?i)\breport\b")),
    ("audit_readiness", re.compile(r"(?i)prepare|readiness|ready for|upcoming audit|audit prep|simulate (an |the )?audit")),
    ("expiring_evidence", re.compile(r"(?i)expir")),
    ("untested_controls", re.compile(r"(?i)not been tested|untested|not tested|haven'?t been tested")),
    ("open_findings", re.compile(r"(?i)unresolved|open findings|high[- ]risk findings|outstanding findings")),
    ("controls_at_risk", re.compile(r"(?i)controls?.*(at risk|attention|weak|failing)|at[- ]risk controls")),
]

PHASES = ["UNDERSTAND", "PLAN", "RETRIEVE", "ASSESS", "DETECT", "INVESTIGATE", "REMEDIATE", "VERIFY", "REMEMBER"]


def classify(text: str, usage: llm.Usage | None = None) -> IntentClassification:
    cc = CONTROL_RE.search(text)
    fc = FINDING_RE.search(text)
    for intent, pat in INTENT_RULES:
        if pat.search(text):
            return IntentClassification(intent=intent, control_code=cc.group(0).upper() if cc else None,
                                        finding_code=fc.group(0).upper() if fc else None)
    parsed = llm.structured("fast", "Classify the user's compliance request into one intent. Extract codes if present.",
                            text, IntentClassification, usage)
    if parsed:
        return parsed
    if cc:
        return IntentClassification(intent="explain_control", control_code=cc.group(0).upper())
    return IntentClassification(intent="document_question")


# ====================================================================== run context
class RunCtx:
    def __init__(self, db: Session, principal: Principal, run: AgentRun):
        self.db, self.principal, self.run = db, principal, run
        self.seq = 0
        self.delay = get_settings().demo_step_delay_ms / 1000
        self.usage = llm.Usage()
        self.tctx = ToolContext(db=db, principal=principal, run_id=run.id)
        self.tctx.cache["emit"] = self.emit
        self.cards: list[dict] = []
        self.plan_done: set[int] = set()

    def emit(self, event_type: str, title: str, status: str = "info", *, phase: str = "", tool: str | None = None,
             detail: dict | None = None, evidence_count: int = 0) -> AgentStep:
        self.seq += 1
        st = AgentStep(company_id=self.principal.company_id, run_id=self.run.id, seq=self.seq, event_type=event_type,
                       phase=phase, title=title, status=status, tool_name=tool, detail=redact_obj(detail or {})[0],
                       evidence_count=evidence_count)
        self.db.add(st)
        self.db.commit()
        return st

    @contextmanager
    def step(self, title: str, phase: str, tool: str | None = None, event_type: str = "step", plan_id: int | None = None):
        etype = event_type + ".started" if "." not in event_type else event_type
        st = self.emit(etype, title, "running", phase=phase, tool=tool)
        t0 = time.perf_counter()
        holder: dict = {"status": "done", "title": title, "detail": {}, "evidence_count": 0}
        try:
            yield holder
        except ToolError as e:
            holder["status"] = "failed"
            holder["detail"] = {"error": e.code, "message": e.message}
            st.status, st.title, st.detail = "failed", holder["title"], holder["detail"]
            st.duration_ms = int((time.perf_counter() - t0) * 1000)
            self.db.commit()
            raise
        if self.delay:
            time.sleep(self.delay)
        st.status, st.title = holder["status"], holder["title"]
        det = dict(holder["detail"] or {})
        if plan_id is not None:
            det["_plan"] = plan_id
        st.detail, st.evidence_count = redact_obj(det)[0], holder["evidence_count"]
        st.duration_ms = int((time.perf_counter() - t0) * 1000)
        if etype.endswith(".started"):
            st.event_type = etype.replace(".started", ".completed")
        if plan_id is not None:
            self.plan_done.add(plan_id)
            self.run.result = {**(self.run.result or {}), "plan_done": sorted(self.plan_done)}
        self.db.commit()

    def tool(self, name: str, args: dict | None = None) -> dict:
        out = call_tool(self.tctx, name, args or {})
        self.db.commit()
        return out

    def set_plan(self, objective: str, steps: list[tuple[str, str, str | None]]):
        self.run.plan = [{"id": i + 1, "title": t, "phase": p, "tool": tool} for i, (t, p, tool) in enumerate(steps)]
        self.run.objective = objective
        self.db.commit()
        self.emit("plan.created", f"Plan created · {len(steps)} steps", "done", phase="PLAN",
                  detail={"objective": objective, "steps": self.run.plan})

    def card(self, kind: str, **data):
        self.cards.append({"type": kind, **data})


# ====================================================================== public API
def start_run(db: Session, principal: Principal, text: str, conversation_id: int | None = None,
              forced_intent: dict | None = None) -> AgentRun:
    if conversation_id:
        conv = db.execute(select(Conversation).where(Conversation.id == conversation_id,
                                                     Conversation.company_id == principal.company_id,
                                                     Conversation.user_id == principal.user_id)).scalar_one_or_none()
        if conv is None:
            raise ToolError("NOT_FOUND", "Conversation not found.")
    else:
        conv = Conversation(company_id=principal.company_id, user_id=principal.user_id, title=text[:80])
        db.add(conv)
        db.flush()
    db.add(Message(company_id=principal.company_id, conversation_id=conv.id, role="user", content=text[:4000]))
    run = AgentRun(company_id=principal.company_id, user_id=principal.user_id, conversation_id=conv.id,
                   objective=text[:1000], intent=(forced_intent or {}).get("intent", "pending"), status="RUNNING",
                   engine="openai-agents" if llm.router.enabled else "deterministic",
                   model=llm.router.model_for("reasoning"), result={"forced": forced_intent or {}})
    db.add(run)
    db.commit()
    threading.Thread(target=_execute, args=(run.id, principal, text), daemon=True).start()
    return run


def _execute(run_id: int, principal: Principal, text: str) -> None:
    db = SessionLocal()
    run = db.get(AgentRun, run_id)
    rc = RunCtx(db, principal, run)
    t0 = time.perf_counter()
    try:
        rc.emit("agent.started", "Compliance Agent started", "done", phase="UNDERSTAND",
                detail={"engine": run.engine, "model": run.model or "deterministic"})
        forced = (run.result or {}).get("forced") or {}
        intent = IntentClassification(**forced) if forced.get("intent") else classify(text, rc.usage)
        run.intent = intent.intent
        db.commit()
        handler = WORKFLOWS.get(intent.intent, wf_document_question)
        content = handler(rc, intent, text)
        final_status = run.status if run.status == "AWAITING_APPROVAL" else "COMPLETED"
        _finish(rc, content, final_status, t0)
    except ToolError as e:
        _finish(rc, f"The agent could not complete this step. {e.message}", "FAILED", t0, error=e.code)
    except Exception:  # never leak stack traces to users
        log.error("agent run %s failed: %s", run_id, traceback.format_exc())
        db.rollback()
        run = db.get(AgentRun, run_id)
        rc.run = run
        _finish(rc, "The agent could not complete this step. No action has been recorded as complete.", "FAILED", t0,
                error="INTERNAL_ERROR")
    finally:
        db.close()


def _finish(rc: RunCtx, content: str, status: str, t0: float, error: str | None = None) -> None:
    db, run = rc.db, rc.run
    cards, dlp = redact_obj(rc.cards)
    content, dlp2 = redact_obj(content)
    if dlp or dlp2:
        cards.append({"type": "notice", "tone": "warning", "text": "Sensitive information redacted by policy."})
    db.add(Message(company_id=run.company_id, conversation_id=run.conversation_id, role="assistant", content=content,
                   cards=cards, run_id=run.id))
    run.status = status
    run.error = error
    run.completed_at = datetime.now(timezone.utc)
    run.duration_ms = int((time.perf_counter() - t0) * 1000)
    run.llm_calls, run.tokens_in, run.tokens_out = rc.usage.calls, rc.usage.tokens_in, rc.usage.tokens_out
    run.result = {**(run.result or {}), "content": content, "cards": cards}
    db.commit()
    rc.emit("agent.completed" if status != "FAILED" else "agent.failed",
            {"COMPLETED": "Run complete", "AWAITING_APPROVAL": "Waiting for human approval",
             "FAILED": "The agent could not complete this step"}[status],
            {"COMPLETED": "done", "AWAITING_APPROVAL": "warning", "FAILED": "failed"}[status], phase="REMEMBER")


# ====================================================================== helpers
def _resolve_control(rc: RunCtx, intent: IntentClassification, text: str) -> str | None:
    if intent.control_code:
        return intent.control_code
    snap = rc.tctx.snapshot()
    low = text.lower()
    best = None
    for cv in snap.controls.values():
        name = cv.control.name.lower()
        if name in low:
            return cv.control.code
        words = [w for w in re.findall(r"[a-z]+", name) if len(w) > 3]
        hits = sum(1 for w in words if w in low)
        if words and hits >= max(2, len(words) - 1) and (best is None or hits > best[0]):
            best = (hits, cv.control.code)
    if intent.finding_code:
        f = next((f for f in snap.findings if f.code == intent.finding_code), None)
        if f:
            return snap.controls[f.control_id].control.code
    return best[1] if best else None


def _nba(label: str, kind: str, **kw) -> dict:
    return {"label": label, "kind": kind, **kw}


# ====================================================================== workflows
def wf_audit_readiness(rc: RunCtx, intent: IntentClassification, text: str) -> str:
    db, p = rc.db, rc.principal
    audit = next_upcoming_audit(db, p.company_id)
    rc.tctx.audit_id = audit.id if audit else None
    objective = f"Prepare NovaTech for {audit.name}" if audit else "Assess current audit readiness"
    rc.set_plan(objective, [
        ("Identify framework and audit scope", "UNDERSTAND", None),
        ("Identify applicable requirements", "RETRIEVE", "search_requirements"),
        ("Retrieve mapped controls", "RETRIEVE", "get_controls"),
        ("Check control health and testing", "ASSESS", "get_controls"),
        ("Validate evidence freshness", "ASSESS", "search_evidence"),
        ("Review previous audits and findings", "INVESTIGATE", "get_audit_history"),
        ("Identify recurring findings", "DETECT", "find_recurring_findings"),
        ("Detect compliance gaps", "DETECT", "detect_compliance_gaps"),
        ("Calculate risk (deterministic model)", "ASSESS", "assess_risk"),
        ("Check remediation status", "REMEDIATE", "get_remediation_status"),
        ("Recommend next best actions", "REMEDIATE", None),
        ("Record readiness assessment in memory", "REMEMBER", "update_compliance_memory"),
    ])
    with rc.step("Authorization check · permission-filtered compliance context", "UNDERSTAND", event_type="authorization.checked") as h:
        h["title"] = f"Authorized as {p.role_name} · context filtered to your tenant and permissions"
    with rc.step("Identifying audit framework", "UNDERSTAND", plan_id=1) as h:
        if audit:
            h["title"] = f"Identified audit: {audit.name} ({audit.framework.name}) on {audit.start_date:%d %b %Y}"
            h["detail"] = {"audit": audit.code, "framework": audit.framework.code, "date": audit.start_date.isoformat()}
        else:
            h["title"] = "No upcoming audit found — assessing whole programme"
    with rc.step("Retrieving requirements", "RETRIEVE", "search_requirements", "retrieval.started", plan_id=2) as h:
        r = rc.tool("search_requirements")
        h["title"] = f"Retrieved {r['count']} requirements"
        h["detail"] = {"frameworks": r["frameworks"], "changed": r["changed"], "unmapped": r["unmapped"]}
    with rc.step("Retrieving mapped controls", "RETRIEVE", "get_controls", "retrieval.started", plan_id=3) as h:
        c = rc.tool("get_controls")
        h["title"] = f"Mapped {c['count']} controls"
        h["detail"] = {"status_counts": c["status_counts"]}
    with rc.step("Checking control health", "ASSESS", "get_controls", plan_id=4) as h:
        bad = {k: v for k, v in c["status_counts"].items() if k not in ("PASS", "AT_RISK")}
        h["title"] = (f"Checked {c['count']} controls · {sum(bad.values())} failing/overdue · "
                      f"{c['status_counts'].get('AT_RISK', 0)} at risk")
        h["status"] = "warning" if bad else "done"
        h["detail"] = {"attention": bad}
    with rc.step("Validating evidence freshness", "ASSESS", "search_evidence", plan_id=5) as h:
        ev = rc.tool("search_evidence")
        h["title"] = f"Checked {ev['count']} evidence items · {ev['status_counts'].get('EXPIRING', 0)} expiring, {ev['status_counts'].get('EXPIRED', 0)} expired"
        h["evidence_count"] = ev["count"]
        h["status"] = "warning" if ev["status_counts"].get("EXPIRED") else "done"
        h["detail"] = {"status_counts": ev["status_counts"], "missing_for_controls": ev["missing_for_controls"]}
    with rc.step("Reviewing audit memory", "INVESTIGATE", "get_audit_history", "memory.recalled", plan_id=6) as h:
        ah = rc.tool("get_audit_history")
        h["title"] = f"Reviewed {len(ah['audits'])} previous audits · {ah['historical_findings']} historical findings"
    with rc.step("Searching for recurring findings", "DETECT", "find_recurring_findings", plan_id=7) as h:
        rec = rc.tool("find_recurring_findings")
        h["title"] = f"Identified {rec['count']} recurring findings"
        h["status"] = "warning" if rec["count"] else "done"
        h["detail"] = {"items": [f"{x['control_code']} · {x['occurrences']}x" for x in rec["items"]]}
    with rc.step("Running gap detection (16 checks)", "DETECT", "detect_compliance_gaps", "finding.detected", plan_id=8) as h:
        g = rc.tool("detect_compliance_gaps")
        h["title"] = f"Found {g['gap_count']} potential gaps"
        h["status"] = "warning" if g["gap_count"] else "done"
        h["detail"] = {"subjects": [f"{s['subject_code']} · {s['severity']}" for s in g["subjects"]]}
    with rc.step("Calculating risk", "ASSESS", "assess_risk", "risk.assessed", plan_id=9) as h:
        risk = rc.tool("assess_risk")
        rcnt = risk["risk_counts"]
        h["title"] = f"Risk calculated · {rcnt['CRITICAL']} critical, {rcnt['HIGH']} high"
        h["detail"] = {"model": "NovaTech Prototype Risk Model", **rcnt}
    with rc.step("Checking remediation status", "REMEDIATE", "get_remediation_status", plan_id=10) as h:
        rs = rc.tool("get_remediation_status")
        h["title"] = f"{rs['active']} active remediation plans · {rs['overdue_tasks']} overdue tasks"
        h["status"] = "warning" if rs["overdue_tasks"] else "done"
    readiness = risk["readiness"]
    focus = next((x for x in rec["items"] if any(t["code"] == x["control_code"] for t in risk["top_risks"])), None)
    focus_code = focus["control_code"] if focus else (risk["top_risks"][0]["code"] if risk["top_risks"] else None)
    focus_risk = next((t for t in risk["top_risks"] if t["code"] == focus_code), None)
    with rc.step("Preparing next best actions", "REMEDIATE", plan_id=11) as h:
        h["title"] = f"Top priority: {focus_risk['name']} ({focus_code})" if focus_risk else "No priority actions"
    with rc.step("Recording assessment in compliance memory", "REMEMBER", "update_compliance_memory", "memory.updated", plan_id=12) as h:
        rc.tool("update_compliance_memory", {"subject_code": audit.code if audit else "AUD-NONE", "category": "AUDIT",
                                             "summary": f"Readiness assessment: {readiness['overall']}% · {g['gap_count']} gaps · "
                                                        f"{rec['count']} recurring · {rcnt['CRITICAL']} critical"})
        h["title"] = "Audit memory updated with readiness assessment"

    open_f = rc.tool("get_findings", {"open_only": True})
    focus_finding = next((f for f in open_f["findings"] if f["control_code"] == focus_code), None)
    rc.card("summary_metrics", title=objective, items=[
        {"label": "Readiness", "value": f"{readiness['overall']}%", "tone": "info", "hint": readiness["label"]},
        {"label": "Potential gaps", "value": g["gap_count"], "tone": "warning"},
        {"label": "Recurring findings", "value": rec["count"], "tone": "warning"},
        {"label": "High-risk controls", "value": rcnt["HIGH"], "tone": "danger"},
        {"label": "Critical risks", "value": rcnt["CRITICAL"], "tone": "danger"},
        {"label": "Evidence expiring", "value": ev["status_counts"].get("EXPIRING", 0), "tone": "warning"},
    ])
    rc.card("gap_list", title="Potential compliance gaps", subjects=g["subjects"], gaps=g["gaps"][:40])
    if focus_risk:
        cv = rc.tctx.snapshot().by_code(focus_code)
        rc.card("control_risk", control={"id": cv.control.id, "code": focus_code, "name": cv.control.name},
                risk=focus_risk["category"], score=focus_risk["score"], status=focus_risk["status"],
                reason=f"Last tested {cv.days_since_test} days ago; required every {cv.control.frequency_days} days."
                if cv.days_since_test is not None else "Never tested.",
                evidence=[{"code": e.code, "name": e.name, "id": e.id} for e in cv.evidence],
                evidence_state=cv.evidence_state, previous_findings=[f.code for f in cv.findings if f.status == "CLOSED"],
                finding=focus_finding, recurring=bool(focus),
                recommended="Perform the current access review and remove stale access." if "access" in cv.control.name.lower()
                else "Re-test the control with fresh evidence.")
    if rec["items"]:
        rc.card("recurring", items=rec["items"])
    rc.card("top_risks", items=risk["top_risks"])
    actions = []
    if focus_risk:
        actions += [_nba(f"Open {focus_code}", "navigate", to=f"/controls/{rc.tctx.snapshot().by_code(focus_code).control.id}"),
                    _nba(f"Investigate {focus_code}", "agent", prompt=f"Investigate {focus_code}",
                         intent={"intent": "investigate_control", "control_code": focus_code})]
        if focus_finding:
            actions.append(_nba("Generate remediation", "agent", prompt=f"Create a remediation plan for {focus_finding['code']}",
                                intent={"intent": "remediation_plan", "finding_code": focus_finding["code"]}))
    if ev["status_counts"].get("EXPIRING"):
        actions.append(_nba(f"Review {ev['status_counts']['EXPIRING']} expiring evidence", "navigate", to="/evidence?status=EXPIRING"))
    actions.append(_nba("Generate Audit Readiness Report", "agent", prompt="Generate an audit readiness report",
                        intent={"intent": "generate_report"}))
    rc.card("next_actions", actions=actions)

    facts = {"objective": objective, "readiness": readiness["overall"], "gaps": g["gap_count"], "recurring": rec["count"],
             "critical": rcnt["CRITICAL"], "high": rcnt["HIGH"], "expiring": ev["status_counts"].get("EXPIRING", 0),
             "focus": focus_risk}
    nar = llm.structured("reasoning", "Write an executive readiness narrative from these computed facts.", facts,
                         AuditReadinessNarrative, rc.usage)
    if nar:
        return f"{nar.headline}\n\n{nar.summary}\n\nTop priority: {nar.top_priority}"
    return (f"{objective}: NovaTech readiness indicator is {readiness['overall']}%. I found {g['gap_count']} potential gaps, "
            f"{rec['count']} recurring findings, {rcnt['HIGH']} high-risk and {rcnt['CRITICAL']} critical controls, and "
            f"{ev['status_counts'].get('EXPIRING', 0)} evidence items expiring within 30 days."
            + (f" Top priority is {focus_risk['name']} ({focus_code}) — {focus_risk['category'].lower()} risk and a recurring finding."
               if focus_risk else "") + " Further human review is recommended.")


def wf_explain_control(rc: RunCtx, intent: IntentClassification, text: str) -> str:
    code = _resolve_control(rc, intent, text)
    if not code:
        return wf_controls_at_risk(rc, intent, text)
    rc.set_plan(f"Explain the risk of {code}", [
        ("Run deterministic risk model", "ASSESS", "assess_risk"),
        ("Check testing status", "RETRIEVE", "get_control_test_results"),
        ("Check evidence freshness", "RETRIEVE", "search_evidence"),
        ("Review historical findings", "INVESTIGATE", "get_findings"),
        ("Recall audit memory", "INVESTIGATE", "search_compliance_memory"),
        ("Retrieve policy requirements", "RETRIEVE", "search_documents"),
    ])
    with rc.step(f"Assessing risk for {code}", "ASSESS", "assess_risk", "risk.assessed", plan_id=1) as h:
        r = rc.tool("assess_risk", {"control_code": code})
        h["title"] = f"{code} risk: {r['category']} ({r['score']})"
    with rc.step("Checking testing status", "RETRIEVE", "get_control_test_results", plan_id=2) as h:
        t = rc.tool("get_control_test_results", {"control_code": code})
        h["title"] = f"Last tested {t['days_since_test']} days ago (required every {t['frequency_days']} days)" \
            if t["days_since_test"] is not None else "Control has never been tested"
    with rc.step("Checking evidence", "RETRIEVE", "search_evidence", plan_id=3) as h:
        ev = rc.tool("search_evidence", {"control_code": code})
        h["title"] = f"{ev['count']} evidence item(s): " + ", ".join(f"{v} {k.lower()}" for k, v in ev["status_counts"].items())
        h["evidence_count"] = ev["count"]
    with rc.step("Reviewing historical findings", "INVESTIGATE", "get_findings", plan_id=4) as h:
        fs = rc.tool("get_findings", {"control_code": code})
        h["title"] = f"{fs['count']} historical finding(s) on {code}"
    with rc.step("Recalling compliance memory", "INVESTIGATE", "search_compliance_memory", "memory.recalled", plan_id=5) as h:
        mem = rc.tool("search_compliance_memory", {"subject_code": code})
        h["title"] = f"{mem['count']} memory records recalled"
    cv = rc.tctx.snapshot().by_code(code)
    with rc.step("Retrieving policy passages", "RETRIEVE", "search_documents", "retrieval.completed", plan_id=6) as h:
        docs = rc.tool("search_documents", {"query": f"{cv.control.name} frequency requirement {code}"})
        h["title"] = f"{len(docs['results'])} permitted passages retrieved ({docs['latency_ms']}ms)"
        h["evidence_count"] = len(docs["results"])
    rc.card("risk_explanation", control={"id": cv.control.id, "code": code, "name": cv.control.name}, risk=r,
            testing={"days_since_test": t["days_since_test"], "frequency_days": t["frequency_days"], "latest": t["latest"]},
            evidence=ev["evidence"], findings=fs["findings"], memory=mem["records"][:6], criticality=cv.control.criticality)
    rc.card("citations", results=docs["results"][:4])
    open_f = [f for f in fs["findings"] if f["status"] in OPEN_FINDING_STATUSES]
    acts = [_nba(f"Investigate {code}", "agent", prompt=f"Investigate {code}", intent={"intent": "investigate_control", "control_code": code}),
            _nba(f"Open {code}", "navigate", to=f"/controls/{cv.control.id}")]
    if open_f:
        acts.append(_nba("Generate remediation", "agent", prompt=f"Create a remediation plan for {open_f[0]['code']}",
                         intent={"intent": "remediation_plan", "finding_code": open_f[0]["code"]}))
    rc.card("next_actions", actions=acts)
    base = (f"{code} {cv.control.name} is {r['category']} risk (score {r['score']}, NovaTech Prototype Risk Model). "
            + " ".join(r["explanation"]) + ".")
    prior = [f for f in fs["findings"] if f["status"] == "CLOSED"]
    if prior:
        base += f" The same control had {len(prior)} previous finding(s), most recently {prior[0]['code']}."
    return base + " The score is calculated by backend rules; this explanation does not change it."


def wf_investigate(rc: RunCtx, intent: IntentClassification, text: str) -> str:
    code = _resolve_control(rc, intent, text)
    if not code:
        return "Please name the control to investigate (for example C-017)."
    rc.set_plan(f"Investigate {code}", [
        ("Retrieve control history", "RETRIEVE", "get_control_history"),
        ("Retrieve previous audits", "INVESTIGATE", "get_audit_history"),
        ("Recall remediation memory", "INVESTIGATE", "search_compliance_memory"),
        ("Detect recurrence and remediation effectiveness", "DETECT", "find_recurring_findings"),
        ("Form root-cause hypotheses", "INVESTIGATE", None),
    ])
    with rc.step("Retrieving control history", "RETRIEVE", "get_control_history", plan_id=1) as h:
        hist = rc.tool("get_control_history", {"control_code": code})
        h["title"] = f"{len(hist['tests'])} tests, {len(hist['findings'])} findings, {len(hist['owner_history'])} owner assignment(s)"
    with rc.step("Retrieving previous audits", "INVESTIGATE", "get_audit_history", "memory.recalled", plan_id=2) as h:
        ah = rc.tool("get_audit_history", {"control_code": code})
        hit = [a for a in ah["audits"] if a["findings"]]
        h["title"] = f"{code} appeared in {len(hit)} previous audit(s)" if hit else "No previous audit findings"
    with rc.step("Recalling remediation memory", "INVESTIGATE", "search_compliance_memory", "memory.recalled", plan_id=3) as h:
        mem = rc.tool("search_compliance_memory", {"subject_code": code})
        h["title"] = f"{mem['count']} memory records (remediation, verification, behaviour)"
    with rc.step("Analysing recurrence", "DETECT", "find_recurring_findings", plan_id=4) as h:
        rec = rc.tool("find_recurring_findings")
        item = next((x for x in rec["items"] if x["control_code"] == code), None)
        if item:
            h["title"] = f"Recurring control weakness · {item['occurrences']} occurrences since {item['first_detected']}"
            h["status"] = "warning"
        else:
            h["title"] = "No recurrence detected"
    with rc.step("Forming root-cause hypotheses", "INVESTIGATE", plan_id=5) as h:
        hyps = item["hypotheses"] if item else []
        h["title"] = f"{len(hyps)} potential root causes (hypotheses for human validation)"
    cv = rc.tctx.snapshot().by_code(code)
    rc.card("investigation", control={"id": cv.control.id, "code": code, "name": cv.control.name, "status": cv.status},
            recurring=item, history=hist, memory=mem["records"][:8],
            verdict="Recurring control weakness" if item else "No recurring pattern detected")
    open_f = next((f for f in cv.findings if f.status in OPEN_FINDING_STATUSES), None)
    acts = []
    if open_f:
        acts.append(_nba("Generate Remediation", "agent", prompt=f"Create a remediation plan for {open_f.code}",
                         intent={"intent": "remediation_plan", "finding_code": open_f.code}))
    acts.append(_nba(f"Open {code}", "navigate", to=f"/controls/{cv.control.id}"))
    rc.card("next_actions", actions=acts)
    if item:
        pv = sum(1 for o in item["timeline"] for v in o["verification"] if v["result"] == "PASSED")
        return (f"{code} failed previously: first detected {item['first_detected']}, {item['occurrences']} occurrences. "
                f"Previous remediation was implemented and verification passed {pv} time(s), but the control is now "
                f"{cv.status.lower()} again. I classify this as a recurring control weakness — "
                f"{item['interpretation']} (AI-generated analysis; please validate the hypotheses.)")
    return f"{code} has no recurring pattern in audit memory. Current status: {cv.status}."


def wf_remediation(rc: RunCtx, intent: IntentClassification, text: str) -> str:
    snap = rc.tctx.snapshot()
    finding = None
    if intent.finding_code:
        finding = next((f for f in snap.findings if f.code == intent.finding_code), None)
    if finding is None:
        code = _resolve_control(rc, intent, text)
        if code:
            cv = snap.by_code(code)
            finding = next((f for f in cv.findings if f.status in OPEN_FINDING_STATUSES), None)
    if finding is None and re.search(r"(?i)top|three|3", text):
        return wf_top_remediation(rc, intent, text)
    if finding is None:
        return "I couldn't find an open finding to remediate. Name a finding (e.g. FND-2026-041) or a control."
    rc.set_plan(f"Remediate {finding.code}: {finding.title}", [
        ("Generate multi-step remediation plan", "REMEDIATE", "create_remediation_task"),
        ("Execute permitted low-risk steps", "REMEDIATE", "update_remediation_task"),
        ("Request human approval for high-risk action", "REMEDIATE", "create_approval_request"),
    ])
    with rc.step("Generating remediation plan", "REMEDIATE", "create_remediation_task", plan_id=1) as h:
        out = rc.tool("create_remediation_task", {"finding_code": finding.code})
        h["title"] = f"Created {out['plan']['code']} with {len(out['tasks'])} tasks"
        h["detail"] = {"tasks": [t["title"] for t in out["tasks"]]}
    plan_code = out["plan"]["code"]

    def on_task(t, res):
        rc.emit("action.executed", f"✓ {t.title}", "done", phase="REMEDIATE", tool=res.get("connector"),
                detail={"result": {k: v for k, v in (res.get("result") or {}).items() if k != "inactive_sample"},
                        "simulated": True})
    rc.tctx.cache["on_task"] = on_task
    with rc.step("Executing permitted low-risk steps", "REMEDIATE", "update_remediation_task", plan_id=2) as h:
        adv = rc.tool("update_remediation_task", {"plan_code": plan_code})
        h["title"] = f"Executed {len(adv['executed'])} low-risk steps automatically"
    ap = adv["approval"]
    plan = rc.db.execute(select(RemediationPlan).where(RemediationPlan.company_id == rc.principal.company_id,
                                                       RemediationPlan.code == plan_code)).scalar_one()
    tasks = rc.db.execute(select(RemediationTask).where(RemediationTask.plan_id == plan.id).order_by(RemediationTask.seq)).scalars().all()
    rc.card("remediation_plan", plan={"id": plan.id, "code": plan.code, "title": plan.title, "status": plan.status,
                                      "finding": finding.code, "rationale": plan.rationale},
            tasks=[{"id": t.id, "seq": t.seq, "title": t.title, "owner": t.owner.name if t.owner else None,
                    "priority": t.priority, "due_date": t.due_date.isoformat() if t.due_date else None,
                    "status": t.status, "depends_on": t.depends_on_seq, "evidence_required": t.evidence_required,
                    "risk": t.risk_level} for t in tasks])
    if ap:
        with rc.step(f"Approval required · {ap['risk_level']}-risk action", "REMEDIATE", "create_approval_request",
                     "approval.required", plan_id=3) as h:
            h["title"] = f"Approval {ap['code']} requested: {ap['title']}"
            h["status"] = "warning"
        rc.card("approval", approval=ap, plan_code=plan_code)
        rc.run.status = "AWAITING_APPROVAL"
        rc.db.commit()
        return (f"I created {plan_code} for {finding.code} and completed the low-risk steps (access report, reviews, "
                f"manager notification — Demo Connectors). The next step — '{ap['title']}' — is {ap['risk_level']} risk, "
                f"so it needs approval from a user with {ap['required_permission']}. Nothing has been changed yet.")
    return f"I created {plan_code} for {finding.code}. Remaining tasks are assigned to the control owner."


def wf_top_remediation(rc: RunCtx, intent: IntentClassification, text: str) -> str:
    rc.set_plan("Create remediation plans for the top three risks", [
        ("Rank controls by deterministic risk", "ASSESS", "assess_risk"),
        ("Create remediation plans", "REMEDIATE", "create_remediation_task")])
    with rc.step("Ranking risks", "ASSESS", "assess_risk", "risk.assessed", plan_id=1) as h:
        risk = rc.tool("assess_risk")
        h["title"] = "Top risks: " + ", ".join(t["code"] for t in risk["top_risks"][:3])
    made = []
    snap = rc.tctx.snapshot()
    for t in risk["top_risks"][:3]:
        cv = snap.by_code(t["code"])
        f = next((x for x in cv.findings if x.status in OPEN_FINDING_STATUSES), None)
        if not f:
            continue
        with rc.step(f"Planning remediation for {t['code']}", "REMEDIATE", "create_remediation_task", plan_id=2) as h:
            out = rc.tool("create_remediation_task", {"finding_code": f.code})
            h["title"] = f"{out['plan']['code']} · {len(out['tasks'])} tasks for {t['code']}"
            made.append({"control": t["code"], "finding": f.code, **out["plan"], "risk": t["category"]})
    rc.card("table", title="Remediation plans created", columns=["control", "finding", "code", "title", "risk"], rows=made)
    rc.card("next_actions", actions=[_nba("Open Remediation", "navigate", to="/remediation")])
    return f"Created {len(made)} remediation plans for the highest-risk controls. High-risk steps will request approval when advanced."


def wf_recurring(rc: RunCtx, intent: IntentClassification, text: str) -> str:
    rc.set_plan("Show recurring compliance findings", [("Search audit memory for repeated findings", "DETECT", "find_recurring_findings")])
    with rc.step("Searching audit memory for repeated findings", "DETECT", "find_recurring_findings", plan_id=1) as h:
        rec = rc.tool("find_recurring_findings")
        h["title"] = f"{rec['count']} recurring findings"
    rc.card("recurring", items=rec["items"])
    if rec["items"]:
        x = rec["items"][0]
        rc.card("next_actions", actions=[_nba(f"Investigate {x['control_code']}", "agent", prompt=f"Investigate {x['control_code']}",
                                              intent={"intent": "investigate_control", "control_code": x["control_code"]})])
    return f"{rec['count']} recurring findings are active. " + " ".join(
        f"{x['control_code']} {x['control_name']}: {x['occurrences']} occurrences since {x['first_detected']}, "
        f"remediation effectiveness {x['effectiveness']['level']}." for x in rec["items"])


def wf_what_changed(rc: RunCtx, intent: IntentClassification, text: str) -> str:
    rc.set_plan("Compare current state with the previous audit", [("Compare requirements, policies, controls, evidence, findings", "ASSESS", "compare_since_last_audit")])
    with rc.step("Comparing against previous audit baseline", "ASSESS", "compare_since_last_audit", plan_id=1) as h:
        w = rc.tool("compare_since_last_audit")
        h["title"] = f"Baseline {w['baseline']['code'] if w['baseline'] else '—'} · " + w["_summary"]
    rc.card("changes", **{k: v for k, v in w.items() if not k.startswith("_")})
    return f"Compared with {w['baseline']['name'] if w['baseline'] else 'no baseline'}: " + w["_summary"] + "."


def wf_memory_search(rc: RunCtx, intent: IntentClassification, text: str) -> str:
    code = _resolve_control(rc, intent, text)
    rc.set_plan("Search audit memory", [("Search persistent compliance memory", "INVESTIGATE", "search_compliance_memory"),
                                        ("Check previous audits", "INVESTIGATE", "get_audit_history")])
    with rc.step("Searching compliance memory", "INVESTIGATE", "search_compliance_memory", "memory.recalled", plan_id=1) as h:
        mem = rc.tool("search_compliance_memory", {"subject_code": code} if code else {"query": text})
        h["title"] = f"{mem['count']} matching memory records"
    with rc.step("Checking previous audits", "INVESTIGATE", "get_audit_history", plan_id=2) as h:
        ah = rc.tool("get_audit_history", {"control_code": code} if code else {})
        h["title"] = ah["_summary"]
    rc.card("memory", records=mem["records"], audits=[a for a in ah["audits"] if a["findings"]][:6])
    if not mem["records"]:
        return "No previous occurrence found in audit memory."
    first = mem["records"][-1]
    return f"Yes — audit memory holds {mem['count']} related records. Earliest: \"{first['summary']}\" ({first['source_label']})."


def _table_workflow(rc: RunCtx, title: str, tool: str, args: dict, key: str, columns: list[str], summary) -> str:
    rc.set_plan(title, [(title, "RETRIEVE", tool)])
    with rc.step(title, "RETRIEVE", tool, "retrieval.completed", plan_id=1) as h:
        out = rc.tool(tool, args)
        h["title"] = out["_summary"]
    rows = out[key]
    rc.card("table", title=title, columns=columns, rows=rows[:50], link_kind=key)
    return summary(rows)


def wf_expiring(rc, intent, text):
    return _table_workflow(rc, "Evidence expiring within 30 days", "search_evidence", {"status": "EXPIRING"}, "evidence",
                           ["code", "name", "control_code", "owner", "valid_until", "status"],
                           lambda r: f"{len(r)} evidence items expire within 30 days.")


def wf_controls_at_risk(rc, intent, text):
    out = _table_workflow(rc, "Controls requiring attention", "get_controls", {}, "controls",
                          ["code", "name", "owner", "status", "risk_category", "risk_score"], lambda r: "")
    card = rc.cards[-1]
    card["rows"] = sorted([r for r in card["rows"] if r["status"] != "PASS"], key=lambda r: -(r["risk_score"] or 0))
    return out or f"{len(card['rows'])} controls currently need attention, ordered by deterministic risk score."


def wf_untested(rc, intent, text):
    _table_workflow(rc, "Controls not tested recently", "get_controls", {}, "controls",
                          ["code", "name", "owner", "last_tested", "days_since_test", "frequency_days", "status"], lambda r: "")
    card = rc.cards[-1]
    card["rows"] = [r for r in card["rows"] if r["status"] in ("OVERDUE", "NOT_TESTED")]
    return f"{len(card['rows'])} controls are overdue for testing or have never been tested."


def wf_open_findings(rc, intent, text):
    args = {"open_only": True}
    _table_workflow(rc, "Unresolved findings", "get_findings", args, "findings",
                          ["code", "title", "control_code", "severity", "status", "owner", "due_date"], lambda r: "")
    card = rc.cards[-1]
    if re.search(r"(?i)high", text):
        card["rows"] = [r for r in card["rows"] if r["severity"] in ("HIGH", "CRITICAL")]
    return f"{len(card['rows'])} unresolved findings" + (" rated HIGH or CRITICAL." if re.search(r"(?i)high", text) else ".")


def wf_report(rc: RunCtx, intent, text) -> str:
    audit = next_upcoming_audit(rc.db, rc.principal.company_id)
    rc.set_plan("Generate Audit Readiness Report", [("Compile evidence-backed report", "REMEMBER", "generate_audit_report")])
    with rc.step("Compiling evidence-backed report", "REMEMBER", "generate_audit_report", plan_id=1) as h:
        r = rc.tool("generate_audit_report", {"audit_id": audit.id if audit else None})
        h["title"] = f"{r['code']} generated"
    rc.card("report", report_id=r["report_id"], code=r["code"], title=r["title"])
    return f"{r['title']} is ready ({r['code']}). It includes scope, control and evidence status, open and recurring findings, risk summary, remediation progress, evidence references and the audit trail."


def wf_document_question(rc: RunCtx, intent, text) -> str:
    rc.set_plan("Answer from permitted documents", [("Hybrid retrieval (authorization-filtered)", "RETRIEVE", "search_documents"),
                                                    ("Compose grounded answer with citations", "ASSESS", None)])
    with rc.step("Searching permitted documents", "RETRIEVE", "search_documents", "retrieval.completed", plan_id=1) as h:
        docs = rc.tool("search_documents", {"query": text[:400]})
        h["title"] = f"{len(docs['results'])} passages · {docs['retrieval']} · {docs['latency_ms']}ms"
        h["evidence_count"] = len(docs["results"])
    results = docs["results"]
    with rc.step("Composing grounded answer", "ASSESS", plan_id=2) as h:
        answer = None
        if llm.router.enabled and results:
            from app.security.injection import wrap_untrusted

            ctx = "\n\n".join(wrap_untrusted(f"[chunk {r['chunk_id']}] {r['document_name']} p.{r['page']} §{r['section']}\n{r['content']}",
                                             r["document_code"]) for r in results)
            ga = llm.structured("reasoning", "Answer the question using only the passages. Cite chunk ids.",
                                f"Question: {text}\n\nPassages:\n{ctx}", GroundedAnswer, rc.usage)
            if ga and not ga.insufficient_evidence:
                answer = ga.answer
                cited = {c.chunk_id for c in ga.citations}
                results = [r for r in results if r["chunk_id"] in cited] or results
        h["title"] = "Answer grounded in retrieved passages" if results else "Insufficient evidence"
    if not results:
        return "Insufficient evidence to answer from documents you are permitted to access."
    rc.card("citations", results=results[:5])
    if answer:
        return answer
    top = results[0]
    return (f"Based on {len(results)} permitted passage(s), the most relevant is from {top['document_name']} "
            f"(page {top['page']}{', ' + top['section'] if top['section'] else ''}): \"{top['content'][:320]}…\" "
            "See the cited sources below. (Deterministic engine — configure OPENAI_API_KEY/OPENAI_MODEL for synthesized answers.)")


# ------------------------------------------------------------------ approval execution run
def start_approval_execution(db: Session, principal: Principal, approval: ApprovalRequest) -> AgentRun:
    conv_id = None
    if approval.run_id:
        orig = db.get(AgentRun, approval.run_id)
        conv_id = orig.conversation_id if orig and orig.company_id == principal.company_id else None
    if conv_id is None:
        conv = Conversation(company_id=principal.company_id, user_id=principal.user_id, title=f"Execute {approval.code}")
        db.add(conv)
        db.flush()
        conv_id = conv.id
    run = AgentRun(company_id=principal.company_id, user_id=principal.user_id, conversation_id=conv_id,
                   objective=f"Execute approved action {approval.code}: {approval.title}", intent="approval_execution",
                   status="RUNNING", engine="deterministic", result={"approval_id": approval.id})
    db.add(run)
    db.add(Message(company_id=principal.company_id, conversation_id=conv_id, role="user",
                   content=f"Approved {approval.code}: {approval.title}"))
    db.commit()
    threading.Thread(target=_execute_approval, args=(run.id, principal, approval.id), daemon=True).start()
    return run


def _execute_approval(run_id: int, principal: Principal, approval_id: int) -> None:
    db = SessionLocal()
    run = db.get(AgentRun, run_id)
    rc = RunCtx(db, principal, run)
    t0 = time.perf_counter()
    try:
        ap = db.get(ApprovalRequest, approval_id)
        plan = db.get(RemediationPlan, ap.plan_id)
        finding = db.get(Finding, plan.finding_id)
        control = finding.control
        rc.tctx.approval_id = ap.id
        rc.set_plan(f"Execute and verify {ap.code}", [
            ("Confirm approval and authorization", "UNDERSTAND", None),
            ("Execute approved action (Demo Connector)", "REMEDIATE", "execute_remediation_action"),
            ("Verify outcome: expected vs actual", "VERIFY", "verify_remediation"),
            ("Update control and finding status", "VERIFY", None),
            ("Update compliance memory", "REMEMBER", "update_compliance_memory"),
        ])
        with rc.step("Confirming approval", "UNDERSTAND", event_type="approval.approved", plan_id=1) as h:
            h["title"] = f"{ap.code} approved by {principal.name} ({principal.role_name}) · backend authorization verified"
        with rc.step(f"Executing: {ap.title}", "REMEDIATE", "execute_remediation_action", "action.executed", plan_id=2) as h:
            res = rc.tool("execute_remediation_action", {"task_id": ap.task_id})
            h["title"] = f"Disabled {res['result'].get('disabled', 0)} accounts via {res['connector']} (Demo Simulation)" \
                if "disabled" in (res.get("result") or {}) else f"Executed {ap.title}"
        before = (plan.context or {}).get("access_report_before", {}).get("inactive_accounts")
        with rc.step("Running verification", "VERIFY", "verify_remediation", "verification.started", plan_id=3) as h:
            ver = rc.tool("verify_remediation", {"plan_code": plan.code})
            ok = ver["result"] == "PASSED"
            h["title"] = (f"Verification passed · inactive accounts {before} → 0" if ok and before is not None else
                          ("Verification passed" if ok else ver.get("message") or "Remediation was executed, but verification did not pass."))
            h["status"] = "done" if ok else "failed"
            h["detail"] = {"checks": ver.get("checks", [])}
        rc.emit("verification.completed", f"Verification {ver['result']}", "done" if ok else "failed", phase="VERIFY",
                detail={"record": ver["record"]})
        record_posture_snapshot(db, principal.company_id)
        with rc.step("Updating status", "VERIFY", plan_id=4) as h:
            h["title"] = (f"{control.code}: HIGH RISK → REMEDIATION → VERIFICATION → PASS · finding {finding.code} ready for closure"
                          if ok else f"{control.code} status unchanged — no completion recorded")
        with rc.step("Updating compliance memory", "REMEMBER", "update_compliance_memory", "memory.updated", plan_id=5) as h:
            h["title"] = f"Audit Memory Updated · {len(ver.get('memory_updates', []))} records" if ver.get("memory_updates") else "Memory updated"
        rc.card("verification", result=ver["result"], checks=ver.get("checks", []), before=before, after=0 if ok else None,
                evidence=ver.get("evidence"), control_test=ver.get("control_test"),
                control={"id": control.id, "code": control.code, "name": control.name},
                transition=["HIGH RISK", "REMEDIATION", "VERIFICATION", "PASS"] if ok else None,
                finding={"id": finding.id, "code": finding.code, "status": finding.status}, message=ver.get("message"))
        if ver.get("memory_updates"):
            rc.card("memory_update", records=ver["memory_updates"])
        acts = [_nba("Generate Audit Readiness Report", "agent", prompt="Generate an audit readiness report", intent={"intent": "generate_report"}),
                _nba(f"Open {control.code}", "navigate", to=f"/controls/{control.id}"),
                _nba(f"Open {finding.code}", "navigate", to=f"/findings/{finding.id}")]
        if not ok:
            acts.insert(0, _nba("Retry verification", "api", method="POST", path=f"/api/remediation/{plan.id}/verify"))
        rc.card("next_actions", actions=acts)
        content = (f"Approved action executed and verified. Inactive accounts before: {before}, after: 0. {control.code} "
                   f"re-tested PASS with new evidence {ver['evidence']['code']}; {finding.code} is ready for closure. "
                   "Audit memory updated." if ok else
                   f"{ver.get('message', 'Verification did not pass.')} {ver.get('fail_safe', '')}")
        _finish(rc, content, "COMPLETED" if ok else "FAILED", t0, error=None if ok else "VERIFICATION_NOT_PASSED")
    except ToolError as e:
        _finish(rc, f"Action failed. No completion has been recorded. ({e.message})", "FAILED", t0, error=e.code)
    except Exception:
        log.error("approval run failed: %s", traceback.format_exc())
        db.rollback()
        rc.run = db.get(AgentRun, run_id)
        _finish(rc, "Action failed. No completion has been recorded.", "FAILED", t0, error="INTERNAL_ERROR")
    finally:
        db.close()


def record_posture_snapshot(db: Session, company_id: int) -> None:
    from app.compliance.readiness import readiness
    from app.compliance.snapshot import load_snapshot
    from app.models import ComplianceEvent

    audit = next_upcoming_audit(db, company_id)
    r = readiness(load_snapshot(db, company_id, audit_id=audit.id if audit else None))
    db.add(ComplianceEvent(company_id=company_id, event_type="posture_snapshot", title="Readiness snapshot after verification",
                           entity_type="audit", entity_code=audit.code if audit else None,
                           occurred_at=datetime.now(timezone.utc), actor_type="agent", data={"readiness": r["overall"]}))
    db.commit()


def wf_general(rc: RunCtx, intent, text) -> str:
    rc.set_plan("Answer compliance question", [("Select and run tools via the Tool Gateway", "RETRIEVE", None)])
    with rc.step("Reasoning with tools (OpenAI Agents SDK)", "RETRIEVE", plan_id=1) as h:
        ans = llm.run_agent_with_tools(text, rc.tctx, ["get_controls", "get_findings", "search_evidence", "search_documents",
                                                      "find_recurring_findings", "assess_risk", "search_compliance_memory",
                                                      "get_audit_history", "calculate_readiness"], rc.usage)
        h["title"] = "Answer composed from tool results" if ans else "Deterministic engine: routed to document search"
    return ans if ans else wf_document_question(rc, intent, text)


def wf_simulate(rc: RunCtx, intent: IntentClassification, text: str) -> str:
    code = _resolve_control(rc, intent, text) or "C-024"
    rc.set_plan(f"Simulate failure of {code}", [("Simulate control failure (nothing saved)", "ASSESS", "simulate_control_failure")])
    with rc.step(f"Simulating failure of {code}", "ASSESS", "simulate_control_failure", "risk.assessed", plan_id=1) as h:
        out = rc.tool("simulate_control_failure", {"control_code": code, "test_result": "FAIL", "evidence_state": "EXPIRED"})
        h["title"] = f"{code}: risk {out['risk']['before']['category']} → {out['risk']['after']['category']} · readiness {out['readiness']['before']}% → {out['readiness']['after']}%"
    rc.card("simulation", **{k: v for k, v in out.items() if not k.startswith("_")})
    rc.card("next_actions", actions=[_nba("Open Compliance Simulator", "navigate", to=f"/simulator?control={code}"),
                                     _nba(f"Open {code}", "navigate", to=f"/controls/{out['control']['id']}")])
    f = out["potential_finding"]
    return (f"If {code} {out['control']['name']} failed now, its status would move {out['status']['before']} → {out['status']['after']}, "
            f"risk {out['risk']['before']['category']} → {out['risk']['after']['category']} and audit readiness {out['readiness']['before']}% → "
            f"{out['readiness']['after']}%. It affects {len(out['affected_requirements'])} requirements."
            + (f" A {f['severity']} finding would be raised; the remediation would need {out['required_approval']['risk_level']}-risk approval."
               if f else "") + " Simulation only — nothing was saved.")


def wf_policy_lab(rc: RunCtx, intent: IntentClassification, text: str) -> str:
    m = re.search(r"(\d{2,3})\s*days", text)
    days = int(m.group(1)) if m else 60
    pm = re.search(r"POL-\d{3}", text, re.I)
    pol = pm.group(0).upper() if pm else "POL-002"
    rc.set_plan(f"Policy Lab: {pol} review interval → {days} days", [("Simulate policy change (nothing saved)", "ASSESS", "simulate_policy_change")])
    with rc.step("Simulating policy change", "ASSESS", "simulate_policy_change", plan_id=1) as h:
        out = rc.tool("simulate_policy_change", {"policy_code": pol, "proposed_interval_days": days})
        h["title"] = out["summary"]
    rc.card("policy_simulation", **{k: v for k, v in out.items() if not k.startswith("_")})
    rc.card("next_actions", actions=[_nba("Open Policy Lab", "navigate", to=f"/policy-lab?policy={pol}&days={days}")])
    return (f"{out['summary']} {out['potential_overdue']} would immediately become overdue; about "
            f"{out['testing_impact']['extra_tests_per_year']} extra tests per year across "
            f"{len(out['affected_departments'])} departments; {out['evidence_impact']['stale_items']} evidence items would be older than the new interval. "
            "Simulation only — the policy was not changed.")


def wf_scan(rc: RunCtx, intent: IntentClassification, text: str) -> str:
    rc.set_plan("Run compliance scan", [("Scan evidence, tests, findings, deadlines; raise alerts", "DETECT", "run_compliance_scan")])
    with rc.step("Running compliance scan", "DETECT", "run_compliance_scan", "finding.detected", plan_id=1) as h:
        out = rc.tool("run_compliance_scan")
        h["title"] = f"{out['alerts']} alerts · {len(out['new_findings'])} new findings · readiness {out['readiness']}%"
    rc.card("summary_metrics", title="Compliance scan", items=[
        {"label": "Evidence expiring ≤14d", "value": out["evidence_expiring"], "tone": "warning"},
        {"label": "Evidence expired", "value": out["evidence_expired"], "tone": "danger"},
        {"label": "Overdue tests", "value": out["overdue_controls"], "tone": "danger"},
        {"label": "Findings past due", "value": out["findings_past_due"], "tone": "warning"},
        {"label": "Remediation deadlines", "value": out["remediation_deadlines"], "tone": "warning"},
        {"label": "New findings", "value": len(out["new_findings"]), "tone": "danger"}])
    return f"Scan complete: {out['alerts']} alerts ({out['notifications_sent']} new Demo Notifications), readiness {out['readiness']}%."


def wf_brief(rc: RunCtx, intent: IntentClassification, text: str) -> str:
    rc.set_plan("Morning Compliance Brief", [("Compile proactive brief", "UNDERSTAND", "get_morning_brief")])
    with rc.step("Compiling brief", "UNDERSTAND", "get_morning_brief", plan_id=1) as h:
        out = rc.tool("get_morning_brief")
        h["title"] = out["_summary"] or "Nothing needs attention"
    rc.card("brief", **{k: v for k, v in out.items() if not k.startswith("_")})
    tp = out["top_priority"]
    return ("Compliance Agent identified: " + "; ".join(f"{i['count']} {i['label']}" for i in out["items"] if i["count"]) + "."
            + (f" Top priority: {tp['name']} ({tp['code']})." if tp else ""))


def wf_drift(rc: RunCtx, intent: IntentClassification, text: str) -> str:
    rc.set_plan("Detect control drift", [("Compare previous and current control state", "DETECT", "detect_control_drift")])
    with rc.step("Comparing previous and current control state", "DETECT", "detect_control_drift", plan_id=1) as h:
        out = rc.tool("detect_control_drift")
        h["title"] = out["_summary"]
    rc.card("drift", items=out["items"])
    return f"{out['count']} controls show potential control drift. " + " ".join(
        f"{d['control']['code']}: {', '.join(s['type'].lower() for s in d['signals'])}." for d in out["items"][:4])


WORKFLOWS = {
    "audit_readiness": wf_audit_readiness, "explain_control": wf_explain_control, "investigate_control": wf_investigate,
    "remediation_plan": wf_remediation, "recurring_findings": wf_recurring, "what_changed": wf_what_changed,
    "memory_search": wf_memory_search, "expiring_evidence": wf_expiring, "controls_at_risk": wf_controls_at_risk,
    "untested_controls": wf_untested, "open_findings": wf_open_findings, "generate_report": wf_report,
    "document_question": wf_document_question, "general": wf_general, "simulate_control": wf_simulate,
    "policy_lab": wf_policy_lab, "compliance_scan": wf_scan, "morning_brief": wf_brief, "control_drift": wf_drift,
}


def remember_now(*a, **k):  # re-export for API modules
    return remember(*a, **k)


def aware(dt):
    return _aware(dt)
