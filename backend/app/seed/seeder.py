"""Deterministic, internally consistent demo dataset for NovaTech Solutions (+ a second tenant for isolation).

Dates are relative to 'now' so the demo stays evergreen (e.g. C-017 is always 142 days since last test).
Every finding maps to a real control, every remediation to a finding, every verification to a remediation.
"""
from __future__ import annotations

import hashlib
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.authorization.permissions import PERMISSIONS, ROLES
from app.compliance.snapshot import load_snapshot
from app.connectors.base import CONNECTOR_CATALOG
from app.documents.ingest import ingest_document
from app.models import *  # noqa: F403
from app.risk.engine import DEFAULT_RISK_CONFIG, MODEL_VERSION, assess_control
from app.seed.catalog import (
    CONTROLS, DEMO_PASSWORD, DEPARTMENTS, FIRST, FRAMEWORKS, LAST, PERSONAS, POLICIES, REQUIREMENTS,
)
from app.seed.documents import documents as demo_documents

KIND_TEMPLATES = {
    "evidence_missing": ("{n} evidence not retained for the period", "Evidence for the control could not be produced for the full audit period."),
    "test_overdue": ("{n} not performed within required frequency", "The control was executed later than its defined frequency."),
    "control_failure": ("{n} operating exception", "Testing identified exceptions in the operation of the control."),
    "documentation_gap": ("{n} procedure not documented", "The procedure supporting the control was not formally documented."),
    "partial_implementation": ("{n} partially implemented", "The control is implemented for some, but not all, in-scope systems."),
}
ROOT_CAUSES = ["Manual process dependent on a single individual", "Procedure not updated after tooling change",
               "Evidence retention not configured", "Ownership unclear after team restructure",
               "Scope of systems incomplete", "Reminder workflow not configured"]
EVIDENCE_KINDS = ["Execution record", "System export", "Owner sign-off"]


def h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def seed(db: Session) -> dict:
    R = random.Random(42)
    NOW = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    day = lambda n: NOW + timedelta(days=n)  # noqa: E731

    # ------------------------------------------------------------ RBAC
    perms = {}
    for code, desc in PERMISSIONS.items():
        p = Permission(code=code, description=desc)
        db.add(p)
        perms[code] = p
    roles = {}
    db.flush()
    for code, spec in ROLES.items():
        r = Role(code=code, name=spec["name"], description=spec["description"])
        db.add(r)
        db.flush()
        roles[code] = r
        for pc in spec["permissions"]:
            db.add(RolePermission(role_id=r.id, permission_id=perms[pc].id))

    # ------------------------------------------------------------ company / departments / users
    co = Company(name="NovaTech Solutions", slug="novatech",
                 settings={"risk_model": {}, "fault_injection": {}, "scan_schedule": "daily",
                           "industry": "B2B SaaS", "hq": "Hyderabad, India"})
    db.add(co)
    db.flush()
    cid = co.id
    depts = {}
    for n in DEPARTMENTS:
        d = Department(company_id=cid, name=n)
        db.add(d)
        depts[n] = d
    db.flush()

    pw = hash_password(DEMO_PASSWORD)
    users: dict[str, User] = {}
    for email, name, role, dept, title in PERSONAS:
        u = User(company_id=cid, email=email, name=name, title=title, password_hash=pw, role_id=roles[role].id,
                 department_id=depts[dept].id, is_demo_persona=True)
        db.add(u)
        users[name] = u
    anita = User(company_id=cid, email="anita.desai@novatech.demo", name="Anita Desai", title="Senior IT Administrator",
                 role_id=roles["CONTROL_OWNER"].id, department_id=depts["IT"].id)
    db.add(anita)
    users["Anita Desai"] = anita
    by_dept: dict[str, list[User]] = defaultdict(list)
    used = {u.email for u in users.values()}
    titles = {"Engineering": "Software Engineer", "IT": "Systems Administrator", "Security": "Security Analyst",
              "HR": "HR Business Partner", "Finance": "Financial Analyst", "Legal": "Legal Counsel", "Sales": "Account Executive",
              "Marketing": "Marketing Specialist", "Operations": "Operations Manager", "Procurement": "Procurement Specialist",
              "Customer Success": "Customer Success Manager", "Executive": "Director"}
    i = 0
    while len(users) < 100:
        fn, ln = R.choice(FIRST), R.choice(LAST)
        email = f"{fn.lower()}.{ln.lower().replace(chr(39), '')}@novatech.demo"
        if email in used:
            continue
        used.add(email)
        dept = DEPARTMENTS[i % len(DEPARTMENTS)]
        i += 1
        role = "CONTROL_OWNER" if i % 4 == 0 else "EMPLOYEE"
        u = User(company_id=cid, email=email, name=f"{fn} {ln}", title=titles[dept], role_id=roles[role].id,
                 department_id=depts[dept].id)
        db.add(u)
        users[u.name] = u
    db.flush()
    for u in users.values():
        dn = next(k for k, v in depts.items() if v.id == u.department_id)
        by_dept[dn].append(u)
    priya, arjun, kavya, rahul, vikram = (users[n] for n in ("Priya Raman", "Arjun Mehta", "Kavya Nair", "Rahul Verma", "Vikram Sethi"))

    # ------------------------------------------------------------ frameworks / requirements
    fws: dict[str, Framework] = {}
    for code, (name, ver) in FRAMEWORKS.items():
        f = Framework(company_id=cid, code=code, name=name, version=ver, is_demo_mapping=True,
                      description="Prototype / Demonstration Mapping — synthetic requirement wording, not the official standard text.")
        db.add(f)
        fws[code] = f
    db.flush()

    ctrls: dict[int, Control] = {}
    for n, (name, domain, dept, freq, crit, auto) in CONTROLS.items():
        c = Control(company_id=cid, code=f"C-{n:03d}", name=name, domain=domain, department_id=depts[dept].id,
                    frequency_days=freq, criticality=crit, automation=auto,
                    description=f"{name}: performed by {dept} every {freq} days and evidenced in the control register.",
                    test_procedure=["Was the control performed?", "Was it performed within the required frequency?",
                                    "Is complete evidence available?", "Was the result reviewed and approved?"])
        if n == 17:
            c.description = "Managers review all user access to production and business-critical systems every 90 days; inactive accounts are disabled."
            c.test_procedure = ["Was the review performed?", "Was it performed within required frequency?", "Were all users included?",
                                "Were privileged users reviewed?", "Were terminated users removed?", "Was the review approved?",
                                "Is evidence available?"]
        db.add(c)
        ctrls[n] = c
    db.flush()

    reqs: dict[str, Requirement] = {}
    for fw_code, items in REQUIREMENTS.items():
        for code, title, cat, cnums in items:
            created = day(-60) if code == "ISO-8.11" else day(-900)
            r = Requirement(company_id=cid, framework_id=fws[fw_code].id, code=code, title=title,
                            description=f"{title}. (Synthetic demonstration wording for {FRAMEWORKS[fw_code][0]}.)",
                            category=cat, current_version="1.0", effective_date=(day(-900)).date(), status="active",
                            created_at=created, updated_at=created)
            db.add(r)
            db.flush()
            reqs[code] = r
            db.add(RequirementVersion(company_id=cid, requirement_id=r.id, version="1.0", description=r.description,
                                      change_summary="Initial version", effective_date=r.effective_date))
            for cn in cnums:
                db.add(RequirementControlMap(company_id=cid, requirement_id=r.id, control_id=ctrls[cn].id))
    # requirement changes
    iso533_eff = day(-45)
    r = reqs["ISO-5.33"]
    r.status, r.current_version = "changed", "2.0"
    db.add(RequirementVersion(company_id=cid, requirement_id=r.id, version="2.0", effective_date=iso533_eff.date(),
                              description="Records retention schedules are reviewed at least every 90 days and disposal is evidenced quarterly.",
                              change_summary="Review interval tightened from annual to 90 days; quarterly disposal evidence required.",
                              parameters={"max_interval_days": 90}))
    r = reqs["ISO-5.18"]
    r.current_version = "1.1"
    db.add(RequirementVersion(company_id=cid, requirement_id=r.id, version="1.1", effective_date=day(-200).date(),
                              description="Access rights, including privileged and service accounts, are reviewed at least quarterly.",
                              change_summary="Clarified that privileged and service accounts are in scope of periodic reviews.",
                              parameters={"max_interval_days": 90}))
    r = reqs["DPDP-07"]
    db.add(RequirementVersion(company_id=cid, requirement_id=r.id, version="1.1", effective_date=day(40).date(),
                              description="Breaches are intimated to the authority and affected principals within the defined window.",
                              change_summary="Adds a defined notification timeline and content template.", parameters={}))
    db.flush()

    # ------------------------------------------------------------ owners
    fixed_owner = {17: rahul, 11: rahul, 12: rahul, 19: rahul, 76: rahul, 18: kavya, 14: kavya, 21: kavya, 29: kavya,
                   61: kavya, 69: priya, 66: priya}
    owner_of: dict[int, User] = {}
    for n, c in ctrls.items():
        dn = CONTROLS[n][2]
        u = fixed_owner.get(n) or R.choice([x for x in by_dept[dn] if not x.is_demo_persona] or by_dept[dn])
        owner_of[n] = u
        if n == 17:
            db.add(ControlOwner(company_id=cid, control_id=c.id, user_id=anita.id, assigned_at=day(-700), unassigned_at=day(-180)))
            db.add(ControlOwner(company_id=cid, control_id=c.id, user_id=rahul.id, assigned_at=day(-180)))
        else:
            db.add(ControlOwner(company_id=cid, control_id=c.id, user_id=u.id, assigned_at=day(-700)))

    # ------------------------------------------------------------ audits
    def mk_audit(code, name, fw, typ, start, status, auditor, outcome=None, summary=""):
        a = Audit(company_id=cid, code=code, name=name, framework_id=fws[fw].id, audit_type=typ, status=status,
                  start_date=day(start).date(), end_date=day(start + 5).date(), auditor=auditor, outcome=outcome,
                  summary=summary)
        db.add(a)
        db.flush()
        return a
    A = {
        "SOC24": mk_audit("AUD-SOC-FY24", "SOC 2-style Type II Examination FY24", "SOC2", "external", -735, "completed", "Meridian Assurance LLP", "Completed — qualified opinion avoided; 8 exceptions"),
        "SOC25": mk_audit("AUD-SOC-FY25", "SOC 2-style Type II Examination FY25", "SOC2", "external", -405, "completed", "Meridian Assurance LLP", "Completed — 10 exceptions"),
        "ISO25": mk_audit("AUD-ISO-2025", "ISO 27001-style Certification Audit 2025", "ISO27001", "external", -327, "completed", "Northbridge Certification", "Completed — 9 nonconformities (minor)"),
        "Q1": mk_audit("AUD-INT-2026Q1", "Q1 2026 Internal Control Review", "ISO27001", "internal", -241, "completed", "Arjun Mehta (Internal Audit)", "Completed — 8 findings"),
        "Q2": mk_audit("AUD-INT-2026Q2", "Q2 2026 Internal Control Review", "ISO27001", "internal", -151, "completed", "Arjun Mehta (Internal Audit)", "Completed — 7 findings"),
        "PEN": mk_audit("AUD-PEN-2026", "Independent Penetration Test 2026", "NIST_CSF", "external", -95, "completed", "RedLattice Security", "Completed — 4 findings"),
        "DPDP": mk_audit("AUD-DPDP-2026", "DPDP-style Privacy Readiness Review", "DPDP", "internal", -65, "completed", "Priya Raman (Compliance)", "Completed — 4 findings"),
        "ISO26": mk_audit("AUD-ISO-2026-S", "ISO 27001-style Surveillance Audit 2026", "ISO27001", "surveillance", 17, "planned", "Northbridge Certification",
                          summary="Annual surveillance audit of the ISMS. Fieldwork 2 days."),
        "SOC26": mk_audit("AUD-SOC-FY26", "SOC 2-style Type II Examination FY26", "SOC2", "external", 75, "planned", "Meridian Assurance LLP"),
    }
    fw_of_audit = {"SOC24": "SOC2", "SOC25": "SOC2", "ISO25": "ISO27001", "Q1": "ISO27001", "Q2": "ISO27001",
                   "PEN": "NIST_CSF", "DPDP": "DPDP", "ISO26": "ISO27001", "SOC26": "SOC2"}
    req_ctrls: dict[str, set[int]] = defaultdict(set)
    for fw_code, items in REQUIREMENTS.items():
        for code, _, _, cnums in items:
            req_ctrls[fw_code].update(cnums)
    for key, a in A.items():
        fw = fw_of_audit[key]
        for code, _, _, _ in REQUIREMENTS[fw]:
            db.add(AuditScope(company_id=cid, audit_id=a.id, requirement_id=reqs[code].id))
        for cn in sorted(req_ctrls[fw]):
            db.add(AuditScope(company_id=cid, audit_id=a.id, control_id=ctrls[cn].id))
    db.flush()

    # ------------------------------------------------------------ historical findings (generic controls)
    SPECIAL = {9, 17, 18, 24, 31, 42, 55, 63}
    plan_counter: dict[int, int] = defaultdict(int)
    ver_counter: dict[int, int] = defaultdict(int)
    apr_counter = [0]
    findings_all: list[Finding] = []
    fail_tests: dict[int, list[datetime]] = defaultdict(list)
    retests: dict[int, list[datetime]] = defaultdict(list)  # PASS re-test performed at closure
    memory: list[dict] = []
    events: list[dict] = []

    def code_for(counter, prefix, when: datetime):
        counter[when.year] += 1
        return f"{prefix}-{when.year}-{counter[when.year]:03d}"

    def history(f, event, frm, to, at, actor=None, actor_type="user", note=""):
        db.add(FindingHistory(company_id=cid, finding_id=f.id, event=event, from_status=frm, to_status=to,
                              actor_id=actor.id if actor else None, actor_type=actor_type, note=note, at=at, created_at=at))

    def remediation_history(f: Finding, closed: datetime, verifications: list[tuple[str, datetime]], late: bool,
                            titles: list[str] | None = None, summary: str = "", risky: bool = False):
        start = _aw(f.detected_at) + timedelta(days=2)
        plan = RemediationPlan(company_id=cid, code=code_for(plan_counter, "REM", start), finding_id=f.id,
                               title=f"Remediate {f.title.lower()}", status="COMPLETED", created_by=priya.id,
                               completed_at=closed, created_at=start, summary_of_actions=summary or "Corrective action implemented and evidenced.",
                               rationale="Restore effective operation of the control.")
        db.add(plan)
        db.flush()
        titles = titles or ["Confirm root cause with control owner", "Implement corrective action", "Collect evidence and re-test control"]
        span = (closed - start).days
        for s, t in enumerate(titles, start=1):
            due = (start + timedelta(days=max(5, int(span * s / len(titles) * (0.75 if late else 1.1))))).date()
            done = start + timedelta(days=max(3, int(span * s / len(titles))))
            task = RemediationTask(company_id=cid, plan_id=plan.id, seq=s, title=t, owner_id=owner_of[_num(f)].id,
                                   priority="HIGH" if f.severity in ("HIGH", "CRITICAL") else "MEDIUM", due_date=due,
                                   status="COMPLETED", depends_on_seq=s - 1 or None, evidence_required="Updated evidence",
                                   risk_level="HIGH" if (risky and s == 2) else "LOW", completed_at=done, created_at=start)
            db.add(task)
            db.flush()
            if risky and s == 2:
                apr_counter[0] += 1
                ap = ApprovalRequest(company_id=cid, code=f"APR-{start.year}-{apr_counter[0]:03d}", plan_id=plan.id, task_id=task.id,
                                     action_type="manual", title=t, reason=f"Remediation of {f.code}", risk_level="HIGH",
                                     affected={"control": f"C-{_num(f):03d}"}, evidence_refs=[], required_permission="APPROVAL_HIGH",
                                     status="EXECUTED", requested_by=owner_of[_num(f)].id, requested_by_agent=False,
                                     decided_by=priya.id, decided_at=done - timedelta(days=1), decision_note="Approved — change window confirmed.",
                                     created_at=done - timedelta(days=2))
                db.add(ap)
                db.flush()
                db.add(RemediationAction(company_id=cid, task_id=task.id, action_type="manual", connector="", executed_by=owner_of[_num(f)].id,
                                         executed_by_agent=False, executed_at=done, status="SUCCEEDED", approval_id=ap.id,
                                         result={"note": "Executed by owner"}, is_simulated=True))
        history(f, "remediation_plan_created", "OPEN", "IN_REMEDIATION", start, priya, note=plan.code)
        events.append(dict(t="remediation_started", title=f"Remediation started: {plan.code}", ent="remediation", code=plan.code, c=_num(f), at=start, actor=priya))
        for res, at in verifications:
            v = VerificationRecord(company_id=cid, code=code_for(ver_counter, "VER", at), plan_id=plan.id, finding_id=f.id,
                                   control_id=f.control_id, verified_at=at, result=res, verified_by_agent=False,
                                   checks=[{"name": "Control re-test", "expected": "PASS", "actual": "PASS" if res == "PASSED" else "EXCEPTIONS", "passed": res == "PASSED"}],
                                   notes="Re-performance by compliance team." if res == "PASSED" else "Evidence did not cover the full population.",
                                   created_at=at)
            db.add(v)
            db.flush()
            history(f, "verification_" + res.lower(), None, None, at, arjun, note=v.code)
            events.append(dict(t="verification_" + ("passed" if res == "PASSED" else "failed"),
                               title=f"Verification {res.lower()} for C-{_num(f):03d}", ent="verification", code=v.code, c=_num(f), at=at, actor=arjun))
            memory.append(dict(cat="VERIFICATION", c=_num(f), at=at, src=("verification", v.id, v.code), outcome=res, ver=res,
                               s=f"Verification {v.code} {res.lower()} for {f.code} ({f.title})."))
        memory.append(dict(cat="REMEDIATION", c=_num(f), at=closed, src=("remediation_plan", plan.id, plan.code), outcome="COMPLETED",
                           ver=verifications[-1][0] if verifications else None,
                           s=f"{plan.code}: {plan.summary_of_actions} Completed {closed.date().isoformat()}" + (" (late)." if late else ".")))
        return plan

    def _num(f: Finding) -> int:
        return next(n for n, c in ctrls.items() if c.id == f.control_id)

    def _aw(dt):
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    def new_finding(n: int, audit_key: str | None, kind: str, severity: str, detected: datetime, status: str,
                    title: str | None = None, desc: str | None = None, source="audit", root="", due_days=45) -> Finding:
        c = ctrls[n]
        t, dsc = KIND_TEMPLATES.get(kind, (title, desc))
        f = Finding(company_id=cid, code="PENDING", title=title or t.format(n=c.name), description=desc or dsc,
                    category=kind, control_id=c.id, audit_id=A[audit_key].id if audit_key else None, severity=severity,
                    status=status, owner_id=owner_of[n].id if n != 17 else rahul.id, detected_at=detected,
                    due_date=(detected + timedelta(days=due_days)).date(), source=source, root_cause=root, created_at=detected)
        reqc = next((code for fw, items in REQUIREMENTS.items() for code, _, _, cn in items if n in cn), None)
        if reqc:
            f.requirement_id = reqs[reqc].id
        db.add(f)
        db.flush()
        if audit_key:
            db.add(AuditFinding(company_id=cid, audit_id=A[audit_key].id, finding_id=f.id))
        history(f, "created", None, "OPEN", detected, arjun if source == "audit" else None,
                "user" if source == "audit" else "agent", note=f"Raised during {A[audit_key].name}" if audit_key else "Detected by continuous monitoring")
        events.append(dict(t="finding_created", title=f"Finding created: {f.title}", ent="finding", code=None, fid=f, c=n, at=detected,
                           actor=arjun if source == "audit" else None))
        findings_all.append(f)
        return f

    generic = [n for n in CONTROLS if n not in SPECIAL]
    R.shuffle(generic)
    pool = list(generic)
    plan_audits = [("SOC24", 8), ("SOC25", 10), ("ISO25", 7), ("Q1", 7), ("Q2", 7), ("PEN", 4), ("DPDP", 4)]
    sev_choices = ["LOW"] * 30 + ["MEDIUM"] * 45 + ["HIGH"] * 20 + ["CRITICAL"] * 5
    for key, count in plan_audits:
        fw = fw_of_audit[key]
        cands = [n for n in pool if n in req_ctrls[fw]] or pool
        a = A[key]
        det = datetime.combine(a.end_date, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=10)
        for n in cands[:count]:
            pool.remove(n)
            kind = R.choice(list(KIND_TEMPLATES))
            sev = R.choice(sev_choices)
            f = new_finding(n, key, kind, sev, det, "CLOSED", root=R.choice(ROOT_CAUSES))
            late = R.random() < 0.7
            closed = min(det + timedelta(days=R.randint(28, 70) if late else R.randint(18, 40)), day(-3))
            fail_tests[n].append(det - timedelta(days=2))
            retests[n].append(closed)
            vers = [("FAILED", closed - timedelta(days=9)), ("PASSED", closed)] if R.random() < 0.12 else [("PASSED", closed)]
            remediation_history(f, closed, vers, late, risky=(sev in ("HIGH", "CRITICAL") and R.random() < 0.5))
            f.closed_at = closed
            history(f, "closed", "READY_FOR_CLOSURE", "CLOSED", closed, priya, note="Closed after verification")
            events.append(dict(t="finding_closed", title=f"Finding closed: {f.title}", ent="finding", fid=f, c=n, at=closed, actor=priya))
            memory.append(dict(cat="AUDIT", c=n, at=det, src=("audit", a.id, a.name), outcome="Remediated", ver=vers[-1][0],
                               s=f"C-{n:03d} {ctrls[n].name} failed during {a.name}: {f.title}."))

    # ------------------------------------------------------------ scenario A: C-017 recurring access review
    c17 = ctrls[17]
    f1 = new_finding(17, "ISO25", "access_review_overdue", "HIGH", day(-322), "CLOSED",
                     title="Quarterly access review overdue", desc="User access review for production systems was not completed within 90 days; 9 inactive accounts found.",
                     root="Review depended on a single administrator; no reminder workflow.")
    remediation_history(f1, day(-290), [("PASSED", day(-290))], False,
                        titles=["Perform overdue access review", "Disable inactive accounts", "Add calendar reminder for quarterly review"],
                        summary="Overdue review performed, 9 inactive accounts disabled, calendar reminder added.")
    f1.closed_at = day(-290)
    history(f1, "closed", "READY_FOR_CLOSURE", "CLOSED", day(-290), priya)
    f2 = new_finding(17, "Q1", "access_review_overdue", "HIGH", day(-236), "CLOSED",
                     title="Quarterly access review overdue", desc="Q4 2025 review not evidenced; review record missing privileged accounts.",
                     root="Ownership transition; review template did not include privileged accounts.")
    remediation_history(f2, day(-142), [("FAILED", day(-205)), ("PASSED", day(-142))], True,
                        titles=["Update access review process and template", "Perform review including privileged accounts",
                                "Collect evidence and re-test control"],
                        summary="Access review process updated (template now includes privileged accounts); review performed.")
    f2.closed_at = day(-142)
    history(f2, "closed", "READY_FOR_CLOSURE", "CLOSED", day(-142), priya)
    f3 = new_finding(17, None, "access_review_overdue", "HIGH", day(-40), "OPEN", source="agent",
                     title="Quarterly access review overdue",
                     desc="Continuous monitoring: the quarterly user access review is overdue (last performed 142 days ago; required every 90 days) and its evidence has expired.")
    fail_tests[17] += [day(-330), day(-236)]

    # scenario B: vendor assessment (missing evidence, recurring)
    v1 = new_finding(31, "ISO25", "vendor_assessment_missing", "MEDIUM", day(-322), "CLOSED",
                     title="Vendor security assessments missing for critical vendors",
                     desc="2 Tier-1 vendors had no current security assessment.", root="Assessment tracker maintained manually.")
    remediation_history(v1, day(-280), [("PASSED", day(-280))], False,
                        titles=["Collect vendor questionnaires", "Review assessments and record risk"],
                        summary="Questionnaires collected for both vendors; risk recorded.")
    v1.closed_at = day(-280)
    history(v1, "closed", "READY_FOR_CLOSURE", "CLOSED", day(-280), priya)
    fail_tests[31].append(day(-330))
    fb = new_finding(31, None, "vendor_assessment_missing", "MEDIUM", day(-60), "OPEN", source="agent",
                     title="Vendor security assessments missing for critical vendors",
                     desc="No current assessment evidence is on file for 3 Tier-1 vendors (Payroll processor, Cloud email, Support desk).")

    # scenario D: data retention — changed requirement
    fd = new_finding(55, None, "retention_misaligned", "HIGH", day(-30), "IN_REMEDIATION", source="agent",
                     title="Retention schedule not aligned with updated requirement",
                     desc="ISO-5.33 v2.0 requires 90-day retention schedule reviews; control runs every 180 days and evidence expired.")
    # scenario E: privileged access (critical, requires approval)
    fe = new_finding(18, None, "privileged_access_review_failed", "CRITICAL", day(-20), "IN_REMEDIATION", source="control_test",
                     title="Privileged accounts without approval ticket",
                     desc="4 privileged accounts in the PAM export have no approval ticket; PAM export conflicts with the HR roster.")
    # others
    fbk = new_finding(24, None, "control_failure", "CRITICAL", day(-25), "IN_REMEDIATION", source="control_test",
                      title="Backup restoration exceeded RTO", desc="2 of 5 restores failed; finance database restore exceeded the 4-hour RTO.")
    ft = new_finding(63, None, "partial_implementation", "MEDIUM", day(-30), "IN_REMEDIATION", source="control_test",
                     title="Security awareness completion below target", desc="82% completion against a 95% target.")
    fk = new_finding(9, None, "test_overdue", "LOW", day(-8), "OPEN", source="agent",
                     title="Encryption key rotation not performed within 90 days", desc="Last rotation evidenced 100 days ago.")

    # codes: audit findings AUD-YYYY-NNN by date, agent findings FND-YYYY-NNN
    per_year: dict[int, int] = defaultdict(int)
    for f in sorted([f for f in findings_all if f.audit_id], key=lambda f: _aw(f.detected_at)):
        per_year[_aw(f.detected_at).year] += 1
        f.code = f"AUD-{_aw(f.detected_at).year}-{per_year[_aw(f.detected_at).year]:03d}"
    holder = next((f for f in findings_all if f.code == "AUD-2026-017"), None)
    if holder and holder is not f2:
        holder.code, f2.code = f2.code, "AUD-2026-017"
    elif holder is None:
        f2.code = "AUD-2026-017"
    for f, code in [(fb, "FND-2026-038"), (fk, "FND-2026-040"), (f3, "FND-2026-041"), (fd, "FND-2026-042"),
                    (ft, "FND-2026-043"), (fe, "FND-2026-044"), (fbk, "FND-2026-045")]:
        f.code = code
    f3.previous_finding_id = f2.id
    f2.previous_finding_id = f1.id
    fb.previous_finding_id = v1.id
    db.flush()

    # open remediation plans (existing) with overdue tasks and pending approvals
    def open_plan(f: Finding, n: int, title: str, tasks: list[tuple], start: datetime, approval: tuple | None = None):
        plan = RemediationPlan(company_id=cid, code=code_for(plan_counter, "REM", start), finding_id=f.id, title=title,
                               status="PENDING_APPROVAL" if approval else "IN_PROGRESS", created_by=priya.id, created_at=start,
                               rationale="Restore effective operation of the control.")
        db.add(plan)
        db.flush()
        for s, (t, st, due_off, risk, done_off) in enumerate(tasks, start=1):
            task = RemediationTask(company_id=cid, plan_id=plan.id, seq=s, title=t, owner_id=owner_of[n].id,
                                   priority="HIGH", due_date=day(due_off).date(), status=st, depends_on_seq=s - 1 or None,
                                   evidence_required="Updated evidence", risk_level=risk,
                                   completed_at=day(done_off) if done_off is not None else None, created_at=start)
            db.add(task)
            db.flush()
            if approval and st == "AWAITING_APPROVAL":
                apr_counter[0] += 1
                db.add(ApprovalRequest(company_id=cid, code=f"APR-2026-{apr_counter[0]:03d}", plan_id=plan.id, task_id=task.id,
                                       action_type="manual", title=t, reason=approval[0], risk_level=risk,
                                       affected=approval[1], evidence_refs=approval[2],
                                       required_permission="APPROVAL_CRITICAL" if risk == "CRITICAL" else "APPROVAL_HIGH",
                                       status="PENDING", requested_by=owner_of[n].id, requested_by_agent=False,
                                       created_at=day(-3)))
        history(f, "remediation_plan_created", "OPEN", "IN_REMEDIATION", start, priya, note=plan.code)
        return plan

    open_plan(fe, 18, "Revoke unapproved privileged access and reconcile PAM with HR roster",
              [("Reconcile PAM export with HR roster", "COMPLETED", -15, "LOW", -16),
               ("Revoke 4 unapproved privileged accounts (manual — PAM)", "AWAITING_APPROVAL", -5, "CRITICAL", None),
               ("Re-perform privileged access review", "PENDING", 10, "LOW", None)], day(-18),
              ("Remediation of FND-2026-044 (privileged accounts without approval)", {"accounts": 4, "control": "C-018"}, ["EV-PAM"]))
    open_plan(fbk, 24, "Remediate backup restore failures and re-test",
              [("Move finance DB backups to faster storage tier", "COMPLETED", -12, "LOW", -13),
               ("Approve emergency restore test window in production", "AWAITING_APPROVAL", -4, "HIGH", None),
               ("Re-run restoration test for 5 systems", "PENDING", 7, "LOW", None)], day(-22),
              ("Remediation of FND-2026-045 (backup restoration)", {"systems": 5, "control": "C-024"}, []))
    open_plan(ft, 63, "Raise awareness training completion to target",
              [("Send reminders to non-completers", "COMPLETED", -20, "LOW", -18),
               ("Escalate to Sales and Customer Success leadership", "IN_PROGRESS", -6, "LOW", None),
               ("Collect updated completion report", "PENDING", 20, "LOW", None)], day(-28))
    open_plan(fd, 55, "Align retention schedule review with ISO-5.33 v2.0",
              [("Update Data Retention & Disposal Policy to 90-day review", "IN_PROGRESS", -3, "LOW", None),
               ("Change control frequency to 90 days", "PENDING", 14, "MEDIUM", None)], day(-26))
    db.flush()

    # ------------------------------------------------------------ control tests
    tests: list[ControlTest] = []

    def add_test(n, at, result, tester=None, audit_key=None, notes=""):
        t = ControlTest(company_id=cid, code="CT-TMP", control_id=ctrls[n].id, tested_at=at, result=result,
                        tester_id=(tester or owner_of[n]).id, tester_type="auditor" if audit_key else "user",
                        audit_id=A[audit_key].id if audit_key else None, method="inspection" if CONTROLS[n][5] == "manual" else "automated check",
                        questions=[{"question": q, "answer": "Yes" if result == "PASS" else ("Partially" if result == "PARTIAL" else "No")}
                                   for q in ctrls[n].test_procedure], notes=notes, created_at=at)
        db.add(t)
        tests.append(t)
        return t

    special_tests = {
        17: [(-600, "PASS"), (-510, "PASS"), (-420, "PASS"), (-330, "FAIL"), (-290, "PASS"), (-236, "FAIL"), (-142, "PASS")],
        18: [(-470, "PASS"), (-380, "PASS"), (-290, "PASS"), (-200, "PASS"), (-110, "PASS"), (-20, "FAIL")],
        24: [(-475, "PASS"), (-385, "PASS"), (-295, "PASS"), (-205, "PASS"), (-115, "PASS"), (-25, "FAIL")],
        31: [(-640, "PASS"), (-460, "PASS"), (-330, "FAIL"), (-280, "PASS"), (-100, "PASS")],
        42: [(-580, "PASS"), (-400, "PASS"), (-220, "PASS"), (-40, "PASS")],
        55: [(-660, "PASS"), (-480, "PASS"), (-300, "PASS"), (-120, "PASS")],
        63: [(-760, "PASS"), (-395, "PASS"), (-30, "PARTIAL")],
        9: [(-460, "PASS"), (-370, "PASS"), (-280, "PASS"), (-190, "PASS"), (-100, "PASS")],
    }
    last_test: dict[int, datetime] = {}
    for n in CONTROLS:
        if n in special_tests:
            for off, res in special_tests[n]:
                add_test(n, day(off), res, tester=rahul if n == 17 and off > -180 else (anita if n == 17 else None),
                         notes="Tested during audit fieldwork" if res == "FAIL" else "")
            last_test[n] = day(special_tests[n][-1][0])
            continue
        freq = CONTROLS[n][3]
        cur = day(-R.randint(3, max(4, int(freq * 0.7))))
        if retests.get(n) and max(retests[n]) > cur:
            cur = max(retests[n])  # the closure re-test is the most recent test
        last_test[n] = cur
        at = cur
        while (NOW - at).days < 760:
            add_test(n, at, "PASS")
            at = at - timedelta(days=int(freq * R.uniform(0.9, 1.05)))
        for fdt in fail_tests.get(n, []):
            add_test(n, fdt, "FAIL", tester=arjun, notes="Exception noted during audit fieldwork")
        for rdt in retests.get(n, []):
            if rdt != cur:
                add_test(n, rdt, "PASS", notes="Re-test after remediation")
    tests.sort(key=lambda t: _aw(t.tested_at))
    for i2, t in enumerate(tests, start=1):
        t.code = f"CT-{i2:03d}"
    db.flush()

    # ------------------------------------------------------------ documents (real ingestion pipeline)
    key_dates = {"c017_last_review": day(-142), "iso533_effective": iso533_eff, "c042_last": day(-40),
                 "c024_test": day(-25), "c018_test": day(-20)}
    docs: dict[str, Document] = {}
    for fname, text, meta in demo_documents(NOW, key_dates):
        overrides = {k: v for k, v in meta.items() if k in ("document_type", "classification", "framework_code", "version")}
        res = ingest_document(db, company_id=cid, user_id=priya.id, filename=fname, data=text.encode(), overrides=overrides, source="seed")
        doc = db.get(Document, res["document"]["id"])
        doc.required_permission = meta.get("required_permission")
        doc.effective_date = day(-142).date() if "Q2 2026" in fname else day(-120).date()
        docs[fname] = doc
    db.flush()

    # ------------------------------------------------------------ evidence
    ev_rows: list[Evidence] = []

    def add_ev(n, name, collected, valid_until, current=True, verification="verified", doc=None, page=None,
               conflicting=False, completeness=1.0, source="Control owner upload", extracted=None, code=None):
        e = Evidence(company_id=cid, code=code or "EV-TMP", name=name, control_id=ctrls[n].id, owner_id=owner_of[n].id,
                     source=source, collected_at=collected, valid_until=valid_until, verification_status=verification,
                     sha256=h(f"{n}{name}{collected}"), document_id=doc.id if doc else None, page=page,
                     is_conflicting=conflicting, is_current=current, completeness=completeness, extracted=extracted or {},
                     created_at=collected, description=f"Evidence supporting {ctrls[n].code} {ctrls[n].name}.")
        db.add(e)
        ev_rows.append(e)
        return e

    expiring = {14: 7, 21: 20, 27: 15, 47: 25, 61: 28}
    unverified = {4, 6, 12, 15, 20, 28, 35, 37, 50, 51, 57, 60}
    for n in CONTROLS:
        if n in SPECIAL:
            continue
        freq = CONTROLS[n][3]
        base = last_test[n]
        for k2, kind in enumerate(EVIDENCE_KINDS):
            vu = day(expiring[n]) if (n in expiring and k2 == 0) else day(R.randint(45, 220))
            add_ev(n, f"{ctrls[n].name} — {kind}", min(base - timedelta(days=k2), day(-1)), vu,
                   verification="unverified" if (n in unverified and k2 == 1) else "verified",
                   source=["Control owner upload", "Automated export", "Control owner upload"][k2])
        add_ev(n, f"{ctrls[n].name} — {EVIDENCE_KINDS[0]} (previous cycle)", base - timedelta(days=freq),
               base - timedelta(days=5), current=False)

    ar_doc = docs["Access Review Report - Q2 2026.txt"]
    add_ev(17, "Access Review Report — Q4 2025", day(-290), day(-200), current=False, source="IT Access Management",
           extracted={"inactive_accounts": 0, "users_reviewed": 198})
    add_ev(17, "Access Review Report — Q1 2026 (incomplete)", day(-205), day(-142), current=False, completeness=0.7,
           source="IT Access Management", extracted={"privileged_reviewed": False})
    add_ev(17, "Access Review Report — Q2 2026", day(-142), day(-52), doc=ar_doc, page=4, source="IT Access Management",
                   extracted={"users_reviewed": 214, "inactive_disabled": 12, "privileged_reviewed": 19}, code="EV-119")
    add_ev(18, "PAM Privileged Account Export — Sept 2026", day(-20), day(70), doc=docs["Privileged Access Review - Sept 2026.txt"],
           page=1, conflicting=True, source="PAM system export", code="EV-PAM")
    add_ev(18, "HR-approved Privileged Roster", day(-20), day(70), source="HR system export")
    add_ev(24, "Backup Restoration Test Report", day(-25), day(12), doc=docs["Backup Restoration Test Report.txt"], page=1)
    add_ev(31, "Vendor Assessment Pack — H2 2025", day(-280), day(-100), current=False)
    add_ev(42, "Incident Response Tabletop Exercise Report", day(-40), day(140), doc=docs["Incident Response Plan v3.1.txt"], page=2)
    add_ev(42, "Incident Response Plan v3.1 — approval record", day(-60), day(300))
    add_ev(55, "Retention Schedule Review Record", day(-200), day(-20), doc=docs["Data Retention and Disposal Policy v1.3.txt"], page=1)
    add_ev(63, "Security Awareness Training Completion Report 2026", day(-30), day(335),
           doc=docs["Security Awareness Training Report 2026.txt"], page=1, source="LMS export")
    add_ev(9, "Key Rotation Log", day(-100), day(60), doc=docs["Cryptography and Key Management Standard v1.5.txt"], page=1)
    ev_rows.sort(key=lambda e: _aw(e.collected_at))
    k3 = 0
    taken = {e.code for e in ev_rows if e.code not in ("EV-TMP", "EV-PAM")}
    for e in ev_rows:
        if e.code == "EV-TMP" or e.code == "EV-PAM":
            k3 += 1
            while f"EV-{k3:03d}" in taken:
                k3 += 1
            e.code = f"EV-{k3:03d}"
    db.flush()
    pam_code = next(e.code for e in ev_rows if e.name.startswith("PAM Privileged"))
    for ap in db.query(ApprovalRequest).filter(ApprovalRequest.company_id == cid, ApprovalRequest.status == "PENDING"):
        ap.evidence_refs = [pam_code] if "privileged" in ap.reason else []
    for e in ev_rows:
        db.add(EvidenceVersion(company_id=cid, evidence_id=e.id, version=1, collected_at=e.collected_at, sha256=e.sha256))
        events.append(dict(t="evidence_uploaded", title=f"Evidence uploaded: {e.name}", ent="evidence", code=e.code,
                           c=next(n for n, c in ctrls.items() if c.id == e.control_id), at=e.collected_at, actor=None))

    # ------------------------------------------------------------ policies
    for code, name, dept, ver, freq, cnums in POLICIES:
        reviewed = day(-250) if code == "POL-004" else day(-R.randint(30, 300))
        p = Policy(company_id=cid, code=code, name=name, department_id=depts[dept].id, owner_id=R.choice(by_dept[dept]).id,
                   current_version=ver, status="CHANGE_REQUIRED" if code == "POL-004" else "ACTIVE", review_frequency_days=freq,
                   last_reviewed_at=reviewed.date(), parameters={"control_codes": [f"C-{n:03d}" for n in cnums]})
        if code == "POL-002":
            p.owner_id = rahul.id
            p.parameters["access_review_interval_days"] = 90
            p.document_id = docs["Access Control Policy v2.4.txt"].id
        if code == "POL-004":
            p.parameters["retention_review_interval_days"] = 365
            p.document_id = docs["Data Retention and Disposal Policy v1.3.txt"].id
        db.add(p)
        db.flush()
        maj, mnr = ver.split(".")
        prev = f"{maj}.{int(mnr) - 1}" if int(mnr) > 0 else f"{int(maj) - 1}.9"
        db.add(PolicyVersion(company_id=cid, policy_id=p.id, version=prev, effective_date=(reviewed - timedelta(days=365)).date(),
                             summary=f"{name} v{prev}", change_summary="Previous approved version"))
        change = "Introduces stronger quarterly review requirements (privileged accounts in the same cycle; full population evidence)." \
            if code == "POL-002" else ("Pending update: ISO-5.33 v2.0 requires 90-day retention schedule reviews." if code == "POL-004"
                                       else "Annual review; wording clarified.")
        eff = day(-200) if code == "POL-002" else reviewed
        db.add(PolicyVersion(company_id=cid, policy_id=p.id, version=ver, effective_date=eff.date(), summary=f"{name} v{ver}",
                             change_summary=change, parameters=p.parameters))
        memory.append(dict(cat="POLICY", c=None, subj=code, at=eff, src=("policy", p.id, f"{code} v{ver}"), outcome="ACTIVE" if code != "POL-004" else "CHANGE_REQUIRED",
                           s=f"{name} v{ver} effective {eff.date().isoformat()}: {change}"))
        events.append(dict(t="policy_updated", title=f"Policy updated: {name} v{ver}", ent="policy", code=code, c=None, at=eff, actor=priya))

    # ------------------------------------------------------------ regulatory changes
    for code, rq, title, ctype, old, new, eff, status, risk, action in [
        ("RC-001", "ISO-5.33", "Records retention review interval tightened", "UPDATED", "1.0", "2.0", -45, "IMPACT_ASSESSMENT_REQUIRED", "HIGH",
         "Update POL-004 and change C-055 frequency to 90 days; produce quarterly disposal evidence."),
        ("RC-002", "ISO-8.11", "New requirement: data masking in non-production", "NEW", None, "1.0", -60, "IMPACT_ASSESSMENT_REQUIRED", "MEDIUM",
         "Define and map a control for data masking in test environments."),
        ("RC-003", "ISO-5.18", "Privileged and service accounts in scope of access reviews", "UPDATED", "1.0", "1.1", -200, "IMPLEMENTED", "MEDIUM",
         "Access Control Policy v2.4 updated; review template includes privileged accounts."),
        ("RC-004", "DPDP-07", "Breach intimation timeline and template", "UPDATED", "1.0", "1.1", 40, "EFFECTIVE_SOON", "MEDIUM",
         "Update Breach Notification Procedure (C-044) before the effective date."),
        ("RC-005", "SOC-CC6.1", "MFA for all administrative interfaces", "UPDATED", "1.0", "1.1", 75, "UNDER_REVIEW", "LOW",
         "Confirm C-014 coverage includes all admin consoles."),
    ]:
        db.add(RegulatoryChange(company_id=cid, code=code, requirement_id=reqs[rq].id, title=title, change_type=ctype,
                                old_version=old, new_version=new, summary=title + ".", effective_date=day(eff).date(),
                                status=status, risk=risk, action_required=action))
        memory.append(dict(cat="REGULATORY", c=None, subj=rq, at=day(min(eff, 0)), src=("regulatory_change", None, code),
                           outcome=status, s=f"{rq} {ctype.lower()} to v{new} ({'effective ' + day(eff).date().isoformat()}): {title}."))
        events.append(dict(t="requirement_updated", title=f"Requirement {ctype.lower()}: {rq} v{new}", ent="requirement", code=rq, c=None,
                           at=day(min(eff, 0)), actor=None))

    # ------------------------------------------------------------ IAM demo connector data
    systems = ["Workspace SSO", "AWS Console", "GitHub", "Salesforce", "NetSuite", "Jira"]
    emp = [u for u in users.values()]
    for k4 in range(120):
        u = emp[k4 % len(emp)]
        sysname = systems[k4 % len(systems)]
        acct = IamAccount(company_id=cid, username=f"{u.email.split('@')[0]}@{sysname.split()[0].lower()}", display_name=u.name,
                          department=next(k for k, v in depts.items() if v.id == u.department_id), system=sysname,
                          is_privileged=(k4 % 9 == 0), last_login_at=day(-R.randint(0, 60)), status="ACTIVE")
        if k4 < 12:
            acct.last_login_at = day(-R.randint(95, 300))
            acct.is_privileged = k4 in (3, 7)
        elif k4 < 17:
            acct.employment_status = "TERMINATED"
            acct.last_login_at = day(-R.randint(10, 60))
        elif k4 < 25:
            acct.status, acct.disabled_at, acct.last_login_at = "DISABLED", day(-R.randint(150, 400)), day(-R.randint(200, 500))
        db.add(acct)

    # ------------------------------------------------------------ memory: behaviour + control + evidence
    memory += [
        dict(cat="CONTROL", c=17, at=day(-180), src=("control_owner", None, "Ownership change"), outcome="OWNER_CHANGED",
             s="C-017 ownership moved from Anita Desai to Rahul Verma after the IT restructure."),
        dict(cat="BEHAVIOR", c=17, at=day(-236), src=("pattern", None, "Recurring finding detector"), outcome="RECURRING_PATTERN",
             s="C-017 access review overdue for the second time (AUD-ISO-2025, Q1 2026 review). Previous fix (calendar reminder) did not prevent recurrence."),
        dict(cat="BEHAVIOR", c=31, at=day(-60), src=("pattern", None, "Recurring finding detector"), outcome="RECURRING_PATTERN",
             s="C-031 vendor assessments missing again; tracker still maintained manually."),
        dict(cat="EVIDENCE", c=17, at=day(-52), src=("evidence", None, "EV-119"), outcome="EXPIRED",
             s="EV-119 Access Review Report — Q2 2026 expired (90-day validity)."),
        dict(cat="CONTROL", c=42, at=day(-40), src=("control_test", None, "Tabletop"), outcome="PASS", ver="PASSED",
             s="C-042 incident response tabletop (ransomware) passed; evidence valid."),
        dict(cat="CONTROL", c=18, at=day(-20), src=("control_test", None, "PAM review"), outcome="FAIL",
             s="C-018 privileged access review failed: PAM export conflicts with HR roster (4 unapproved accounts)."),
        dict(cat="AUDIT", c=17, at=day(-40), src=("scan", None, "Scheduled compliance scan"), outcome="Open",
             s="Scheduled compliance scan raised FND-2026-041: C-017 overdue again (third occurrence)."),
    ]
    for n, f in [(17, f1), (17, f2), (31, v1)]:
        a = db.get(Audit, f.audit_id)
        memory.append(dict(cat="AUDIT", c=n, at=_aw(f.detected_at), src=("audit", a.id, a.name), outcome="Remediated", ver="PASSED",
                           s=f"C-{n:03d} {ctrls[n].name} failed during {a.name}: {f.title} ({f.code})."))
    for m in memory:
        n = m.get("c")
        db.add(MemoryRecord(company_id=cid, category=m["cat"], subject_type="control" if n else "other",
                            subject_id=ctrls[n].id if n else None, subject_code=f"C-{n:03d}" if n else m.get("subj"),
                            summary=m["s"], source_type=m["src"][0], source_id=m["src"][1], source_label=m["src"][2] or "",
                            occurred_at=m["at"], outcome=m.get("outcome"), verification=m.get("ver"), written_by="seed",
                            importance=5 if m["cat"] == "BEHAVIOR" else 3, created_at=m["at"]))

    # ------------------------------------------------------------ events + audit logs
    for t in tests:
        if (NOW - _aw(t.tested_at)).days <= 400:
            n = next(k for k, c in ctrls.items() if c.id == t.control_id)
            events.append(dict(t="control_tested", title=f"Control tested: {ctrls[n].code} {t.result}", ent="control_test", code=t.code,
                               c=n, at=_aw(t.tested_at), actor=owner_of[n]))
    for a in A.values():
        if a.status == "completed":
            events.append(dict(t="audit_completed", title=f"Audit completed: {a.name}", ent="audit", code=a.code, c=None,
                               at=datetime.combine(a.end_date, datetime.min.time(), tzinfo=timezone.utc), actor=arjun))
    for ev in events:
        f = ev.get("fid")
        n = ev.get("c")
        db.add(ComplianceEvent(company_id=cid, event_type=ev["t"], title=ev["title"], entity_type=ev["ent"],
                               entity_code=f.code if f else ev.get("code"), entity_id=f.id if f else None,
                               control_id=ctrls[n].id if n else None, occurred_at=ev["at"],
                               actor_id=ev["actor"].id if ev.get("actor") else None,
                               actor_type="user" if ev.get("actor") else "system", created_at=ev["at"]))
        actor = ev.get("actor")
        db.add(AuditLog(company_id=cid, user_id=actor.id if actor else None, actor_type="user" if actor else "system",
                        actor_label=actor.name if actor else "Compliance Agent (scheduled scan)",
                        role=next((r.code for r in roles.values() if actor and r.id == actor.role_id), None),
                        action=ev["title"], resource=f.code if f else ev.get("code"), resource_type=ev["ent"],
                        risk_level="MEDIUM" if ev["t"].startswith("finding") else "LOW", authorization_result="ALLOWED",
                        result="RECORDED", created_at=ev["at"]))
    for k5 in range(60):
        u = R.choice([priya, arjun, kavya, rahul, vikram])
        db.add(AuditLog(company_id=cid, user_id=u.id, actor_type="user", actor_label=u.name,
                        role=next(r.code for r in roles.values() if r.id == u.role_id), action="Signed in (Demo SAML SSO)",
                        resource="session", resource_type="auth", risk_level="LOW", result="SUCCESS",
                        created_at=day(-R.randint(1, 120)) + timedelta(hours=R.randint(8, 19))))

    # ------------------------------------------------------------ security events
    sneha = users["Sneha Iyer"]
    kinds = [("permission_denied", "LOW", "Access denied to /api/findings (missing FINDINGS_READ)"),
             ("failed_login", "LOW", "Failed sign-in attempt"),
             ("dlp_redaction", "LOW", "Sensitive value redacted from agent output"),
             ("bulk_document_access", "MEDIUM", "12 confidential documents opened within 10 minutes"),
             ("tool_denied", "MEDIUM", "Agent tool create_remediation_task denied for Employee role")]
    for k6 in range(52):
        kind, sev, desc = kinds[k6 % len(kinds)]
        u = R.choice(list(users.values()))
        db.add(SecurityEvent(company_id=cid, user_id=u.id, event_type=kind, severity=sev, description=desc,
                             status="RESOLVED", details={"source": "Prototype Security Analytics"},
                             created_at=day(-R.randint(3, 200))))
    db.add(SecurityEvent(company_id=cid, user_id=sneha.id, event_type="repeated_denials", severity="HIGH", status="INVESTIGATING",
                         description="38 denied access attempts in 5 minutes", created_at=day(-1),
                         details={"pattern": "38 denied access attempts in 5 minutes", "label": "Prototype Security Analytics"}))
    db.add(SecurityEvent(company_id=cid, user_id=users["Anita Desai"].id, event_type="unusual_evidence_downloads", severity="MEDIUM",
                         status="OPEN", description="46 evidence files downloaded in 10 minutes", created_at=day(-2),
                         details={"label": "Prototype Security Analytics"}))
    db.add(SecurityEvent(company_id=cid, user_id=vikram.id, event_type="failed_authentication", severity="MEDIUM",
                         status="OPEN", description="9 failed sign-in attempts in 15 minutes", created_at=day(-1),
                         details={"label": "Prototype Security Analytics"}))

    # ------------------------------------------------------------ notifications
    for u, kind, title, sev, link, off in [
        (priya, "evidence", "Evidence expiring in 7 days: C-014 MFA Enforcement", "warning", "/evidence?status=EXPIRING", -1),
        (priya, "control", "Control test overdue: C-017 Quarterly User Access Review", "danger", f"/controls/{c17.id}", -2),
        (priya, "finding", "New high-risk finding: FND-2026-042 retention schedule", "danger", "/findings", -30),
        (priya, "remediation", "Remediation deadline passed: awareness escalation (C-063)", "warning", "/remediation", -5),
        (priya, "requirement", "Requirement changed: ISO-5.33 v2.0", "info", "/requirements", -45),
        (priya, "audit", "Audit approaching: ISO 27001-style Surveillance Audit in 17 days", "info", "/audits", 0),
        (priya, "approval", "2 approvals awaiting decision", "warning", "/remediation?tab=approvals", -3),
        (rahul, "evidence_request", "Evidence requested: C-017 Quarterly User Access Review", "warning", f"/controls/{c17.id}", -10),
        (kavya, "security", "Security alert: 38 denied access attempts in 5 minutes", "danger", "/security", -1),
        (vikram, "approval", "Critical approval pending: revoke 4 privileged accounts", "danger", "/remediation?tab=approvals", -3),
    ]:
        db.add(Notification(company_id=cid, user_id=u.id, kind=kind, title=title, severity=sev, link=link, created_at=day(off)))

    # ------------------------------------------------------------ integrations
    for c in CONNECTOR_CATALOG:
        db.add(Integration(company_id=cid, key=c["key"], name=c["name"], kind=c["kind"], status=c["status"],
                           last_sync_at=day(0) if c["status"] in ("DEMO", "CONNECTED") else None))

    # ------------------------------------------------------------ conversations (history)
    convo_templates = [
        ("Which controls are overdue for testing?", "C-017 Quarterly User Access Review and C-009 Encryption Key Rotation are overdue. C-017 is high risk because the finding has recurred."),
        ("What evidence is expiring this month?", "6 evidence items expire within 30 days, including the Backup Restoration Test Report (C-024) and MFA enforcement export (C-014)."),
        ("Summarise open findings for the executive review", "7 findings are open: 2 critical (C-018, C-024), 2 high (C-017, C-055), 2 medium and 1 low."),
        ("Was the vendor assessment finding present in the previous audit?", "Yes — AUD-ISO-2025 raised the same finding for C-031. It was remediated and verified, and has now recurred."),
        ("What does our access control policy say about inactive accounts?", "Access Control Policy v2.4 §4.3: accounts with no login for 90 days must be disabled unless an exception is documented."),
        ("What changed in ISO-5.33?", "ISO-5.33 v2.0 tightens the retention schedule review interval from annual to 90 days (Prototype / Demonstration Mapping)."),
    ]
    for k7 in range(18):
        u = [priya, arjun, rahul, vikram, kavya][k7 % 5]
        at = day(-R.randint(2, 150))
        conv = Conversation(company_id=cid, user_id=u.id, title=convo_templates[k7 % len(convo_templates)][0], created_at=at, updated_at=at)
        db.add(conv)
        db.flush()
        for j in range(3):
            q, a = convo_templates[(k7 + j) % len(convo_templates)]
            db.add(Message(company_id=cid, conversation_id=conv.id, role="user", content=q, created_at=at + timedelta(minutes=j * 3)))
            db.add(Message(company_id=cid, conversation_id=conv.id, role="assistant", content=a, cards=[],
                           created_at=at + timedelta(minutes=j * 3 + 1)))

    db.flush()
    # ------------------------------------------------------------ tenant B (isolation tests)
    cb = Company(name="Acme Bank (Tenant B)", slug="acme", settings={})
    db.add(cb)
    db.flush()
    db_dept = Department(company_id=cb.id, name="Executive")
    db.add(db_dept)
    db.flush()
    tom = User(company_id=cb.id, email="tom.baker@acme.demo", name="Tom Baker", title="Compliance Lead",
               password_hash=pw, role_id=roles["COMPLIANCE_OFFICER"].id, department_id=db_dept.id)
    db.add(tom)
    fwb = Framework(company_id=cb.id, code="ISO27001", name="ISO/IEC 27001-style Information Security Controls", version="2022-style")
    db.add(fwb)
    db.flush()
    cbc = Control(company_id=cb.id, code="C-001", name="Acme Access Review", domain="Access Control", frequency_days=90,
                  criticality=4, status="PASS")
    db.add(cbc)
    db.flush()
    db.add(Finding(company_id=cb.id, code="ACME-2026-001", title="Acme confidential finding", category="access_review_overdue",
                   control_id=cbc.id, severity="HIGH", status="OPEN", detected_at=day(-5), description="Tenant B data"))
    ingest_document(db, company_id=cb.id, user_id=None, filename="Acme Executive Compensation Report.txt",
                    data=b"Acme Bank Executive Compensation Report. Confidential. CEO base salary and bonus pool for FY26. "
                         b"Executive compensation access review policy.",
                    overrides={"document_type": "report", "classification": "confidential"}, source="seed")
    for c in CONNECTOR_CATALOG[:3]:
        db.add(Integration(company_id=cb.id, key=c["key"], name=c["name"], kind=c["kind"], status=c["status"]))
    db.flush()

    # ------------------------------------------------------------ readiness trend history (weekly posture snapshots)
    for k8, val in enumerate([84, 85, 84, 83, 83, 82, 81, 81, 80, 79, 79]):
        db.add(ComplianceEvent(company_id=cid, event_type="posture_snapshot", title="Weekly readiness snapshot",
                               entity_type="audit", entity_code="AUD-ISO-2026-S", occurred_at=day(-7 * (11 - k8)),
                               actor_type="system", data={"readiness": val}))

    # ------------------------------------------------------------ persist derived state + risk assessments
    snap = load_snapshot(db, cid)
    for cv in snap.controls.values():
        latest = cv.tests[0] if cv.tests else None
        cv.control.status = cv.status
        cv.control.last_tested_at = latest.tested_at if latest else None
        cv.control.last_result = latest.result if latest else None
        r = assess_control(cv, DEFAULT_RISK_CONFIG)
        db.add(RiskAssessment(company_id=cid, entity_type="control", entity_id=cv.control.id, score=r.score,
                              category=r.category, factors=r.factors, model_version=MODEL_VERSION, assessed_at=NOW))
    db.add(EvidenceRequest(company_id=cid, code=f"EVR-{NOW.year}-001", control_id=ctrls[31].id, requested_by=priya.id,
                           recipient_id=owner_of[31].id, evidence_required="Security questionnaires or SOC reports for 3 Tier-1 vendors",
                           reason="FND-2026-038: no current assessment evidence on file", due_date=day(5).date(), created_at=day(-9)))
    db.add(EvidenceRequest(company_id=cid, code=f"EVR-{NOW.year}-002", control_id=ctrls[17].id, requested_by=priya.id,
                           recipient_id=rahul.id, evidence_required="Current quarterly access review report (all users + privileged)",
                           reason="FND-2026-041: EV-119 expired; review overdue", due_date=day(-3).date(), created_at=day(-12)))
    co.settings = {**co.settings, "scan": {"frequency": "daily", "enabled": True}}
    db.commit()
    # this morning's scheduled scan — a real scan over the seeded state
    from app.services.scans import run_scan

    run_scan(db, cid, trigger="scheduled")
    return {"company_id": cid, "tenant_b_id": cb.id, "users": len(users), "controls": len(ctrls), "requirements": len(reqs),
            "evidence": len(ev_rows), "tests": len(tests), "findings": len(findings_all), "documents": len(docs)}
