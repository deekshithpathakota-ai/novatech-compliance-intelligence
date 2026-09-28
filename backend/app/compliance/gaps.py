"""Deterministic compliance gap detection (16 checks). Output is structured and evidence-linked."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from app.compliance.snapshot import Snapshot, _aware, evidence_status
from app.risk.engine import prior_occurrences

GAP_LABELS = {
    "CONTROL_NOT_TESTED": "Control not tested",
    "TEST_OVERDUE": "Control testing overdue",
    "EVIDENCE_MISSING": "Evidence missing",
    "EVIDENCE_EXPIRED": "Evidence expired",
    "EVIDENCE_INCOMPLETE": "Evidence incomplete",
    "REQUIREMENT_UNMAPPED": "Requirement currently has no mapped control",
    "CONTROL_NO_OWNER": "Control without owner",
    "FINDING_UNRESOLVED": "Previous finding unresolved",
    "REMEDIATION_OVERDUE": "Remediation overdue",
    "POLICY_EXPIRED": "Policy expired / change required",
    "REQUIREMENT_CHANGED": "Requirement changed since last test",
    "CONTROL_MISALIGNED": "Control no longer satisfies changed requirement",
    "RECURRING_FINDING": "Recurring finding",
    "CONFLICTING_EVIDENCE": "Conflicting evidence detected",
    "MISSING_APPROVAL": "Action awaiting required approval",
    "CONTROL_FAILURE": "Control failure",
}
SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}


@dataclass
class Gap:
    type: str
    subject_type: str  # control | requirement | policy
    subject_code: str
    subject_name: str
    severity: str
    message: str
    refs: list[dict] = field(default_factory=list)  # [{kind, code, label}]

    @property
    def label(self) -> str:
        return GAP_LABELS[self.type]

    def as_dict(self) -> dict:
        return {**asdict(self), "label": self.label}


def detect_gaps(snap: Snapshot) -> dict:
    now = snap.now
    gaps: list[Gap] = []
    warnings: list[Gap] = []
    controls = snap.in_scope_controls()

    for cv in controls:
        c = cv.control
        code, name = c.code, c.name
        latest = cv.tests[0] if cv.tests else None
        test_ref = [{"kind": "test", "code": latest.code, "label": f"{latest.code} ({latest.result})"}] if latest else []
        if latest is None:
            gaps.append(Gap("CONTROL_NOT_TESTED", "control", code, name, "MEDIUM", f"{code} has never been tested."))
        elif cv.days_since_test is not None and cv.days_since_test > c.frequency_days:
            gaps.append(Gap("TEST_OVERDUE", "control", code, name,
                            "HIGH" if cv.days_since_test > c.frequency_days * 1.25 else "MEDIUM",
                            f"Last tested {cv.days_since_test} days ago; required every {c.frequency_days} days.",
                            test_ref))
        if latest is not None and latest.result == "FAIL":
            gaps.append(Gap("CONTROL_FAILURE", "control", code, name, "CRITICAL" if c.criticality >= 5 else "HIGH",
                            f"Most recent test {latest.code} failed.", test_ref))

        if not cv.evidence:
            gaps.append(Gap("EVIDENCE_MISSING", "control", code, name, "MEDIUM",
                            "No evidence has been submitted for this control."))
        for ev in cv.evidence:
            st = evidence_status(ev, now)
            ref = [{"kind": "evidence", "code": ev.code, "label": ev.name}]
            if st == "EXPIRED":
                gaps.append(Gap("EVIDENCE_EXPIRED", "control", code, name, "HIGH",
                                f"{ev.code} expired {(now - _aware(ev.valid_until)).days} days ago.", ref))
            elif st == "EXPIRING":
                warnings.append(Gap("EVIDENCE_EXPIRED", "control", code, name, "INFO",
                                    f"{ev.code} expires in {(_aware(ev.valid_until) - now).days} days.", ref))
            elif st == "CONFLICTING":
                gaps.append(Gap("CONFLICTING_EVIDENCE", "control", code, name, "HIGH",
                                f"{ev.code} conflicts with another source.", ref))
            if ev.completeness < 1.0 and st not in ("EXPIRED",):
                gaps.append(Gap("EVIDENCE_INCOMPLETE", "control", code, name, "MEDIUM",
                                f"{ev.code} covers {round(ev.completeness * 100)}% of the required population.", ref))

        if cv.owner_id is None:
            gaps.append(Gap("CONTROL_NO_OWNER", "control", code, name, "MEDIUM", f"{code} has no assigned owner."))

        for f in cv.open_findings:
            gaps.append(Gap("FINDING_UNRESOLVED", "control", code, name, f.severity,
                            f"{f.code} '{f.title}' is {f.status.replace('_', ' ').lower()}.",
                            [{"kind": "finding", "code": f.code, "label": f.title}]))
        if cv.open_findings and prior_occurrences(cv) > 0:
            first = min(cv.findings, key=lambda f: _aware(f.detected_at))
            gaps.append(Gap("RECURRING_FINDING", "control", code, name, "HIGH",
                            f"Same issue recorded {prior_occurrences(cv) + 1} times since "
                            f"{_aware(first.detected_at).date().isoformat()}.",
                            [{"kind": "finding", "code": f.code, "label": f.title} for f in cv.findings[:3]]))
        if cv.requirement_changed:
            gaps.append(Gap("REQUIREMENT_CHANGED", "control", code, name, "MEDIUM",
                            "A mapped requirement changed after the control was last tested."))
        if cv.misaligned:
            m = cv.misaligned
            gaps.append(Gap("CONTROL_MISALIGNED", "control", code, name, "HIGH",
                            f"{m['requirement']} v{m['version']} requires every {m['required_interval_days']} days; "
                            f"control runs every {m['control_interval_days']} days.",
                            [{"kind": "requirement", "code": m["requirement"], "label": m["requirement"]}]))

    # requirements without mapped controls
    for r in snap.in_scope_requirements():
        if r.status != "retired" and not snap.req_to_controls.get(r.id):
            gaps.append(Gap("REQUIREMENT_UNMAPPED", "requirement", r.code, r.title, "MEDIUM",
                            "Requirement currently has no mapped control."))

    # remediation overdue / approvals pending (scoped by finding->control)
    scope_ids = {cv.control.id for cv in controls}
    finding_ctrl = {f.id: f.control_id for f in snap.findings}
    finding_code = {f.id: f for f in snap.findings}
    plan_by_id = {p.id: p for p in snap.plans}
    today = now.date()
    for t in snap.tasks:
        plan = plan_by_id.get(t.plan_id)
        if not plan or finding_ctrl.get(plan.finding_id) not in scope_ids:
            continue
        f = finding_code[plan.finding_id]
        cv = snap.controls[f.control_id]
        if t.status not in ("COMPLETED", "CANCELLED") and t.due_date and t.due_date < today:
            gaps.append(Gap("REMEDIATION_OVERDUE", "control", cv.control.code, cv.control.name, "MEDIUM",
                            f"Task '{t.title}' ({plan.code}) was due {t.due_date.isoformat()}.",
                            [{"kind": "remediation", "code": plan.code, "label": plan.title}]))
    for a in snap.approvals:
        if a.status == "PENDING" and a.plan_id in plan_by_id:
            f = finding_code.get(plan_by_id[a.plan_id].finding_id)
            if f and f.control_id in scope_ids:
                cv = snap.controls[f.control_id]
                gaps.append(Gap("MISSING_APPROVAL", "control", cv.control.code, cv.control.name, a.risk_level,
                                f"{a.code} '{a.title}' is awaiting {a.risk_level.lower()}-risk approval.",
                                [{"kind": "approval", "code": a.code, "label": a.title}]))

    # policies
    for p in snap.policies:
        linked = (p.parameters or {}).get("control_codes", [])
        if snap.scope_control_ids is not None and linked and not any(
                snap.by_code(cc) and snap.by_code(cc).control.id in scope_ids for cc in linked):
            continue
        overdue = p.last_reviewed_at and (today - p.last_reviewed_at).days > p.review_frequency_days
        if p.status in ("EXPIRED", "CHANGE_REQUIRED") or overdue:
            subj = snap.by_code(linked[0]) if linked else None
            gaps.append(Gap("POLICY_EXPIRED", "control" if subj else "policy",
                            subj.control.code if subj else p.code, subj.control.name if subj else p.name, "HIGH",
                            f"Policy {p.code} '{p.name}' v{p.current_version} status: "
                            f"{'review overdue' if overdue and p.status == 'ACTIVE' else p.status.replace('_', ' ').lower()}.",
                            [{"kind": "policy", "code": p.code, "label": p.name}]))

    gaps.sort(key=lambda g: (SEVERITY_ORDER.get(g.severity, 9), g.subject_code))
    subjects: dict[str, dict] = {}
    for g in gaps:
        s = subjects.setdefault(g.subject_code, {"subject_code": g.subject_code, "subject_name": g.subject_name,
                                                 "subject_type": g.subject_type, "gap_types": [],
                                                 "severity": g.severity})
        if g.type not in s["gap_types"]:
            s["gap_types"].append(g.type)
        if SEVERITY_ORDER.get(g.severity, 9) < SEVERITY_ORDER.get(s["severity"], 9):
            s["severity"] = g.severity
    return {
        "gaps": [g.as_dict() for g in gaps],
        "warnings": [w.as_dict() for w in warnings],
        "subjects": sorted(subjects.values(), key=lambda s: (SEVERITY_ORDER.get(s["severity"], 9), s["subject_code"])),
        "gap_count": len(subjects),
        "expiring_evidence": len(warnings),
        "checked_at": now.isoformat(),
    }
