from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.common import iso, snap_and_cfg
from app.auth.deps import Principal, require
from app.compliance.readiness import posture, what_changed
from app.compliance.snapshot import OPEN_FINDING_STATUSES, evidence_status
from app.database.session import get_db
from app.memory.service import CATEGORIES, recall, serialize
from app.models import Audit, ComplianceEvent, MemoryRecord, Policy, PolicyVersion, RegulatoryChange, Report
from app.reports.builder import build_readiness_report, render_pdf
from app.schemas.serializers import control_row, finding_row
from app.services.audit import log_action
from app.services.tenancy import get_owned

router = APIRouter(prefix="/api", tags=["audits"])


@router.get("/audits")
def audits(p: Principal = Depends(require("AUDITS_READ")), db: Session = Depends(get_db)):
    rows = db.execute(select(Audit).where(Audit.company_id == p.company_id).order_by(Audit.start_date.desc())).scalars().all()
    snap_all, cfg = snap_and_cfg(db, p.company_id)
    out = []
    for a in rows:
        base = {"id": a.id, "code": a.code, "name": a.name, "framework": a.framework.name, "framework_code": a.framework.code,
                "type": a.audit_type, "status": a.status, "start_date": iso(a.start_date), "end_date": iso(a.end_date),
                "auditor": a.auditor, "outcome": a.outcome,
                "findings": sum(1 for f in snap_all.findings if f.audit_id == a.id)}
        if a.status != "completed":
            snap, _ = snap_and_cfg(db, p.company_id, a.id)
            po = posture(snap, cfg)
            ctrls = snap.in_scope_controls()
            covered = sum(1 for cv in ctrls if any(evidence_status(e, snap.now) in ("VALID", "EXPIRING") for e in cv.evidence))
            base.update({"readiness": po["readiness"]["overall"], "open_findings": po["open_findings"],
                         "critical_gaps": po["critical_risks"], "gaps": po["gap_count"], "controls": len(ctrls),
                         "evidence_coverage": round(covered / max(len(ctrls), 1) * 100),
                         "risk": "HIGH" if po["critical_risks"] else "MEDIUM",
                         "days_until": (a.start_date - snap.now.date()).days})
        out.append(base)
    return out


@router.get("/audits/{aid}")
def audit_detail(aid: int, p: Principal = Depends(require("AUDITS_READ")), db: Session = Depends(get_db)):
    a = get_owned(db, Audit, aid, p.company_id, "Audit")
    snap, cfg = snap_and_cfg(db, p.company_id, a.id)
    po = posture(snap, cfg)
    risks, gaps, rec = po.pop("_risks"), po.pop("_gaps"), po.pop("_recurring")
    ctrls = snap.in_scope_controls()
    ids = {cv.control.id for cv in ctrls}
    if a.status == "completed":
        fnd = [f for f in snap.findings if f.audit_id == a.id]
    else:
        fnd = [f for f in snap.findings if f.control_id in ids and f.status in OPEN_FINDING_STATUSES]
    plans = [pl for pl in snap.plans if pl.finding_id in {f.id for f in fnd}]
    events = db.execute(select(ComplianceEvent).where(ComplianceEvent.company_id == p.company_id,
                                                      ComplianceEvent.control_id.in_(ids) if ids else False)
                        .order_by(ComplianceEvent.occurred_at.desc()).limit(80)).scalars().all()
    tests_in = [t for cv in ctrls for t in cv.tests if t.audit_id == a.id]
    return {
        "id": a.id, "code": a.code, "name": a.name, "framework": a.framework.name, "type": a.audit_type, "status": a.status,
        "start_date": iso(a.start_date), "end_date": iso(a.end_date), "auditor": a.auditor, "outcome": a.outcome, "summary": a.summary,
        "readiness": po["readiness"], "posture": {k: v for k, v in po.items() if k not in ("readiness",)},
        "requirements": [{"id": r.id, "code": r.code, "title": r.title, "status": r.status,
                          "mapped": bool(snap.req_to_controls.get(r.id))} for r in snap.in_scope_requirements()],
        "controls": [control_row(cv, risks[cv.control.id], snap) for cv in sorted(ctrls, key=lambda c: c.control.code)],
        "findings": [finding_row(f, snap) for f in fnd],
        "remediation": [{"id": pl.id, "code": pl.code, "title": pl.title, "status": pl.status} for pl in plans],
        "gaps": gaps["subjects"], "recurring": rec,
        "tests": [{"code": t.code, "control_id": t.control_id, "result": t.result, "at": iso(t.tested_at)} for t in tests_in],
        "timeline": [{"type": e.event_type, "title": e.title, "at": iso(e.occurred_at)} for e in events],
    }


@router.post("/audits/{aid}/readiness")
def audit_readiness(aid: int, p: Principal = Depends(require("AUDITS_READ")), db: Session = Depends(get_db)):
    a = get_owned(db, Audit, aid, p.company_id, "Audit")
    snap, cfg = snap_and_cfg(db, p.company_id, a.id)
    po = posture(snap, cfg)
    po.pop("_risks")
    gaps, rec = po.pop("_gaps"), po.pop("_recurring")
    return {**po, "gaps": gaps, "recurring": rec, "audit": {"id": a.id, "name": a.name}}


@router.get("/what-changed")
def changed(p: Principal = Depends(require("AUDITS_READ")), db: Session = Depends(get_db)):
    snap, _ = snap_and_cfg(db, p.company_id)
    return what_changed(snap)


# ---------------------------------------------------------------- policies / regulatory
@router.get("/policies")
def policies(p: Principal = Depends(require("POLICIES_READ")), db: Session = Depends(get_db)):
    snap, _ = snap_and_cfg(db, p.company_id)
    today = snap.now.date()
    out = []
    for pol in sorted(snap.policies, key=lambda x: x.code):
        due = pol.last_reviewed_at and (today - pol.last_reviewed_at).days > pol.review_frequency_days
        out.append({"id": pol.id, "code": pol.code, "name": pol.name, "version": pol.current_version, "status": pol.status,
                    "last_reviewed": iso(pol.last_reviewed_at), "review_frequency_days": pol.review_frequency_days,
                    "review_overdue": bool(due), "controls": pol.parameters.get("control_codes", []),
                    "document_id": pol.document_id,
                    "next_review": iso(pol.last_reviewed_at + timedelta(days=pol.review_frequency_days)) if pol.last_reviewed_at else None})
    return out


@router.get("/policies/{pid}/versions")
def policy_versions(pid: int, p: Principal = Depends(require("POLICIES_READ")), db: Session = Depends(get_db)):
    pol = get_owned(db, Policy, pid, p.company_id, "Policy")
    rows = db.execute(select(PolicyVersion).where(PolicyVersion.policy_id == pol.id).order_by(PolicyVersion.effective_date)).scalars().all()
    return [{"version": v.version, "summary": v.summary, "change_summary": v.change_summary, "effective_date": iso(v.effective_date),
             "parameters": v.parameters} for v in rows]


@router.get("/regulatory-changes")
def regulatory_changes(p: Principal = Depends(require("REQUIREMENTS_READ")), db: Session = Depends(get_db)):
    snap, cfg = snap_and_cfg(db, p.company_id)
    rows = db.execute(select(RegulatoryChange).where(RegulatoryChange.company_id == p.company_id)
                      .order_by(RegulatoryChange.effective_date.desc())).scalars().all()
    out = []
    for r in rows:
        cids = snap.req_to_controls.get(r.requirement_id, [])
        req = snap.requirements.get(r.requirement_id)
        out.append({"id": r.id, "code": r.code, "title": r.title, "change_type": r.change_type, "old_version": r.old_version,
                    "new_version": r.new_version, "summary": r.summary, "effective_date": iso(r.effective_date), "status": r.status,
                    "risk": r.risk, "action_required": r.action_required, "source": r.source_label,
                    "requirement": {"id": req.id, "code": req.code, "title": req.title} if req else None,
                    "affected_controls": [{"id": c, "code": snap.controls[c].control.code, "name": snap.controls[c].control.name,
                                           "status": snap.controls[c].status} for c in cids]})
    return out


# ---------------------------------------------------------------- memory
@router.get("/memory")
def memory(category: str | None = None, subject: str | None = None, q: str | None = None, limit: int = 100,
           p: Principal = Depends(require("MEMORY_READ")), db: Session = Depends(get_db)):
    if category and category not in CATEGORIES:
        raise HTTPException(422, {"code": "INVALID_INPUT", "message": "Unknown memory category."})
    snap, _ = snap_and_cfg(db, p.company_id)
    rows = recall(db, p.company_id, subject_code=subject, category=category, query=q, limit=min(limit, 300))
    counts = dict(db.execute(select(MemoryRecord.category, func.count(MemoryRecord.id))
                             .where(MemoryRecord.company_id == p.company_id).group_by(MemoryRecord.category)).all())
    return {"records": [serialize(r, snap) for r in rows], "counts": counts, "categories": CATEGORIES}


@router.get("/memory/{mid}")
def memory_item(mid: int, p: Principal = Depends(require("MEMORY_READ")), db: Session = Depends(get_db)):
    m = get_owned(db, MemoryRecord, mid, p.company_id, "Memory record")
    snap, _ = snap_and_cfg(db, p.company_id)
    related = recall(db, p.company_id, subject_code=m.subject_code, limit=12) if m.subject_code else []
    return {**serialize(m, snap), "related": [serialize(r, snap) for r in related if r.id != m.id]}


# ---------------------------------------------------------------- reports
def report_json(r: Report, full: bool = False) -> dict:
    j = {"id": r.id, "code": r.code, "title": r.title, "type": r.report_type, "created_at": iso(r.created_at),
         "audit_id": r.audit_id, "readiness": (r.data.get("readiness") or {}).get("overall"), "agent_run_id": r.agent_run_id}
    if full:
        j["data"] = r.data
    return j


@router.get("/reports")
def reports(p: Principal = Depends(require("REPORTS_GENERATE", "AUDITS_READ", any_of=True)), db: Session = Depends(get_db)):
    rows = db.execute(select(Report).where(Report.company_id == p.company_id).order_by(Report.id.desc())).scalars().all()
    return [report_json(r) for r in rows]


@router.post("/reports/audit-readiness")
def generate_report(audit_id: int | None = None, p: Principal = Depends(require("REPORTS_GENERATE")), db: Session = Depends(get_db)):
    if audit_id:
        get_owned(db, Audit, audit_id, p.company_id, "Audit")
    r = build_readiness_report(db, p, audit_id=audit_id)
    log_action(db, company_id=p.company_id, principal=p, action=f"Generated report {r.code}", resource=r.code,
               resource_type="report", result="GENERATED")
    db.commit()
    return report_json(r, full=True)


@router.get("/reports/{rid}")
def get_report(rid: int, p: Principal = Depends(require("REPORTS_GENERATE", "AUDITS_READ", any_of=True)), db: Session = Depends(get_db)):
    return report_json(get_owned(db, Report, rid, p.company_id, "Report"), full=True)


@router.get("/reports/{rid}/pdf")
def report_pdf(rid: int, p: Principal = Depends(require("REPORTS_GENERATE", "AUDITS_READ", any_of=True)), db: Session = Depends(get_db)):
    r = get_owned(db, Report, rid, p.company_id, "Report")
    log_action(db, company_id=p.company_id, principal=p, action=f"Exported {r.code} as PDF", resource=r.code,
               resource_type="report", result="EXPORTED")
    db.commit()
    return Response(render_pdf(r), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{r.code}.pdf"'})


@router.get("/reports/{rid}/csv")
def report_csv(rid: int, p: Principal = Depends(require("REPORTS_GENERATE", "AUDITS_READ", any_of=True)), db: Session = Depends(get_db)):
    import csv
    import io

    r = get_owned(db, Report, rid, p.company_id, "Report")
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["section", "code", "title", "status", "severity_or_risk"])
    for f in r.data.get("open_findings", []):
        w.writerow(["open_finding", f["code"], f["title"], f["status"], f["severity"]])
    for t in r.data.get("risk_summary", {}).get("top", []):
        w.writerow(["top_risk", t["code"], t["name"], t["status"], t["category"]])
    for g in r.data.get("gaps", []):
        w.writerow(["gap", g["subject_code"], g["subject_name"], ";".join(g["gap_types"]), g["severity"]])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{r.code}.csv"'})

