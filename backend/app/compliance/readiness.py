"""NovaTech Compliance Readiness Indicators (not certification scores) and 'what changed' comparison."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.compliance.gaps import detect_gaps
from app.compliance.recurring import detect_recurring
from app.compliance.snapshot import OPEN_FINDING_STATUSES, Snapshot, _aware, evidence_status
from app.risk.engine import assess_control

INDICATOR_LABEL = "NovaTech Compliance Readiness Indicators"
CONTROL_CREDIT = {"PASS": 1.0, "AT_RISK": 0.7, "PARTIAL": 0.5, "EXPIRED": 0.4, "OVERDUE": 0.25,
                  "NOT_TESTED": 0.0, "FAIL": 0.0}
EVIDENCE_CREDIT = {"VALID": 1.0, "EXPIRING": 0.6, "UNVERIFIED": 0.5, "CONFLICTING": 0.3, "EXPIRED": 0.0,
                   "REJECTED": 0.0}
SEV_WEIGHT = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
WEIGHTS = {"controls": 0.30, "evidence": 0.25, "findings": 0.15, "remediation": 0.15, "policy": 0.15}


def readiness(snap: Snapshot) -> dict:
    now = snap.now
    controls = snap.in_scope_controls()
    ids = {cv.control.id for cv in controls}

    ctrl = sum(CONTROL_CREDIT.get(cv.status, 0) for cv in controls) / max(len(controls), 1)

    # evidence coverage per control: a control is only as well evidenced as its weakest current item
    ev_scores = []
    n_items = 0
    for cv in controls:
        n_items += len(cv.evidence)
        if not cv.evidence:
            ev_scores.append(0.0)
        else:
            ev_scores.append(min(EVIDENCE_CREDIT.get(evidence_status(e, now), 0) * e.completeness for e in cv.evidence))
    evid = sum(ev_scores) / max(len(ev_scores), 1)

    window = now - timedelta(days=365)
    recent = [f for f in snap.findings if f.control_id in ids and _aware(f.detected_at) >= window]
    total_w = sum(SEV_WEIGHT[f.severity] for f in recent) or 1
    open_w = sum(SEV_WEIGHT[f.severity] for f in recent if f.status in OPEN_FINDING_STATUSES)
    find = 1 - open_w / total_w

    plan_ids = {p.id for p in snap.plans if any(f.id == p.finding_id and f.control_id in ids for f in snap.findings)}
    tasks = [t for t in snap.tasks if t.plan_id in plan_ids and t.status != "CANCELLED"]
    today = now.date()

    def task_credit(t) -> float:
        if t.status == "COMPLETED":
            if t.due_date and t.completed_at and _aware(t.completed_at).date() > t.due_date:
                return 0.5  # completed late
            return 1.0
        if t.due_date and t.due_date < today:
            return 0.0  # overdue
        return 0.6 if t.status in ("IN_PROGRESS", "AWAITING_APPROVAL") else 0.4

    rem = sum(task_credit(t) for t in tasks) / max(len(tasks), 1)

    pols = snap.policies
    def pol_ok(p) -> float:
        overdue = p.last_reviewed_at and (today - p.last_reviewed_at).days > p.review_frequency_days
        if p.status in ("EXPIRED", "CHANGE_REQUIRED"):
            return 0.0
        if overdue or p.status == "REVIEW_DUE":
            return 0.5
        return 1.0
    pol = sum(pol_ok(p) for p in pols) / max(len(pols), 1)

    ind = {"controls": ctrl, "evidence": evid, "findings": find, "remediation": rem, "policy": pol}
    overall = sum(ind[k] * WEIGHTS[k] for k in WEIGHTS)
    return {
        "label": INDICATOR_LABEL,
        "disclaimer": "Prototype indicators for prioritisation only — not an official certification or audit score.",
        "overall": round(overall * 100),
        "indicators": {
            "controls": {"value": round(ctrl * 100), "label": "Controls", "basis": f"{len(controls)} controls in scope"},
            "evidence": {"value": round(evid * 100), "label": "Evidence", "basis": f"{n_items} evidence items across {len(ev_scores)} controls"},
            "findings": {"value": round(find * 100), "label": "Open Findings",
                         "basis": f"{sum(1 for f in recent if f.status in OPEN_FINDING_STATUSES)} open of {len(recent)} in last 12 months"},
            "remediation": {"value": round(rem * 100), "label": "Remediation", "basis": f"{len(tasks)} remediation tasks"},
            "policy": {"value": round(pol * 100), "label": "Policy Alignment", "basis": f"{len(pols)} policies"},
        },
        "weights": WEIGHTS,
    }


def posture(snap: Snapshot, risk_cfg: dict | None = None) -> dict:
    """Everything the Command Center and the agent need about the current moment."""
    controls = snap.in_scope_controls()
    risks = {cv.control.id: assess_control(cv, risk_cfg) for cv in controls}
    gaps = detect_gaps(snap)
    recurring = detect_recurring(snap)
    ids = {cv.control.id for cv in controls}
    open_findings = [f for f in snap.findings if f.status in OPEN_FINDING_STATUSES and f.control_id in ids]
    status_counts: dict[str, int] = {}
    for cv in controls:
        status_counts[cv.status] = status_counts.get(cv.status, 0) + 1
    risk_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for r in risks.values():
        risk_counts[r.category] += 1
    expiring = [(cv, e) for cv in controls for e in cv.evidence if evidence_status(e, snap.now) == "EXPIRING"]
    today = snap.now.date()
    plan_ids = {p.id for p in snap.plans if p.finding_id in {f.id for f in open_findings}}
    overdue_tasks = [t for t in snap.tasks if t.plan_id in plan_ids and t.status not in ("COMPLETED", "CANCELLED")
                     and t.due_date and t.due_date < today]
    top = sorted(controls, key=lambda cv: -risks[cv.control.id].score)
    return {
        "readiness": readiness(snap),
        "open_findings": len(open_findings),
        "critical_risks": risk_counts["CRITICAL"],
        "high_risks": risk_counts["HIGH"],
        "risk_counts": risk_counts,
        "controls_at_risk": sum(1 for cv in controls if cv.status != "PASS"),
        "overdue_controls": status_counts.get("OVERDUE", 0),
        "evidence_expiring": len(expiring),
        "overdue_remediation": len(overdue_tasks),
        "recurring_findings": len(recurring),
        "gap_count": gaps["gap_count"],
        "control_status_counts": status_counts,
        "controls_total": len(controls),
        "requirements_total": len(snap.in_scope_requirements()),
        "evidence_total": sum(len(cv.evidence) for cv in controls),
        "top_risks": [{"code": cv.control.code, "name": cv.control.name, "id": cv.control.id, "status": cv.status,
                       **risks[cv.control.id].as_dict()} for cv in top[:8] if risks[cv.control.id].score >= 25],
        "expiring_items": [{"code": e.code, "name": e.name, "control": cv.control.code,
                            "valid_until": _aware(e.valid_until).date().isoformat(),
                            "days_left": (_aware(e.valid_until) - snap.now).days} for cv, e in expiring],
        "_risks": risks, "_gaps": gaps, "_recurring": recurring,
    }


def what_changed(snap: Snapshot) -> dict:
    """Compare today's state against the end of the most recent completed audit."""
    done = sorted([a for a in snap.audits if a.status == "completed" and a.end_date], key=lambda a: a.end_date)
    if not done:
        return {"baseline": None, "items": []}
    upcoming = sorted([a for a in snap.audits if a.status != "completed"], key=lambda a: a.start_date)
    same_fw = [a for a in done if upcoming and a.framework_id == upcoming[0].framework_id]
    base = (same_fw or done)[-1]  # previous audit of the same framework as the next audit
    since = datetime.combine(base.end_date, datetime.min.time(), tzinfo=timezone.utc)
    items: list[dict] = []
    for rid, vers in snap.req_versions.items():
        for v in vers:
            if v.effective_date and datetime.combine(v.effective_date, datetime.min.time(), tzinfo=timezone.utc) > since:
                r = snap.requirements[rid]
                items.append({"kind": "CHANGED", "area": "Requirements", "code": r.code,
                              "title": f"{r.title} → v{v.version}", "detail": v.change_summary})
    for r in snap.requirements.values():
        if _aware(r.created_at) > since and not snap.req_versions.get(r.id):
            items.append({"kind": "NEW", "area": "Requirements", "code": r.code, "title": r.title, "detail": "New requirement"})
    for p in snap.policies:
        if p.status in ("CHANGE_REQUIRED", "EXPIRED"):
            items.append({"kind": "AT_RISK", "area": "Policies", "code": p.code, "title": p.name,
                          "detail": f"Status {p.status.replace('_', ' ').lower()}"})
    for f in snap.findings:
        det = _aware(f.detected_at)
        if det > since and f.status in OPEN_FINDING_STATUSES:
            items.append({"kind": "NEW", "area": "Findings", "code": f.code, "title": f.title, "detail": f.severity})
        if f.closed_at and _aware(f.closed_at) > since:
            items.append({"kind": "RESOLVED", "area": "Findings", "code": f.code, "title": f.title,
                          "detail": f"Closed {_aware(f.closed_at).date().isoformat()}"})
    for rec in detect_recurring(snap):
        items.append({"kind": "RECURRING", "area": "Findings", "code": rec["latest_finding"], "title": rec["title"],
                      "detail": f"{rec['occurrences']} occurrences on {rec['control_code']}"})
    for cv in snap.controls.values():
        if cv.status in ("FAIL", "OVERDUE", "EXPIRED"):
            items.append({"kind": "AT_RISK", "area": "Controls", "code": cv.control.code, "title": cv.control.name,
                          "detail": cv.status})
    new_ev = sum(1 for cv in snap.controls.values() for e in cv.evidence if _aware(e.collected_at) > since)
    items.append({"kind": "CHANGED", "area": "Evidence", "code": "—", "title": f"{new_ev} evidence items collected since baseline",
                  "detail": "Evidence refreshed"})
    counts: dict[str, int] = {}
    for it in items:
        counts[it["kind"]] = counts.get(it["kind"], 0) + 1
    return {"baseline": {"code": base.code, "name": base.name, "end_date": base.end_date.isoformat()},
            "counts": counts, "items": items}
