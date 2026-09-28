"""Loads a tenant's compliance state in a handful of queries and derives deterministic statuses.

Everything downstream (gap detection, risk, readiness, agent tools) reads from a Snapshot, so all
views of the same moment agree with each other.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ApprovalRequest,
    Audit,
    AuditScope,
    Control,
    ControlOwner,
    ControlTest,
    Evidence,
    Finding,
    Framework,
    Policy,
    RemediationPlan,
    RemediationTask,
    Requirement,
    RequirementControlMap,
    RequirementVersion,
    VerificationRecord,
)

OPEN_FINDING_STATUSES = {"OPEN", "IN_REMEDIATION", "READY_FOR_CLOSURE"}
EXPIRING_WINDOW_DAYS = 30


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ------------------------------------------------------------------ evidence
def evidence_status(ev: Evidence, now: datetime | None = None) -> str:
    now = now or now_utc()
    if ev.verification_status == "rejected":
        return "REJECTED"
    if ev.is_conflicting:
        return "CONFLICTING"
    vu = _aware(ev.valid_until)
    if vu < now:
        return "EXPIRED"
    if (vu - now).days <= EXPIRING_WINDOW_DAYS:
        return "EXPIRING"
    if ev.verification_status == "unverified":
        return "UNVERIFIED"
    return "VALID"


def evidence_freshness(ev: Evidence, now: datetime | None = None) -> dict:
    now = now or now_utc()
    collected, vu = _aware(ev.collected_at), _aware(ev.valid_until)
    total = max((vu - collected).days, 1)
    age = (now - collected).days
    remaining = (vu - now).days
    if remaining < 0:
        label = "EXPIRED"
    elif remaining <= EXPIRING_WINDOW_DAYS:
        label = "EXPIRING"
    elif age / total > 0.5:
        label = "AGING"
    else:
        label = "FRESH"
    return {"label": label, "age_days": age, "remaining_days": remaining, "validity_days": total,
            "pct_elapsed": round(min(max(age / total, 0), 1.5) * 100)}


# ------------------------------------------------------------------ views
@dataclass
class ControlView:
    control: Control
    owner_name: str | None
    owner_id: int | None
    owner_history: list[dict]
    evidence: list[Evidence]  # current evidence only
    tests: list[ControlTest]  # newest first
    findings: list[Finding]  # all, newest first
    requirement_codes: list[str]
    framework_codes: list[str]
    status: str = "NOT_TESTED"
    evidence_state: str = "MISSING"
    days_since_test: int | None = None
    requirement_changed: bool = False
    misaligned: dict | None = None

    @property
    def open_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.status in OPEN_FINDING_STATUSES]

    @property
    def active_findings(self) -> list[Finding]:
        """Open findings whose remediation has not yet been verified (READY_FOR_CLOSURE excluded)."""
        return [f for f in self.findings if f.status in ("OPEN", "IN_REMEDIATION")]


@dataclass
class Snapshot:
    company_id: int
    now: datetime
    frameworks: dict[int, Framework]
    requirements: dict[int, Requirement]
    req_versions: dict[int, list[RequirementVersion]]
    req_to_controls: dict[int, list[int]]
    controls: dict[int, ControlView]
    findings: list[Finding]
    plans: list[RemediationPlan]
    tasks: list[RemediationTask]
    verifications: list[VerificationRecord]
    policies: list[Policy]
    approvals: list[ApprovalRequest]
    audits: list[Audit]
    scope_control_ids: set[int] | None = None  # when loaded for an audit
    scope_requirement_ids: set[int] | None = None
    audit: Audit | None = None
    extras: dict = field(default_factory=dict)

    def by_code(self, code: str) -> ControlView | None:
        for cv in self.controls.values():
            if cv.control.code.upper() == code.upper():
                return cv
        return None

    def in_scope_controls(self) -> list[ControlView]:
        if self.scope_control_ids is None:
            return list(self.controls.values())
        return [cv for cid, cv in self.controls.items() if cid in self.scope_control_ids]

    def in_scope_requirements(self) -> list[Requirement]:
        if self.scope_requirement_ids is None:
            return list(self.requirements.values())
        return [r for rid, r in self.requirements.items() if rid in self.scope_requirement_ids]


STATUS_PRIORITY = ["FAIL", "OVERDUE", "EXPIRED", "PARTIAL", "NOT_TESTED", "AT_RISK", "PASS"]


def derive_control_status(cv: ControlView, now: datetime) -> None:
    c = cv.control
    latest = cv.tests[0] if cv.tests else None
    # evidence aggregate
    if not cv.evidence:
        cv.evidence_state = "MISSING"
    else:
        states = [evidence_status(e, now) for e in cv.evidence]
        if "CONFLICTING" in states:
            cv.evidence_state = "CONFLICTING"
        elif all(s in ("EXPIRED", "REJECTED") for s in states):
            cv.evidence_state = "EXPIRED"
        elif "EXPIRING" in states:
            cv.evidence_state = "EXPIRING"
        elif "UNVERIFIED" in states:
            cv.evidence_state = "UNVERIFIED"
        elif "EXPIRED" in states:
            cv.evidence_state = "PARTIALLY_EXPIRED"
        else:
            cv.evidence_state = "VALID"

    candidates: list[str] = []
    if latest is None:
        candidates.append("NOT_TESTED")
    else:
        cv.days_since_test = (now - _aware(latest.tested_at)).days
        if latest.result == "FAIL":
            candidates.append("FAIL")
        elif latest.result == "PARTIAL":
            candidates.append("PARTIAL")
        elif latest.result == "INSUFFICIENT_EVIDENCE":
            candidates.append("AT_RISK")
        if cv.days_since_test > c.frequency_days:
            candidates.append("OVERDUE")
    if cv.evidence_state in ("EXPIRED", "MISSING"):
        candidates.append("EXPIRED" if cv.evidence_state == "EXPIRED" else "AT_RISK")
    if cv.evidence_state in ("EXPIRING", "CONFLICTING", "UNVERIFIED", "PARTIALLY_EXPIRED") or cv.active_findings \
            or cv.requirement_changed or cv.misaligned:
        candidates.append("AT_RISK")
    candidates.append("PASS")
    cv.status = min(candidates, key=STATUS_PRIORITY.index)


def load_snapshot(db: Session, company_id: int, audit_id: int | None = None,
                  framework_code: str | None = None) -> Snapshot:
    now = now_utc()
    q = lambda m: db.execute(select(m).where(m.company_id == company_id)).scalars().all()  # noqa: E731

    frameworks = {f.id: f for f in q(Framework)}
    requirements = {r.id: r for r in q(Requirement)}
    req_versions: dict[int, list[RequirementVersion]] = defaultdict(list)
    for rv in q(RequirementVersion):
        req_versions[rv.requirement_id].append(rv)
    for lst in req_versions.values():
        lst.sort(key=lambda v: (v.effective_date or date.min))
    req_to_controls: dict[int, list[int]] = defaultdict(list)
    ctrl_to_reqs: dict[int, list[int]] = defaultdict(list)
    for m in q(RequirementControlMap):
        req_to_controls[m.requirement_id].append(m.control_id)
        ctrl_to_reqs[m.control_id].append(m.requirement_id)

    owners: dict[int, list[ControlOwner]] = defaultdict(list)
    for o in q(ControlOwner):
        owners[o.control_id].append(o)
    evidence: dict[int, list[Evidence]] = defaultdict(list)
    for e in db.execute(select(Evidence).where(Evidence.company_id == company_id, Evidence.is_current.is_(True))).scalars():
        evidence[e.control_id].append(e)
    tests: dict[int, list[ControlTest]] = defaultdict(list)
    for t in q(ControlTest):
        tests[t.control_id].append(t)
    findings = sorted(q(Finding), key=lambda f: _aware(f.detected_at), reverse=True)
    f_by_ctrl: dict[int, list[Finding]] = defaultdict(list)
    for f in findings:
        f_by_ctrl[f.control_id].append(f)

    controls: dict[int, ControlView] = {}
    for c in q(Control):
        own = sorted(owners.get(c.id, []), key=lambda o: _aware(o.assigned_at))
        current = next((o for o in reversed(own) if o.unassigned_at is None), None)
        req_ids = ctrl_to_reqs.get(c.id, [])
        cv = ControlView(
            control=c,
            owner_name=current.user.name if current else None,
            owner_id=current.user_id if current else None,
            owner_history=[{"name": o.user.name, "from": o.assigned_at.isoformat(),
                            "to": o.unassigned_at.isoformat() if o.unassigned_at else None} for o in own],
            evidence=sorted(evidence.get(c.id, []), key=lambda e: _aware(e.collected_at), reverse=True),
            tests=sorted(tests.get(c.id, []), key=lambda t: _aware(t.tested_at), reverse=True),
            findings=f_by_ctrl.get(c.id, []),
            requirement_codes=[requirements[r].code for r in req_ids if r in requirements],
            framework_codes=sorted({frameworks[requirements[r].framework_id].code for r in req_ids if r in requirements}),
        )
        # requirement change not yet reflected in a passing control test
        last_test = _aware(cv.tests[0].tested_at) if cv.tests else None
        for rid in req_ids:
            r = requirements.get(rid)
            if not r or r.status != "changed":
                continue
            vers = req_versions.get(rid, [])
            newest = vers[-1] if vers else None
            if newest and newest.effective_date:
                eff = datetime.combine(newest.effective_date, datetime.min.time(), tzinfo=timezone.utc)
                if last_test is None or last_test < eff:
                    cv.requirement_changed = True
                max_int = (newest.parameters or {}).get("max_interval_days")
                if max_int and c.frequency_days > max_int:
                    cv.misaligned = {"requirement": r.code, "required_interval_days": max_int,
                                     "control_interval_days": c.frequency_days, "version": newest.version}
        controls[c.id] = cv

    for cv in controls.values():
        derive_control_status(cv, now)

    snap = Snapshot(
        company_id=company_id, now=now, frameworks=frameworks, requirements=requirements,
        req_versions=req_versions, req_to_controls=req_to_controls, controls=controls, findings=findings,
        plans=q(RemediationPlan), tasks=q(RemediationTask), verifications=q(VerificationRecord),
        policies=q(Policy), approvals=q(ApprovalRequest), audits=q(Audit),
    )

    if audit_id is not None:
        audit = next((a for a in snap.audits if a.id == audit_id), None)
        if audit:
            snap.audit = audit
            rows = db.execute(select(AuditScope).where(AuditScope.company_id == company_id,
                                                       AuditScope.audit_id == audit_id)).scalars().all()
            snap.scope_control_ids = {r.control_id for r in rows if r.control_id}
            snap.scope_requirement_ids = {r.requirement_id for r in rows if r.requirement_id}
    elif framework_code:
        fw_ids = {f.id for f in frameworks.values() if f.code == framework_code}
        snap.scope_requirement_ids = {r.id for r in requirements.values() if r.framework_id in fw_ids}
        snap.scope_control_ids = {cid for rid in snap.scope_requirement_ids for cid in req_to_controls.get(rid, [])}
    return snap


def next_upcoming_audit(db: Session, company_id: int) -> Audit | None:
    return db.execute(
        select(Audit).where(Audit.company_id == company_id, Audit.status.in_(["planned", "in_progress"]))
        .order_by(Audit.start_date)
    ).scalars().first()
