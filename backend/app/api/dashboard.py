from collections import Counter, defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.common import iso, snap_and_cfg
from app.auth.deps import Principal, get_principal, require
from app.compliance.readiness import posture
from app.compliance.snapshot import OPEN_FINDING_STATUSES, _aware, evidence_freshness, next_upcoming_audit
from app.database.session import get_db
from app.models import ApprovalRequest, ComplianceEvent, Notification, SecurityEvent
from app.risk.engine import assess_control

router = APIRouter(prefix="/api", tags=["dashboard"])


def compute_dashboard(db: Session, p: Principal) -> dict:
    audit = next_upcoming_audit(db, p.company_id)
    scope_snap, cfg = snap_and_cfg(db, p.company_id, audit.id if audit else None)
    snap, _ = snap_and_cfg(db, p.company_id)
    scope = posture(scope_snap, cfg)
    org = posture(snap, cfg)
    risks = org.pop("_risks")
    org.pop("_gaps")
    recurring = org.pop("_recurring")
    for k in ("_risks", "_gaps", "_recurring"):
        scope.pop(k, None)
    now = snap.now

    # risk by framework
    by_fw: dict[str, Counter] = defaultdict(Counter)
    for cv in snap.controls.values():
        for fw in cv.framework_codes:
            by_fw[fw][risks[cv.control.id].category] += 1
    risk_by_framework = [{"framework": fw, **{k: c.get(k, 0) for k in ("LOW", "MEDIUM", "HIGH", "CRITICAL")}}
                         for fw, c in sorted(by_fw.items())]
    # finding trend: last 12 months opened vs closed
    months = []
    for i in range(11, -1, -1):
        m = (now.replace(day=1) - timedelta(days=30 * i)).strftime("%Y-%m")
        if m not in months:
            months.append(m)
    opened = Counter(_aware(f.detected_at).strftime("%Y-%m") for f in snap.findings)
    closed = Counter(_aware(f.closed_at).strftime("%Y-%m") for f in snap.findings if f.closed_at)
    finding_trend = [{"month": m, "opened": opened.get(m, 0), "closed": closed.get(m, 0)} for m in months[-12:]]
    # remediation progress
    today = now.date()
    active_ids = {pl.id for pl in snap.plans if pl.status not in ("COMPLETED", "CANCELLED")}
    tasks = [t for t in snap.tasks if t.plan_id in active_ids]
    rem = Counter()
    for t in tasks:
        if t.status == "COMPLETED":
            rem["Completed"] += 1
        elif t.due_date and t.due_date < today:
            rem["Overdue"] += 1
        elif t.status == "AWAITING_APPROVAL":
            rem["Awaiting approval"] += 1
        elif t.status == "IN_PROGRESS":
            rem["In progress"] += 1
        else:
            rem["Pending"] += 1
    fresh = Counter(evidence_freshness(e, now)["label"] for cv in snap.controls.values() for e in cv.evidence)
    trend_rows = db.execute(select(ComplianceEvent).where(ComplianceEvent.company_id == p.company_id,
                                                          ComplianceEvent.event_type == "posture_snapshot")
                            .order_by(ComplianceEvent.occurred_at)).scalars().all()
    readiness_trend = [{"date": _aware(e.occurred_at).date().isoformat(), "readiness": e.data.get("readiness")} for e in trend_rows][-11:]
    readiness_trend = [r for r in readiness_trend if r["date"] != today.isoformat()]
    readiness_trend.append({"date": today.isoformat(), "readiness": scope["readiness"]["overall"]})
    ind = scope["readiness"]["indicators"]
    unmapped = sum(1 for r in scope_snap.in_scope_requirements() if not scope_snap.req_to_controls.get(r.id))
    changed = sum(1 for r in scope_snap.in_scope_requirements() if r.status == "changed")
    req_risk = min(100, round((unmapped + changed) / max(scope["requirements_total"], 1) * 100 * 8))
    radar = [
        {"axis": "Controls", "risk": 100 - ind["controls"]["value"], "link": "/controls?status=attention"},
        {"axis": "Evidence", "risk": 100 - ind["evidence"]["value"], "link": "/evidence?status=EXPIRING"},
        {"axis": "Policies", "risk": 100 - ind["policy"]["value"], "link": "/policies"},
        {"axis": "Audits", "risk": 100 - ind["findings"]["value"], "link": "/findings"},
        {"axis": "Remediation", "risk": 100 - ind["remediation"]["value"], "link": "/remediation"},
        {"axis": "Requirements", "risk": req_risk, "link": "/requirements"},
    ]
    for r in radar:
        r["level"] = "CRITICAL" if r["risk"] >= 40 else "HIGH" if r["risk"] >= 25 else "MEDIUM" if r["risk"] >= 12 else "LOW"

    pending_approvals = db.execute(select(func.count(ApprovalRequest.id)).where(
        ApprovalRequest.company_id == p.company_id, ApprovalRequest.status == "PENDING")).scalar_one()
    recs = []
    if recurring:
        x = recurring[0]
        cv = snap.by_code(x["control_code"])
        recs.append({"title": f"{x['control_code']} {x['control_name']} is a recurring finding",
                     "detail": f"{x['occurrences']} occurrences since {x['first_detected']}; remediation effectiveness {x['effectiveness']['level']}.",
                     "severity": risks[cv.control.id].category,
                     "actions": [{"label": "Investigate", "kind": "agent", "prompt": f"Investigate {x['control_code']}",
                                  "intent": {"intent": "investigate_control", "control_code": x["control_code"]}},
                                 {"label": "Open control", "kind": "navigate", "to": f"/controls/{cv.control.id}"}]})
    crit = [t for t in org["top_risks"] if t["category"] == "CRITICAL"]
    if crit:
        recs.append({"title": f"{len(crit)} critical-risk controls", "detail": ", ".join(f"{t['code']} {t['name']}" for t in crit),
                     "severity": "CRITICAL", "actions": [{"label": "Review", "kind": "navigate", "to": "/controls?risk=CRITICAL"}]})
    if pending_approvals:
        recs.append({"title": f"{pending_approvals} approvals awaiting a decision", "detail": "Remediation is blocked until a permitted approver decides.",
                     "severity": "HIGH", "actions": [{"label": "Review approvals", "kind": "navigate", "to": "/remediation?tab=approvals"}]})
    if org["evidence_expiring"]:
        recs.append({"title": f"{org['evidence_expiring']} evidence items expire within 30 days",
                     "detail": ", ".join(f"{e['code']} ({e['days_left']}d)" for e in sorted(org["expiring_items"], key=lambda e: e["days_left"])[:4]),
                     "severity": "MEDIUM", "actions": [{"label": "Review evidence", "kind": "navigate", "to": "/evidence?status=EXPIRING"}]})
    changed_reqs = [r for r in snap.requirements.values() if r.status == "changed"]
    if changed_reqs:
        recs.append({"title": f"{len(changed_reqs)} requirement change needs impact assessment",
                     "detail": ", ".join(r.code for r in changed_reqs), "severity": "HIGH",
                     "actions": [{"label": "Regulatory changes", "kind": "navigate", "to": "/regulatory-changes"}]})
    timeline = db.execute(select(ComplianceEvent).where(ComplianceEvent.company_id == p.company_id,
                                                        ComplianceEvent.event_type != "posture_snapshot",
                                                        ComplianceEvent.event_type != "control_tested")
                          .order_by(ComplianceEvent.occurred_at.desc()).limit(12)).scalars().all()
    return {
        "user": p.name,
        "upcoming_audit": {"id": audit.id, "code": audit.code, "name": audit.name, "date": iso(audit.start_date),
                           "days": (audit.start_date - today).days, "framework": audit.framework.name,
                           "readiness": scope["readiness"]["overall"], "gaps": scope["gap_count"],
                           "critical": scope["critical_risks"]} if audit else None,
        "readiness": scope["readiness"],
        "metrics": {"readiness": scope["readiness"]["overall"], "critical_risks": org["critical_risks"],
                    "open_findings": org["open_findings"], "evidence_expiring": org["evidence_expiring"],
                    "overdue_controls": org["overdue_controls"], "controls_at_risk": org["controls_at_risk"],
                    "overdue_remediation": org["overdue_remediation"], "recurring_findings": org["recurring_findings"],
                    "high_risks": org["high_risks"], "controls_total": org["controls_total"]},
        "charts": {"risk_by_framework": risk_by_framework,
                   "control_health": [{"status": k, "count": v} for k, v in sorted(org["control_status_counts"].items())],
                   "finding_trend": finding_trend,
                   "remediation_progress": [{"state": k, "count": rem.get(k, 0)} for k in ("Completed", "In progress", "Awaiting approval", "Pending", "Overdue")],
                   "evidence_freshness": [{"label": k, "count": fresh.get(k, 0)} for k in ("FRESH", "AGING", "EXPIRING", "EXPIRED")],
                   "readiness_trend": readiness_trend},
        "radar": radar,
        "top_risks": org["top_risks"],
        "recommendations": recs,
        "timeline": [{"id": e.id, "type": e.event_type, "title": e.title, "at": iso(e.occurred_at), "entity": e.entity_code,
                      "control_id": e.control_id, "actor_type": e.actor_type} for e in timeline],
    }


@router.get("/dashboard")
def dashboard(p: Principal = Depends(require("DASHBOARD_READ")), db: Session = Depends(get_db)):
    return compute_dashboard(db, p)


@router.get("/nav-counts")
def nav_counts(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    snap, cfg = snap_and_cfg(db, p.company_id)
    open_f = sum(1 for f in snap.findings if f.status in OPEN_FINDING_STATUSES)
    expiring = sum(1 for cv in snap.controls.values() for e in cv.evidence
                   if 0 <= (_aware(e.valid_until) - snap.now).days <= 30)
    rem = sum(1 for pl in snap.plans if pl.status not in ("COMPLETED", "CANCELLED"))
    appr = sum(1 for a in snap.approvals if a.status == "PENDING")
    sec = db.execute(select(func.count(SecurityEvent.id)).where(SecurityEvent.company_id == p.company_id,
                                                                SecurityEvent.status.in_(["OPEN", "INVESTIGATING"]))).scalar_one()
    unread = db.execute(select(func.count(Notification.id)).where(Notification.company_id == p.company_id,
                                                                  Notification.user_id == p.user_id,
                                                                  Notification.is_read.is_(False))).scalar_one()
    controls_attention = sum(1 for cv in snap.controls.values() if assess_control(cv, cfg).category in ("HIGH", "CRITICAL"))
    return {"findings": open_f, "evidence": expiring, "remediation": rem, "approvals": appr, "security": sec,
            "notifications": unread, "controls": controls_attention}


@router.get("/notifications")
def notifications(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    rows = db.execute(select(Notification).where(Notification.company_id == p.company_id, Notification.user_id == p.user_id)
                      .order_by(Notification.created_at.desc()).limit(30)).scalars().all()
    return [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "severity": n.severity, "link": n.link,
             "is_read": n.is_read, "at": iso(n.created_at), "simulated_delivery": n.is_simulated_delivery} for n in rows]


@router.post("/notifications/{nid}/read")
def read_notification(nid: int, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    n = db.execute(select(Notification).where(Notification.id == nid, Notification.company_id == p.company_id,
                                              Notification.user_id == p.user_id)).scalar_one_or_none()
    if n:
        n.is_read = True
        db.commit()
    return {"ok": True}


@router.post("/notifications/read-all")
def read_all(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    for n in db.execute(select(Notification).where(Notification.company_id == p.company_id, Notification.user_id == p.user_id,
                                                   Notification.is_read.is_(False))).scalars():
        n.is_read = True
    db.commit()
    return {"ok": True}


@router.get("/timeline")
def timeline(control_id: int | None = None, limit: int = 60, p: Principal = Depends(require("DASHBOARD_READ")),
             db: Session = Depends(get_db)):
    q = select(ComplianceEvent).where(ComplianceEvent.company_id == p.company_id, ComplianceEvent.event_type != "posture_snapshot")
    if control_id:
        q = q.where(ComplianceEvent.control_id == control_id)
    rows = db.execute(q.order_by(ComplianceEvent.occurred_at.desc()).limit(min(limit, 300))).scalars().all()
    return [{"id": e.id, "type": e.event_type, "title": e.title, "at": iso(e.occurred_at), "entity": e.entity_code,
             "entity_type": e.entity_type, "control_id": e.control_id, "actor_type": e.actor_type} for e in rows]

