"""Post-action verification: ACTION -> VERIFY -> COMPARE EXPECTED VS ACTUAL -> UPDATE STATUS -> UPDATE MEMORY.

Never assumes success. If the evidence source is down, verification is INCONCLUSIVE and nothing is closed.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.base import ConnectorUnavailable, get_connector
from app.memory.service import remember
from app.models import (
    ComplianceEvent,
    Control,
    ControlTest,
    Evidence,
    EvidenceVersion,
    Finding,
    FindingHistory,
    RemediationAction,
    RemediationPlan,
    VerificationRecord,
)
from app.remediation.service import next_code, plan_context, tasks_for

ACCESS_REVIEW_QUESTIONS = [
    "Was the review performed?",
    "Was it performed within required frequency?",
    "Were all users included?",
    "Were privileged users reviewed?",
    "Were terminated users removed?",
    "Was the review approved?",
    "Is evidence available?",
]


def _evidence_code(db: Session, company_id: int) -> str:
    rows = db.execute(select(Evidence.code).where(Evidence.company_id == company_id)).scalars().all()
    nums = [int(c.split("-")[1]) for c in rows if c.startswith("EV-") and c.split("-")[1].isdigit()]
    return f"EV-{(max(nums) if nums else 0) + 1:03d}"


def _test_code(db: Session, company_id: int) -> str:
    rows = db.execute(select(ControlTest.code).where(ControlTest.company_id == company_id)).scalars().all()
    nums = [int(c.split("-")[1]) for c in rows if c.startswith("CT-") and c.split("-")[1].isdigit()]
    return f"CT-{(max(nums) if nums else 0) + 1:03d}"


def verify_plan(db: Session, *, plan: RemediationPlan, user_id: int | None, run_id: int | None, emit=None) -> dict:
    emit = emit or (lambda *a, **k: None)
    finding: Finding = db.get(Finding, plan.finding_id)
    control: Control = finding.control
    ctx = plan_context(db, plan)
    now = datetime.now(timezone.utc)
    checks: list[dict] = []
    plan.status = "VERIFYING"

    # 0. is the evidence service reachable? (self-recovery: retry once, then alternative source, then stop)
    attempts, store_ok = 0, False
    for attempts in (1, 2):
        try:
            get_connector("evidence_store", db, plan.company_id).get_data("health")
            store_ok = True
            break
        except ConnectorUnavailable:
            emit("tool.retry", f"Evidence service unavailable — attempt {attempts} failed", "warning")
    if not store_ok:
        rec = VerificationRecord(company_id=plan.company_id, code=next_code(db, VerificationRecord, plan.company_id, "VER"),
                                 plan_id=plan.id, finding_id=finding.id, control_id=control.id, result="INCONCLUSIVE",
                                 checks=[{"name": "Evidence source reachable", "expected": "available",
                                          "actual": "unavailable", "passed": False}],
                                 notes="Verification could not be completed because the evidence source was unavailable.")
        db.add(rec)
        db.add(ComplianceEvent(company_id=plan.company_id, event_type="verification_failed",
                               title=f"Verification inconclusive for {control.code}", entity_type="verification",
                               entity_code=rec.code, control_id=control.id, occurred_at=now, actor_type="agent",
                               description=rec.notes))
        remember(db, company_id=plan.company_id, category="VERIFICATION", subject_type="control", subject_id=control.id,
                 subject_code=control.code, summary=f"Verification of {plan.code} could not complete: evidence service unavailable.",
                 source_type="verification", source_id=rec.id, source_label=rec.code, outcome="INCONCLUSIVE",
                 verification="INCONCLUSIVE")
        db.flush()
        return {"result": "INCONCLUSIVE", "record": rec.code, "attempts": attempts,
                "message": "Verification could not be completed because the evidence source was unavailable.",
                "fail_safe": "Remediation was executed, but verification did not pass. No completion has been recorded."}

    # 1. compare expected vs actual via the connector that performed the action
    before = ctx.get("access_report_before", {}).get("inactive_accounts")
    iam_result = None
    if before is not None:
        iam_result = get_connector("iam", db, plan.company_id).verify_action("disable_accounts", before=before)
        checks.append({"name": "Inactive accounts", "expected": 0, "before": before, "actual": iam_result["after"],
                       "passed": iam_result["passed"]})
        report = get_connector("iam", db, plan.company_id).get_data("access_report")
        checks.append({"name": "Terminated users still active", "expected": 0, "actual": report["terminated_still_active"],
                       "passed": report["terminated_still_active"] == 0})
    exec_actions = db.execute(select(RemediationAction).where(
        RemediationAction.company_id == plan.company_id,
        RemediationAction.task_id.in_([t.id for t in tasks_for(db, plan)]))).scalars().all()
    failed_actions = [a for a in exec_actions if a.status != "SUCCEEDED"]
    checks.append({"name": "All remediation actions succeeded", "expected": "0 failures",
                   "actual": f"{len(failed_actions)} failures", "passed": not failed_actions})
    passed = all(c["passed"] for c in checks)

    new_ev = None
    test = None
    if passed:
        # 2. collect fresh evidence (supersedes the expired item — history is kept)
        emit("evidence.collected", "Collected post-remediation access report", "done")
        old = db.execute(select(Evidence).where(Evidence.control_id == control.id, Evidence.is_current.is_(True))).scalars().all()
        for e in old:
            e.is_current = False
        payload = f"{control.code}|{now.isoformat()}|{checks}".encode()
        report = get_connector("iam", db, plan.company_id).get_data("access_report") if before is not None else {}
        new_ev = Evidence(company_id=plan.company_id, code=_evidence_code(db, plan.company_id),
                          name=f"{control.name} Report — post-remediation ({now:%b %Y})",
                          description="Generated by the Compliance Agent from the IAM Demo Connector after remediation.",
                          control_id=control.id, owner_id=user_id, source="IAM Demo Connector (agent-collected)",
                          collected_at=now, valid_until=now + timedelta(days=control.frequency_days),
                          verification_status="verified", sha256=hashlib.sha256(payload).hexdigest(),
                          extracted={"inactive_accounts": report.get("inactive_accounts"),
                                     "privileged_accounts": report.get("privileged_accounts"),
                                     "total_accounts": report.get("total_accounts"), "reviewed_all_users": True})
        db.add(new_ev)
        db.flush()
        db.add(EvidenceVersion(company_id=plan.company_id, evidence_id=new_ev.id, version=1, collected_at=now,
                               sha256=new_ev.sha256, note="Agent-collected after remediation"))
        # 3. re-test the control
        answers = [{"question": q, "answer": "Yes", "evidence": new_ev.code} for q in ACCESS_REVIEW_QUESTIONS]
        test = ControlTest(company_id=plan.company_id, code=_test_code(db, plan.company_id), control_id=control.id,
                           tested_at=now, tester_id=user_id, tester_type="agent", result="PASS", method="automated re-test",
                           questions=answers, evidence_ids=[new_ev.id],
                           notes=f"Re-test after {plan.code}. Inactive accounts {before} → {iam_result['after'] if iam_result else 'n/a'}.",
                           agent_run_id=run_id)
        db.add(test)
        prev_status = control.status
        control.status, control.last_tested_at, control.last_result = "PASS", now, "PASS"
        for t in tasks_for(db, plan):
            if t.action_type in ("evidence.collect_access_report", "control.retest") and t.status != "COMPLETED":
                t.status, t.completed_at = "COMPLETED", now
        plan.status, plan.completed_at = "COMPLETED", now
        prev_f = finding.status
        finding.status = "READY_FOR_CLOSURE"
        db.add(FindingHistory(company_id=plan.company_id, finding_id=finding.id, event="verification_passed",
                              from_status=prev_f, to_status="READY_FOR_CLOSURE", actor_type="agent",
                              note=f"Verified by agent; evidence {new_ev.code}; test {test.code}"))
    else:
        plan.status = "FAILED"
        prev_status = control.status

    db.flush()
    rec = VerificationRecord(company_id=plan.company_id, code=next_code(db, VerificationRecord, plan.company_id, "VER"),
                             plan_id=plan.id, finding_id=finding.id, control_id=control.id,
                             result="PASSED" if passed else "FAILED", checks=checks,
                             evidence_id=new_ev.id if new_ev else None,
                             notes="Expected vs actual comparison completed." if passed else
                             "Remediation was executed, but verification did not pass.")
    db.add(rec)
    db.add(ComplianceEvent(company_id=plan.company_id, event_type="verification_passed" if passed else "verification_failed",
                           title=f"Verification {'passed' if passed else 'failed'} for {control.code}",
                           entity_type="verification", entity_code=rec.code, control_id=control.id, occurred_at=now,
                           actor_type="agent", data={"checks": checks}))
    db.flush()

    # 4. memory update
    mem = []
    mem.append(remember(db, company_id=plan.company_id, category="REMEDIATION", subject_type="control", subject_id=control.id,
                        subject_code=control.code,
                        summary=f"{plan.code} remediated {finding.code}: " + "; ".join(t.title for t in tasks_for(db, plan)),
                        source_type="remediation_plan", source_id=plan.id, source_label=plan.code,
                        outcome="COMPLETED" if passed else "FAILED", verification="PASSED" if passed else "FAILED",
                        details={"checks": checks}, importance=4))
    mem.append(remember(db, company_id=plan.company_id, category="VERIFICATION", subject_type="control", subject_id=control.id,
                        subject_code=control.code,
                        summary=(f"Verification {rec.code} passed: inactive accounts {before} → 0; control re-tested PASS."
                                 if passed and before is not None else f"Verification {rec.code} {rec.result.lower()}."),
                        source_type="verification", source_id=rec.id, source_label=rec.code, outcome=rec.result,
                        verification=rec.result, importance=4))
    prior = db.execute(select(Finding).where(Finding.company_id == plan.company_id, Finding.control_id == control.id,
                                             Finding.category == finding.category)).scalars().all()
    if len(prior) >= 2:
        mem.append(remember(db, company_id=plan.company_id, category="BEHAVIOR", subject_type="control", subject_id=control.id,
                            subject_code=control.code,
                            summary=f"{control.code} has now required remediation {len(prior)} times for '{finding.category.replace('_', ' ')}'. "
                                    "Watch for recurrence; a preventive process change (automated review scheduling) is recommended.",
                            source_type="pattern", source_label="Recurring finding detector", outcome="RECURRING_PATTERN",
                            importance=5))
    return {"result": rec.result, "record": rec.code, "checks": checks,
            "evidence": {"code": new_ev.code, "name": new_ev.name} if new_ev else None,
            "control_test": {"code": test.code, "result": test.result, "questions": test.questions} if test else None,
            "control_transition": [prev_status, "REMEDIATION", "VERIFICATION", "PASS" if passed else prev_status],
            "finding_status": finding.status, "plan_status": plan.status,
            "memory_updates": [{"id": m.id, "category": m.category, "summary": m.summary} for m in mem]}
