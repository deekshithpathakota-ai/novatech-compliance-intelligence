"""P5: Scheduled compliance scans (background scheduler), proactive alerts and the Morning Compliance Brief."""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compliance.gaps import detect_gaps
from app.compliance.readiness import readiness
from app.compliance.recurring import detect_recurring
from app.compliance.snapshot import OPEN_FINDING_STATUSES, _aware, evidence_status, load_snapshot, next_upcoming_audit
from app.database.session import SessionLocal
from app.memory.service import remember
from app.models import (AgentRun, ApprovalRequest, Company, ComplianceEvent, Finding, FindingHistory, Notification, Role,
                        User)
from app.risk.engine import assess_control, merged_config

log = logging.getLogger("novatech.scans")
FREQUENCIES = {"daily": 1, "weekly": 7, "monthly": 30}
AUTO_FINDING = {"TEST_OVERDUE": ("test_overdue", "{name} not performed within required frequency"),
                "EVIDENCE_EXPIRED": ("evidence_expired", "{name} evidence expired"),
                "EVIDENCE_MISSING": ("evidence_missing", "{name} evidence missing"),
                "CONTROL_FAILURE": ("control_failure", "{name} operating exception")}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def get_schedule(company: Company) -> dict:
    s = dict((company.settings or {}).get("scan") or {})
    s.setdefault("frequency", "daily")
    s.setdefault("enabled", True)
    return s


def set_schedule(db: Session, company: Company, frequency: str | None = None, enabled: bool | None = None,
                 last_run_at: datetime | None = None) -> dict:
    s = get_schedule(company)
    if frequency:
        s["frequency"] = frequency
    if enabled is not None:
        s["enabled"] = enabled
    if last_run_at:
        s["last_run_at"] = last_run_at.isoformat()
    base = datetime.fromisoformat(s["last_run_at"]) if s.get("last_run_at") else now_utc()
    s["next_run_at"] = (base + timedelta(days=FREQUENCIES[s["frequency"]])).isoformat()
    company.settings = {**(company.settings or {}), "scan": s}
    db.flush()
    return s


def _officers(db: Session, company_id: int) -> list[User]:
    return db.execute(select(User).join(Role).where(User.company_id == company_id, Role.code == "COMPLIANCE_OFFICER",
                                                    User.is_active.is_(True))).scalars().all()


def _notify(db: Session, company_id: int, user_id: int | None, title: str, kind: str, severity: str, link: str | None) -> bool:
    """Create a Demo Notification unless the same alert was already sent in the last 24h."""
    dup = db.execute(select(Notification).where(Notification.company_id == company_id, Notification.user_id == user_id,
                                                Notification.title == title,
                                                Notification.created_at >= now_utc() - timedelta(hours=24))).scalars().first()
    if dup:
        return False
    db.add(Notification(company_id=company_id, user_id=user_id, kind=kind, title=title, severity=severity, link=link,
                        is_simulated_delivery=True))
    return True


def _next_finding_code(db: Session, company_id: int) -> str:
    year = now_utc().year
    codes = db.execute(select(Finding.code).where(Finding.company_id == company_id, Finding.code.like(f"FND-{year}-%"))).scalars().all()
    n = max([int(c.rsplit("-", 1)[1]) for c in codes if c.rsplit("-", 1)[1].isdigit()] or [0])
    return f"FND-{year}-{n + 1:03d}"


def run_scan(db: Session, company_id: int, trigger: str = "manual", requested_by: int | None = None) -> dict:
    from app.agents.orchestrator import RunCtx
    from app.auth.deps import principal_for_user

    officers = _officers(db, company_id)
    owner_user = db.get(User, requested_by) if requested_by else (officers[0] if officers else None)
    if owner_user is None:
        raise ValueError("No compliance officer to own the scan")
    principal = principal_for_user(db, owner_user)
    t0 = time.perf_counter()
    run = AgentRun(company_id=company_id, user_id=owner_user.id, objective=f"{trigger.title()} compliance scan",
                   intent="scheduled_scan", status="RUNNING", engine="deterministic", result={"trigger": trigger})
    db.add(run)
    db.commit()
    rc = RunCtx(db, principal, run)
    rc.delay = 0
    rc.emit("agent.started", f"Compliance scan started ({trigger})", "done", phase="UNDERSTAND")
    snap = load_snapshot(db, company_id)
    cfg = merged_config(db.get(Company, company_id).settings)
    now = snap.now
    alerts: list[dict] = []

    with rc.step("Checking evidence freshness", "ASSESS", "search_evidence") as h:
        exp_soon = [(cv, e) for cv in snap.controls.values() for e in cv.evidence
                    if evidence_status(e, now) == "EXPIRING" and (_aware(e.valid_until) - now).days <= 14]
        expired = [(cv, e) for cv in snap.controls.values() for e in cv.evidence if evidence_status(e, now) == "EXPIRED"]
        h["title"] = f"{len(exp_soon)} evidence items expire within 14 days · {len(expired)} expired"
        h["status"] = "warning" if exp_soon or expired else "done"
        for cv, e in exp_soon:
            alerts.append({"title": f"Evidence expiring in {(_aware(e.valid_until) - now).days} days: {cv.control.code} {e.name}",
                           "kind": "evidence", "severity": "warning", "link": f"/evidence?focus={e.id}", "owner": cv.owner_id})
    with rc.step("Checking overdue controls", "DETECT", "get_controls") as h:
        overdue = [cv for cv in snap.controls.values() if cv.status == "OVERDUE"]
        h["title"] = f"{len(overdue)} control tests overdue"
        h["status"] = "warning" if overdue else "done"
        for cv in overdue:
            alerts.append({"title": f"Control test overdue: {cv.control.code} {cv.control.name}", "kind": "control",
                           "severity": "danger", "link": f"/controls/{cv.control.id}", "owner": cv.owner_id})
    with rc.step("Checking unresolved findings", "DETECT", "get_findings") as h:
        open_f = [f for f in snap.findings if f.status in OPEN_FINDING_STATUSES]
        past_due = [f for f in open_f if f.due_date and f.due_date < now.date()]
        h["title"] = f"{len(open_f)} unresolved findings · {len(past_due)} past due"
        h["status"] = "warning" if past_due else "done"
    with rc.step("Checking remediation deadlines", "REMEDIATE", "get_remediation_status") as h:
        active = {p.id for p in snap.plans if p.status not in ("COMPLETED", "CANCELLED")}
        soon = [t for t in snap.tasks if t.plan_id in active and t.status not in ("COMPLETED", "CANCELLED") and t.due_date
                and t.due_date <= now.date() + timedelta(days=3)]
        h["title"] = f"{len(soon)} remediation tasks due within 3 days or overdue"
        h["status"] = "warning" if soon else "done"
        for t in soon:
            alerts.append({"title": f"Remediation deadline {'passed' if t.due_date < now.date() else 'approaching'}: {t.title}",
                           "kind": "remediation", "severity": "warning", "link": "/remediation", "owner": t.owner_id})
    created: list[str] = []
    with rc.step("Raising findings for new control gaps", "DETECT", "detect_compliance_gaps", "finding.detected") as h:
        gaps = detect_gaps(snap)
        for g in gaps["gaps"]:
            if g["type"] not in AUTO_FINDING or g["subject_type"] != "control":
                continue
            cv = snap.by_code(g["subject_code"])
            if cv is None or cv.active_findings or g["subject_code"] in created:
                continue
            cat, tmpl = AUTO_FINDING[g["type"]]
            risk = assess_control(cv, cfg)
            f = Finding(company_id=company_id, code=_next_finding_code(db, company_id), title=tmpl.format(name=cv.control.name),
                        description=f"Scheduled compliance scan: {g['message']}", category=cat, control_id=cv.control.id,
                        severity=risk.category if risk.category != "LOW" else "MEDIUM", status="OPEN", owner_id=cv.owner_id,
                        detected_at=now, due_date=(now + timedelta(days=30)).date(), source="agent")
            db.add(f)
            db.flush()
            db.add(FindingHistory(company_id=company_id, finding_id=f.id, event="created", to_status="OPEN", actor_type="agent",
                                  note="Detected by scheduled compliance scan", at=now))
            created.append(cv.control.code)
            alerts.append({"title": f"New {f.severity.lower()}-risk finding: {f.code} {f.title}", "kind": "finding",
                           "severity": "danger", "link": f"/findings/{f.id}", "owner": cv.owner_id})
        h["title"] = f"{len(created)} new finding(s) raised" if created else "No new control gaps without an open finding"
        h["status"] = "warning" if created else "done"
    sent = 0
    with rc.step("Generating alerts (Demo Notifications)", "REMEMBER", "send_notification") as h:
        for a in alerts:
            for uid in {o.id for o in officers} | ({a["owner"]} if a.get("owner") else set()):
                sent += _notify(db, company_id, uid, a["title"], a["kind"], a["severity"], a["link"])
        h["title"] = f"{len(alerts)} alerts · {sent} new notifications (duplicates within 24h suppressed)"
    audit = next_upcoming_audit(db, company_id)
    ready = readiness(load_snapshot(db, company_id, audit_id=audit.id if audit else None))["overall"]
    db.add(ComplianceEvent(company_id=company_id, event_type="posture_snapshot", title="Readiness snapshot (scan)",
                           entity_type="audit", entity_code=audit.code if audit else None, occurred_at=now,
                           actor_type="agent", data={"readiness": ready}))
    db.add(ComplianceEvent(company_id=company_id, event_type="compliance_scan", title=f"Compliance scan ({trigger}): {len(alerts)} alerts",
                           entity_type="scan", entity_code=f"RUN-{run.id}", occurred_at=now, actor_type="agent",
                           data={"alerts": len(alerts), "new_findings": created}))
    with rc.step("Updating compliance memory", "REMEMBER", "update_compliance_memory", "memory.updated") as h:
        remember(db, company_id=company_id, category="AUDIT", subject_type="scan", subject_code=audit.code if audit else None,
                 summary=f"{trigger.title()} compliance scan: {len(exp_soon)} evidence expiring, {len(overdue)} overdue tests, "
                         f"{len(past_due)} findings past due, {len(soon)} remediation deadlines, {len(created)} new findings. "
                         f"Readiness {ready}%.", source_type="agent_run", source_id=run.id, source_label=f"Scan run #{run.id}")
        h["title"] = "Scan result recorded in audit memory"
    set_schedule(db, db.get(Company, company_id), last_run_at=now)
    summary = {"trigger": trigger, "evidence_expiring": len(exp_soon), "evidence_expired": len(expired),
               "overdue_controls": len(overdue), "open_findings": len(open_f), "findings_past_due": len(past_due),
               "remediation_deadlines": len(soon), "new_findings": created, "alerts": len(alerts),
               "notifications_sent": sent, "readiness": ready}
    run.status, run.completed_at = "COMPLETED", now_utc()
    run.duration_ms = int((time.perf_counter() - t0) * 1000)
    run.result = {**(run.result or {}), "summary": summary,
                  "content": f"Scan complete: {len(alerts)} alerts, {len(created)} new findings, readiness {ready}%."}
    db.commit()
    rc.emit("agent.completed", "Scan complete", "done", phase="REMEMBER")
    return {"run_id": run.id, **summary}


def morning_brief(db: Session, principal) -> dict:
    snap = load_snapshot(db, principal.company_id)
    cfg = merged_config(db.get(Company, principal.company_id).settings)
    now = snap.now
    mine = principal.role_code in ("CONTROL_OWNER", "EMPLOYEE")
    cvs = [cv for cv in snap.controls.values() if not mine or cv.owner_id == principal.user_id]
    ids = {cv.control.id for cv in cvs}
    expiring = [(cv, e) for cv in cvs for e in cv.evidence if evidence_status(e, now) == "EXPIRING" and (_aware(e.valid_until) - now).days <= 14]
    overdue = [cv for cv in cvs if cv.status == "OVERDUE"]
    new_high = [f for f in snap.findings if f.control_id in ids and f.severity in ("HIGH", "CRITICAL")
                and f.status in ("OPEN", "IN_REMEDIATION") and _aware(f.detected_at) >= now - timedelta(days=30)]
    rec = [r for r in detect_recurring(snap) if r["control_id"] in ids]
    active = {p.id for p in snap.plans if p.status not in ("COMPLETED", "CANCELLED")}
    tasks = [t for t in snap.tasks if t.plan_id in active and t.status not in ("COMPLETED", "CANCELLED") and t.due_date
             and t.due_date <= now.date() + timedelta(days=7) and (not mine or t.owner_id == principal.user_id)]
    approvals = db.execute(select(ApprovalRequest).where(ApprovalRequest.company_id == principal.company_id,
                                                         ApprovalRequest.status == "PENDING")).scalars().all()
    my_approvals = [a for a in approvals if principal.has(a.required_permission)]
    ranked = sorted(cvs, key=lambda cv: (-(1 if any(r["control_id"] == cv.control.id for r in rec) else 0),
                                         -assess_control(cv, cfg).score))
    top = ranked[0] if ranked and assess_control(ranked[0], cfg).score >= 25 else None
    hour = datetime.now().hour
    items = [
        {"key": "evidence", "count": len(expiring), "label": "evidence items expiring soon", "link": "/evidence?status=EXPIRING"},
        {"key": "overdue", "count": len(overdue), "label": "overdue control tests", "link": "/controls?status=OVERDUE"},
        {"key": "new_high", "count": len(new_high), "label": "new high-risk findings (30 days)", "link": "/findings?severity=HIGH"},
        {"key": "recurring", "count": len(rec), "label": "recurring findings", "link": "/findings?recurring=yes"},
        {"key": "tasks", "count": len(tasks), "label": "remediation tasks approaching deadline", "link": "/remediation"},
        {"key": "approvals", "count": len(my_approvals), "label": "approvals waiting for you", "link": "/remediation?tab=approvals"},
    ]
    return {"greeting": f"Good {'morning' if hour < 12 else 'afternoon' if hour < 17 else 'evening'}, {principal.name.split()[0]}.",
            "scope": "your controls" if mine else "NovaTech",
            "items": items,
            "top_priority": {"code": top.control.code, "name": top.control.name, "id": top.control.id, "status": top.status,
                             "risk": assess_control(top, cfg).category,
                             "why": "Recurring finding and highest deterministic risk" if any(r["control_id"] == top.control.id for r in rec)
                             else "Highest deterministic risk"} if top else None,
            "generated_at": now.isoformat(), "label": "Proactive brief generated by the Compliance Agent from live state"}


# ------------------------------------------------------------------ background scheduler
_started = False


def _tick() -> None:
    db = SessionLocal()
    try:
        for c in db.execute(select(Company)).scalars().all():
            s = get_schedule(c)
            if not s.get("enabled") or not s.get("next_run_at"):
                continue
            if datetime.fromisoformat(s["next_run_at"]) <= now_utc() and _officers(db, c.id):
                log.info("running scheduled scan for company %s", c.id)
                run_scan(db, c.id, trigger="scheduled")
    except Exception:
        log.exception("scheduled scan tick failed")
        db.rollback()
    finally:
        db.close()


def start_scheduler(interval_s: int = 60) -> None:
    """Simple in-process scheduler (prototype). Production: a durable job queue / cron worker."""
    global _started
    if _started or os.environ.get("DISABLE_SCHEDULER") == "1":
        return
    _started = True

    def loop():
        while True:
            time.sleep(interval_s)
            _tick()

    threading.Thread(target=loop, daemon=True, name="compliance-scan-scheduler").start()
