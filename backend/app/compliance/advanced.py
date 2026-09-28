"""P4 intelligence: Policy Lab, Compliance Simulator, Audit Replay, Compliance Graph, Control Drift and
Regulatory Change Impact.

Simulations run in a throwaway session: ORM objects are changed in memory only, never flushed, and the
session is rolled back. Nothing a simulation does is saved.
"""
from __future__ import annotations

import difflib
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compliance.gaps import detect_gaps
from app.compliance.readiness import readiness
from app.compliance.snapshot import (
    OPEN_FINDING_STATUSES, Snapshot, _aware, derive_control_status, evidence_status, load_snapshot, next_upcoming_audit,
)
from app.database.session import SessionLocal
from app.models import (
    ApprovalRequest, Audit, ControlTest, Evidence, Finding, Policy, PolicyVersion, RegulatoryChange, RemediationAction,
)
from app.risk.engine import assess_control

SIM_LABEL = "Simulation — nothing is saved"
RISK_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


def _rederive(snap: Snapshot) -> None:
    for cv in snap.controls.values():
        if cv.misaligned and cv.control.frequency_days <= cv.misaligned["required_interval_days"]:
            cv.misaligned = None
        derive_control_status(cv, snap.now)


def _scope_snapshot(db: Session, company_id: int) -> tuple[Snapshot, Audit | None]:
    audit = next_upcoming_audit(db, company_id)
    return load_snapshot(db, company_id, audit_id=audit.id if audit else None), audit


# ============================================================ Policy Lab
POLICY_DOMAIN = {"POL-002": "Access Control", "POL-004": "Privacy", "POL-005": "Incident Management",
                 "POL-006": "Supplier Management", "POL-007": "Resilience", "POL-008": "Cryptography",
                 "POL-009": "Secure Development", "POL-010": "Privacy", "POL-011": "People", "POL-012": "Resilience",
                 "POL-013": "Change Management", "POL-014": "Physical Security", "POL-001": "Governance",
                 "POL-003": "People"}


def simulate_policy_change(company_id: int, policy_code: str, proposed_interval_days: int, cfg: dict) -> dict:
    """'Access reviews every 90 days → every 60 days': which controls, departments, evidence and tests change?"""
    db = SessionLocal()
    try:
        snap, audit = _scope_snapshot(db, company_id)
        pol = next((p for p in snap.policies if p.code == policy_code), None)
        if pol is None:
            raise ValueError("Unknown policy")
        domain = POLICY_DOMAIN.get(policy_code)
        linked = set((pol.parameters or {}).get("control_codes", []))
        candidates = [cv for cv in snap.controls.values() if cv.control.code in linked or cv.control.domain == domain]
        current_intervals = Counter(cv.control.frequency_days for cv in candidates)
        before_ready = readiness(snap)["overall"]
        before = {cv.control.id: (cv.status, assess_control(cv, cfg)) for cv in snap.controls.values()}

        affected = [cv for cv in candidates if cv.control.frequency_days > proposed_interval_days]
        original = {cv.control.id: cv.control.frequency_days for cv in affected}
        for cv in affected:
            cv.control.frequency_days = proposed_interval_days  # in-memory only, never flushed
        _rederive(snap)
        after_ready = readiness(snap)["overall"]

        rows, depts, stale_evidence, extra_tests = [], Counter(), [], 0.0
        for cv in affected:
            prev_status, prev_risk = before[cv.control.id]
            new_risk = assess_control(cv, cfg)
            dept = cv.control.department.name if cv.control.department else None
            if dept:
                depts[dept] += 1
            for e in cv.evidence:
                age = (snap.now - _aware(e.collected_at)).days
                if age > proposed_interval_days:
                    stale_evidence.append({"code": e.code, "name": e.name, "control": cv.control.code, "age_days": age})
            extra_tests += 365 / proposed_interval_days - 365 / original[cv.control.id]
            rows.append({"code": cv.control.code, "name": cv.control.name, "id": cv.control.id, "department": dept,
                         "current_interval_days": original[cv.control.id], "days_since_test": cv.days_since_test,
                         "status_before": prev_status, "status_after": cv.status,
                         "risk_before": prev_risk.category, "risk_after": new_risk.category,
                         "score_before": prev_risk.score, "score_after": new_risk.score,
                         "becomes_overdue": cv.status == "OVERDUE" and prev_status != "OVERDUE"})
        overdue_new = [r for r in rows if r["becomes_overdue"]]
        return {
            "label": SIM_LABEL, "policy": {"code": pol.code, "name": pol.name, "version": pol.current_version},
            "domain": domain, "proposed_interval_days": proposed_interval_days,
            "current_intervals": dict(current_intervals),
            "summary": f"Policy change would affect {len(rows)} control{'s' if len(rows) != 1 else ''}.",
            "affected_controls": sorted(rows, key=lambda r: (not r["becomes_overdue"], r["code"])),
            "affected_departments": [{"name": k, "controls": v} for k, v in depts.most_common()],
            "evidence_impact": {"stale_items": len(stale_evidence), "items": stale_evidence[:25]},
            "testing_impact": {"extra_tests_per_year": round(extra_tests, 1)},
            "potential_overdue": len(overdue_new),
            "readiness": {"before": before_ready, "after": after_ready, "audit": audit.name if audit else None},
        }
    finally:
        db.rollback()
        db.close()


# ============================================================ Compliance Simulator
def _category_for(code: str) -> str:
    return {"C-017": "access_review_overdue", "C-018": "privileged_access_review_failed",
            "C-031": "vendor_assessment_missing"}.get(code, "control_failure")


def simulate_control(company_id: int, control_code: str, test_result: str | None, evidence_state: str | None,
                     frequency_days: int | None, cfg: dict) -> dict:
    """'What happens if this control fails?'"""
    from app.authorization.permissions import APPROVAL_PERMISSION_BY_RISK
    from app.remediation.service import build_playbook

    db = SessionLocal()
    try:
        snap, audit = _scope_snapshot(db, company_id)
        cv = snap.by_code(control_code)
        if cv is None:
            raise ValueError("Unknown control")
        before_risk = assess_control(cv, cfg)
        before_status = cv.status
        before_ready = readiness(snap)["overall"]
        before_gaps = detect_gaps(snap)["gap_count"]
        now = snap.now
        changes = []
        if frequency_days:
            cv.control.frequency_days = frequency_days
            changes.append(f"test frequency {frequency_days} days")
        if test_result:
            cv.tests.insert(0, ControlTest(company_id=company_id, code="CT-SIM", control_id=cv.control.id, tested_at=now,
                                           result=test_result, questions=[], evidence_ids=[]))
            changes.append(f"latest test {test_result}")
        if evidence_state == "EXPIRED":
            for e in cv.evidence:
                e.valid_until = now - timedelta(days=1)
            changes.append("evidence expired")
        elif evidence_state == "MISSING":
            cv.evidence = []
            changes.append("evidence missing")
        elif evidence_state == "CONFLICTING" and cv.evidence:
            cv.evidence[0].is_conflicting = True
            changes.append("conflicting evidence")
        elif evidence_state == "VALID":
            for e in cv.evidence:
                e.valid_until = now + timedelta(days=120)
                e.is_conflicting = False
                e.verification_status = "verified"
            changes.append("evidence valid")
        _rederive(snap)
        after_risk = assess_control(cv, cfg)
        after_ready = readiness(snap)["overall"]
        after_gaps = detect_gaps(snap)

        failing = cv.status in ("FAIL", "OVERDUE", "EXPIRED", "PARTIAL") or cv.evidence_state in ("MISSING", "EXPIRED")
        finding = None
        remediation, approval = [], None
        if failing:
            sev = after_risk.category if after_risk.category != "LOW" else "MEDIUM"
            tf = Finding(company_id=company_id, code="SIMULATED", title=f"{cv.control.name}: {cv.status.replace('_', ' ').lower()}",
                         category=_category_for(cv.control.code), control_id=cv.control.id, severity=sev, status="OPEN",
                         detected_at=now)
            tf.control = cv.control
            title, rationale, steps = build_playbook(db, tf)
            finding = {"title": tf.title, "severity": sev, "category": tf.category,
                       "would_recur": any(f.category == tf.category for f in cv.findings)}
            remediation = [{"seq": i + 1, "title": s["title"], "risk": s["risk"]} for i, s in enumerate(steps)]
            top = max(steps, key=lambda s: RISK_RANK[s["risk"]])
            approval = {"risk_level": top["risk"], "action": top["title"],
                        "required_permission": APPROVAL_PERMISSION_BY_RISK[top["risk"]] or "none — executes automatically"}
        reqs = [r for r in snap.requirements.values() if r.code in cv.requirement_codes]
        return {
            "label": SIM_LABEL, "control": {"code": cv.control.code, "name": cv.control.name, "id": cv.control.id,
                                            "department": cv.control.department.name if cv.control.department else None},
            "changes": changes,
            "affected_requirements": [{"code": r.code, "title": r.title, "framework": snap.frameworks[r.framework_id].code} for r in reqs],
            "status": {"before": before_status, "after": cv.status},
            "risk": {"before": before_risk.as_dict(), "after": after_risk.as_dict()},
            "readiness": {"before": before_ready, "after": after_ready, "audit": audit.name if audit else None},
            "gaps": {"before": before_gaps, "after": after_gaps["gap_count"]},
            "potential_finding": finding, "recommended_remediation": remediation, "required_approval": approval,
        }
    finally:
        db.rollback()
        db.close()


# ============================================================ Audit Replay
def audit_replay(db: Session, company_id: int, audit_id: int) -> dict:
    a = db.get(Audit, audit_id)
    if a is None or a.company_id != company_id:
        raise ValueError("Audit not found")
    snap = load_snapshot(db, company_id, audit_id=audit_id)
    start = datetime.combine(a.start_date, datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(a.end_date or a.start_date, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1)
    ctrls = snap.in_scope_controls()
    ids = {cv.control.id for cv in ctrls}
    reqs = snap.in_scope_requirements()
    tests = db.execute(select(ControlTest).where(ControlTest.company_id == company_id, ControlTest.control_id.in_(ids),
                                                 ControlTest.tested_at >= start - timedelta(days=3),
                                                 ControlTest.tested_at <= end)).scalars().all()
    ev = db.execute(select(Evidence).where(Evidence.company_id == company_id, Evidence.control_id.in_(ids),
                                           Evidence.collected_at <= end)).scalars().all()
    used = [e for e in ev if _aware(e.valid_until) >= start]
    findings = [f for f in snap.findings if f.audit_id == audit_id]
    fids = {f.id for f in findings}
    plans = [p for p in snap.plans if p.finding_id in fids]
    pids = {p.id for p in plans}
    tasks = [t for t in snap.tasks if t.plan_id in pids]
    approvals = db.execute(select(ApprovalRequest).where(ApprovalRequest.company_id == company_id,
                                                         ApprovalRequest.plan_id.in_(pids or {0}))).scalars().all()
    actions = db.execute(select(RemediationAction).where(RemediationAction.task_id.in_([t.id for t in tasks] or [0]))).scalars().all()
    vers = [v for v in snap.verifications if v.finding_id in fids]
    code = {cv.control.id: cv.control.code for cv in snap.controls.values()}
    frames: list[dict] = []

    def frame(kind, at, title, items, tone="neutral"):
        frames.append({"kind": kind, "at": at.isoformat() if at else None, "title": title, "items": items, "tone": tone})

    frame("scope", start, f"Scope: {len(reqs)} requirements · {len(ctrls)} controls",
          [{"code": r.code, "label": r.title} for r in reqs[:60]])
    frame("tests", start, f"{len(tests)} control tests performed during fieldwork",
          [{"code": t.code, "label": f"{code.get(t.control_id)} · {t.result}", "status": t.result} for t in sorted(tests, key=lambda t: t.tested_at)],
          "danger" if any(t.result == "FAIL" for t in tests) else "success")
    frame("evidence", start, f"{len(used)} evidence items relied on",
          [{"code": e.code, "label": f"{code.get(e.control_id)} · {e.name}"} for e in used[:60]])
    frame("findings", end, f"{len(findings)} findings raised",
          [{"code": f.code, "label": f"{code.get(f.control_id)} · {f.title}", "status": f.severity, "id": f.id} for f in findings],
          "danger" if findings else "success")
    for p in sorted(plans, key=lambda p: p.created_at):
        ts = [t for t in tasks if t.plan_id == p.id]
        frame("remediation", _aware(p.created_at), f"{p.code}: {p.title}",
              [{"code": f"#{t.seq}", "label": t.title, "status": t.status} for t in sorted(ts, key=lambda t: t.seq)], "info")
    for ap in approvals:
        frame("approval", _aware(ap.decided_at or ap.created_at), f"{ap.code} {ap.status.lower()}: {ap.title}",
              [{"code": ap.risk_level, "label": ap.decision_note or ap.reason}], "warning")
    for ac in actions:
        frame("action", _aware(ac.executed_at), f"Action executed: {ac.action_type}", [{"code": ac.status, "label": str(ac.result)[:120]}], "info")
    for v in sorted(vers, key=lambda v: v.verified_at):
        frame("verification", _aware(v.verified_at), f"{v.code} verification {v.result.lower()}",
              [{"code": c.get("name", ""), "label": f"expected {c.get('expected')} · actual {c.get('actual')}"} for c in v.checks],
              "success" if v.result == "PASSED" else "danger")
    closed = [f for f in findings if f.status == "CLOSED"]
    frame("result", max([_aware(f.closed_at) for f in closed], default=end),
          f"Final result: {a.outcome or a.status} · {len(closed)}/{len(findings)} findings closed",
          [{"code": f.code, "label": f.status} for f in findings], "success" if len(closed) == len(findings) else "warning")
    frames.sort(key=lambda f: (f["at"] or ""))
    order = ["scope", "tests", "evidence", "findings"]
    frames.sort(key=lambda f: (0 if f["kind"] in order else 1, order.index(f["kind"]) if f["kind"] in order else 0, f["at"] or ""))
    return {"audit": {"id": a.id, "code": a.code, "name": a.name, "framework": a.framework.name, "status": a.status,
                      "start": a.start_date.isoformat(), "end": a.end_date.isoformat() if a.end_date else None, "outcome": a.outcome},
            "frames": frames,
            "stats": {"requirements": len(reqs), "controls": len(ctrls), "tests": len(tests), "evidence": len(used),
                      "findings": len(findings), "plans": len(plans), "approvals": len(approvals), "verifications": len(vers),
                      "closed": len(closed)}}


# ============================================================ Compliance Graph
def compliance_graph(snap: Snapshot, cfg: dict, focus: str | None = None, framework: str | None = None,
                     only_attention: bool = True) -> dict:
    nodes: dict[str, dict] = {}
    edges: set[tuple[str, str]] = set()

    def add(nid, kind, label, sub, status=None, link=None, extra=None):
        nodes.setdefault(nid, {"id": nid, "kind": kind, "label": label, "sub": sub, "status": status, "link": link, **(extra or {})})

    ctrls = list(snap.controls.values())
    if framework:
        ctrls = [cv for cv in ctrls if framework in cv.framework_codes]
    if focus:
        ctrls = [cv for cv in ctrls if cv.control.code == focus]
    elif only_attention:
        ctrls = [cv for cv in ctrls if cv.status not in ("PASS",) and (cv.active_findings or cv.status != "AT_RISK")]
    for cv in ctrls:
        c = cv.control
        r = assess_control(cv, cfg)
        cid = f"c{c.id}"
        add(cid, "control", c.code, c.name, cv.status, f"/controls/{c.id}", {"risk": r.category, "score": r.score})
        for rq in (x for x in snap.requirements.values() if x.code in cv.requirement_codes):
            if framework and snap.frameworks[rq.framework_id].code != framework:
                continue
            add(f"r{rq.id}", "requirement", rq.code, rq.title, rq.status.upper(), "/requirements")
            edges.add((f"r{rq.id}", cid))
        for e in cv.evidence:
            add(f"e{e.id}", "evidence", e.code, e.name, evidence_status(e, snap.now), f"/evidence?focus={e.id}")
            edges.add((cid, f"e{e.id}"))
        if cv.tests:
            t = cv.tests[0]
            add(f"t{t.id}", "test", t.code, f"{t.result} · {_aware(t.tested_at).date()}", t.result)
            edges.add((cid, f"t{t.id}"))
            for e in cv.evidence:
                edges.add((f"e{e.id}", f"t{t.id}"))
        recent = [f for f in cv.findings if f.status in OPEN_FINDING_STATUSES][:2] + \
                 [f for f in cv.findings if f.status not in OPEN_FINDING_STATUSES][:2]
        for f in recent:
            add(f"f{f.id}", "finding", f.code, f.title, f.status, f"/findings/{f.id}", {"severity": f.severity})
            edges.add((f"t{cv.tests[0].id}" if cv.tests else cid, f"f{f.id}"))
            for p in (p for p in snap.plans if p.finding_id == f.id):
                add(f"p{p.id}", "remediation", p.code, p.title, p.status, "/remediation")
                edges.add((f"f{f.id}", f"p{p.id}"))
                for v in (v for v in snap.verifications if v.plan_id == p.id):
                    add(f"v{v.id}", "verification", v.code, v.result, v.result)
                    edges.add((f"p{p.id}", f"v{v.id}"))
    counts = Counter(n["kind"] for n in nodes.values())
    return {"nodes": list(nodes.values()), "edges": [{"from": a, "to": b} for a, b in edges], "counts": counts,
            "layers": ["requirement", "control", "evidence", "test", "finding", "remediation", "verification"]}


# ============================================================ Control Drift
def control_drift(db: Session, snap: Snapshot) -> list[dict]:
    pol_versions = db.execute(select(PolicyVersion, Policy).join(Policy, Policy.id == PolicyVersion.policy_id)
                              .where(Policy.company_id == snap.company_id)).all()
    old_evidence = defaultdict(list)
    for e in db.execute(select(Evidence).where(Evidence.company_id == snap.company_id, Evidence.is_current.is_(False))).scalars():
        old_evidence[e.control_id].append(e)
    out = []
    for cv in snap.controls.values():
        c = cv.control
        last_pass = next((t for t in cv.tests if t.result == "PASS"), None)
        signals = []
        if cv.misaligned:
            m = cv.misaligned
            signals.append({"type": "Requirement changed", "previous": f"{m['requirement']} satisfied by {m['control_interval_days']}-day cycle",
                            "current": f"v{m['version']} requires {m['required_interval_days']} days", "impact": "Control no longer satisfies the requirement"})
        if last_pass and len(cv.owner_history) > 1:
            changed = [o for o in cv.owner_history[1:] if o["from"] > _aware(last_pass.tested_at).isoformat()]
            if changed:
                signals.append({"type": "Owner changed since last passing test", "previous": cv.owner_history[-2]["name"],
                                "current": cv.owner_history[-1]["name"], "impact": "Implementation knowledge may not have transferred"})
        prev = sorted(old_evidence.get(c.id, []), key=lambda e: _aware(e.collected_at))
        if prev and cv.evidence:
            p, n = prev[-1], cv.evidence[0]
            if p.source != n.source or n.completeness < p.completeness:
                signals.append({"type": "Evidence no longer matches", "previous": f"{p.source} · {round(p.completeness * 100)}% population",
                                "current": f"{n.source} · {round(n.completeness * 100)}% population", "impact": "Evidence method or coverage changed"})
        elif prev and not cv.evidence:
            signals.append({"type": "Evidence no longer produced", "previous": f"{prev[-1].code} {prev[-1].name}",
                            "current": "No current evidence", "impact": "Control operation cannot be demonstrated"})
        for v, pol in pol_versions:
            if v.change_summary.startswith(("Annual review", "Previous approved")):
                continue  # routine re-approval, no substantive change
            if c.code in (pol.parameters or {}).get("control_codes", []) and v.effective_date and last_pass and \
                    v.effective_date > _aware(last_pass.tested_at).date() and v.version == pol.current_version:
                signals.append({"type": "Policy changed after last test", "previous": f"{pol.code} before v{v.version}",
                                "current": f"{pol.code} v{v.version} ({v.change_summary})", "impact": "Control not re-tested against current policy"})
        if len(cv.tests) >= 3:
            gaps = [(_aware(a.tested_at) - _aware(b.tested_at)).days for a, b in zip(cv.tests[:4], cv.tests[1:4])]
            avg = sum(gaps) / len(gaps)
            if avg > c.frequency_days * 1.2:
                signals.append({"type": "Operating cadence drifted", "previous": f"designed every {c.frequency_days} days",
                                "current": f"actually every ~{round(avg)} days", "impact": "Control runs less often than designed"})
        if signals:
            out.append({"control": {"id": c.id, "code": c.code, "name": c.name, "status": cv.status, "owner": cv.owner_name},
                        "label": "Potential Control Drift", "signals": signals,
                        "evidence": [{"code": e.code, "name": e.name, "status": evidence_status(e, snap.now)} for e in cv.evidence],
                        "severity": "HIGH" if any(s["type"] in ("Requirement changed", "Evidence no longer produced") for s in signals)
                        else "MEDIUM"})
    return sorted(out, key=lambda d: (d["severity"] != "HIGH", -len(d["signals"])))


# ============================================================ Regulatory change impact
def regulatory_impact(db: Session, snap: Snapshot, change_id: int, cfg: dict) -> dict:
    ch = db.get(RegulatoryChange, change_id)
    if ch is None or ch.company_id != snap.company_id:
        raise ValueError("Change not found")
    req = snap.requirements.get(ch.requirement_id)
    vers = snap.req_versions.get(req.id, []) if req else []
    old = next((v for v in vers if v.version == ch.old_version), None)
    new = next((v for v in vers if v.version == ch.new_version), None)
    diff = []
    if old and new:
        for tok in difflib.ndiff(old.description.split(), new.description.split()):
            if tok[0] in "+- ":
                diff.append({"op": {"+": "add", "-": "del", " ": "same"}[tok[0]], "text": tok[2:]})
    cids = snap.req_to_controls.get(req.id, []) if req else []
    cvs = [snap.controls[c] for c in cids]
    evid = [(cv, e) for cv in cvs for e in cv.evidence]
    fnd = [f for cv in cvs for f in cv.findings if f.status in OPEN_FINDING_STATUSES]
    audits = []
    for a in snap.audits:
        if a.status != "completed" and req and a.framework_id == req.framework_id:
            audits.append({"id": a.id, "name": a.name, "date": a.start_date.isoformat()})
    risks = [{"code": cv.control.code, "name": cv.control.name, "status": cv.status, **assess_control(cv, cfg).as_dict()} for cv in cvs]
    worst = max((r["category"] for r in risks), key=lambda c: RISK_RANK[c], default=ch.risk)
    new_param = (new.parameters or {}).get("max_interval_days") if new else None
    misaligned = [cv.control.code for cv in cvs if new_param and cv.control.frequency_days > new_param]
    return {
        "change": {"id": ch.id, "code": ch.code, "title": ch.title, "type": ch.change_type, "old_version": ch.old_version,
                   "new_version": ch.new_version, "effective_date": ch.effective_date.isoformat(), "source": ch.source_label,
                   "status": ch.status},
        "requirement": {"code": req.code, "title": req.title} if req else None,
        "old_text": old.description if old else None, "new_text": new.description if new else None, "diff": diff,
        "change_summary": new.change_summary if new else ch.summary,
        "affected_controls": risks,
        "affected_departments": sorted({cv.control.department.name for cv in cvs if cv.control.department}),
        "affected_evidence": [{"code": e.code, "name": e.name, "control": cv.control.code, "status": evidence_status(e, snap.now)} for cv, e in evid],
        "affected_findings": [{"code": f.code, "title": f.title, "id": f.id} for f in fnd],
        "upcoming_audits": audits,
        "misaligned_controls": misaligned,
        "new_risk": worst if not misaligned else max(worst, "HIGH", key=lambda c: RISK_RANK[c]),
        "summary": (f"{ch.code} affects {len(cvs)} control(s), {len(set(d for d in (cv.control.department.name for cv in cvs if cv.control.department)))} department(s), "
                    f"{len(evid)} evidence item(s) and {len(audits)} upcoming audit(s)." if req else "No requirement linked."),
        "no_mapped_control": bool(req) and not cvs,
    }

