import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import iso, snap_and_cfg
from app.auth.deps import Principal, PermissionDenied, require
from app.compliance.recurring import detect_recurring
from app.compliance.snapshot import _aware, evidence_freshness, evidence_status
from app.compliance.testing import run_control_test
from app.database.session import get_db
from app.documents.ingest import IngestionError, SUPPORTED, ingest_document
from app.memory.service import recall, serialize
from app.models import (ComplianceEvent, Control, Document, Evidence, EvidenceVersion, Framework, Requirement)
from app.risk.engine import assess_control
from app.schemas.serializers import control_row, evidence_row, finding_row
from app.services.audit import log_action
from app.services.tenancy import get_owned

router = APIRouter(prefix="/api", tags=["compliance"])


def _visible_controls(p: Principal, snap):
    """Control owners only see controls assigned to them (contextual authorization)."""
    if p.has("CONTROLS_READ") or p.has("COMPLIANCE_READ_ALL"):
        return list(snap.controls.values())
    if p.has("CONTROLS_READ_ASSIGNED"):
        return [cv for cv in snap.controls.values() if cv.owner_id == p.user_id]
    raise PermissionDenied(p, "CONTROLS_READ", "/api/controls")


@router.get("/frameworks")
def frameworks(p: Principal = Depends(require("REQUIREMENTS_READ")), db: Session = Depends(get_db)):
    snap, _ = snap_and_cfg(db, p.company_id)
    out = []
    for f in snap.frameworks.values():
        reqs = [r for r in snap.requirements.values() if r.framework_id == f.id]
        mapped = sum(1 for r in reqs if snap.req_to_controls.get(r.id))
        out.append({"id": f.id, "code": f.code, "name": f.name, "version": f.version, "description": f.description,
                    "is_demo_mapping": f.is_demo_mapping, "requirements": len(reqs), "mapped": mapped,
                    "controls": len({c for r in reqs for c in snap.req_to_controls.get(r.id, [])})})
    return out


@router.get("/requirements")
def requirements(framework: str | None = None, p: Principal = Depends(require("REQUIREMENTS_READ")), db: Session = Depends(get_db)):
    snap, _ = snap_and_cfg(db, p.company_id)
    rows = []
    for r in sorted(snap.requirements.values(), key=lambda r: r.code):
        fw = snap.frameworks[r.framework_id]
        if framework and fw.code != framework:
            continue
        cids = snap.req_to_controls.get(r.id, [])
        rows.append({"id": r.id, "code": r.code, "title": r.title, "category": r.category, "framework": fw.code,
                     "framework_name": fw.name, "version": r.current_version, "status": r.status,
                     "controls": [{"id": c, "code": snap.controls[c].control.code, "status": snap.controls[c].status} for c in cids],
                     "mapped": bool(cids)})
    return rows


@router.get("/requirements/{rid}")
def requirement(rid: int, p: Principal = Depends(require("REQUIREMENTS_READ")), db: Session = Depends(get_db)):
    r = get_owned(db, Requirement, rid, p.company_id, "Requirement")
    snap, cfg = snap_and_cfg(db, p.company_id)
    vers = snap.req_versions.get(r.id, [])
    return {"id": r.id, "code": r.code, "title": r.title, "description": r.description, "category": r.category,
            "framework": snap.frameworks[r.framework_id].name, "status": r.status, "version": r.current_version,
            "label": "Prototype / Demonstration Mapping",
            "versions": [{"version": v.version, "description": v.description, "change_summary": v.change_summary,
                          "effective_date": iso(v.effective_date), "parameters": v.parameters} for v in vers],
            "controls": [control_row(snap.controls[c], assess_control(snap.controls[c], cfg), snap) for c in snap.req_to_controls.get(r.id, [])]}


@router.get("/controls")
def controls(status: str | None = None, framework: str | None = None, risk: str | None = None,
             p: Principal = Depends(require("CONTROLS_READ", "CONTROLS_READ_ASSIGNED", any_of=True)), db: Session = Depends(get_db)):
    snap, cfg = snap_and_cfg(db, p.company_id)
    rows = [control_row(cv, assess_control(cv, cfg), snap) for cv in _visible_controls(p, snap)]
    if status == "attention":
        rows = [r for r in rows if r["status"] != "PASS"]
    elif status:
        rows = [r for r in rows if r["status"] == status]
    if framework:
        rows = [r for r in rows if framework in r["frameworks"]]
    if risk:
        rows = [r for r in rows if r["risk_category"] == risk]
    return sorted(rows, key=lambda r: r["code"])


def lineage(cv, snap, plans, verifs) -> dict:
    c = cv.control
    nodes, edges = [], []

    def node(i, kind, label, sub="", status=None, link=None):
        nodes.append({"id": i, "kind": kind, "label": label, "sub": sub, "status": status, "link": link})

    node(f"c{c.id}", "control", c.code, c.name, cv.status, f"/controls/{c.id}")
    for code in cv.requirement_codes:
        r = next(x for x in snap.requirements.values() if x.code == code)
        node(f"r{r.id}", "requirement", r.code, r.title, r.status, "/requirements")
        edges.append((f"r{r.id}", f"c{c.id}"))
    t = cv.tests[0] if cv.tests else None
    if t:
        node(f"t{t.id}", "test", t.code, f"{t.result} · {_aware(t.tested_at).date().isoformat()}", t.result)
        edges.append((f"c{c.id}", f"t{t.id}"))
    for e in cv.evidence:
        node(f"e{e.id}", "evidence", e.code, e.name, evidence_status(e, snap.now), f"/evidence?focus={e.id}")
        edges.append((f"t{t.id}" if t else f"c{c.id}", f"e{e.id}"))
        if e.document_id:
            node(f"d{e.document_id}-{e.id}", "document", f"Page {e.page or 1}", f"Document #{e.document_id}", None, f"/documents/{e.document_id}")
            edges.append((f"e{e.id}", f"d{e.document_id}-{e.id}"))
    for f in cv.findings[:3]:
        node(f"f{f.id}", "finding", f.code, f.title, f.status, f"/findings/{f.id}")
        edges.append((f"c{c.id}", f"f{f.id}"))
        for pl in [x for x in plans if x.finding_id == f.id][:1]:
            node(f"p{pl.id}", "remediation", pl.code, pl.title, pl.status, "/remediation")
            edges.append((f"f{f.id}", f"p{pl.id}"))
            for v in [x for x in verifs if x.plan_id == pl.id][-1:]:
                node(f"v{v.id}", "verification", v.code, v.result, v.result)
                edges.append((f"p{pl.id}", f"v{v.id}"))
    return {"nodes": nodes, "edges": [{"from": a, "to": b} for a, b in edges]}


@router.get("/controls/{cid}")
def control_detail(cid: int, p: Principal = Depends(require("CONTROLS_READ", "CONTROLS_READ_ASSIGNED", any_of=True)),
                   db: Session = Depends(get_db)):
    get_owned(db, Control, cid, p.company_id, "Control")
    snap, cfg = snap_and_cfg(db, p.company_id)
    cv = snap.controls[cid]
    if cv not in _visible_controls(p, snap):
        raise PermissionDenied(p, "CONTROLS_READ", f"/api/controls/{cid}")
    risk = assess_control(cv, cfg)
    rec = next((x for x in detect_recurring(snap, include_closed=True) if x["control_code"] == cv.control.code), None)
    plans = [pl for pl in snap.plans if pl.finding_id in {f.id for f in cv.findings}]
    verifs = [v for v in snap.verifications if v.control_id == cid]
    reqs = [r for r in snap.requirements.values() if r.code in cv.requirement_codes]
    events = db.execute(select(ComplianceEvent).where(ComplianceEvent.company_id == p.company_id, ComplianceEvent.control_id == cid)
                        .order_by(ComplianceEvent.occurred_at.desc()).limit(60)).scalars().all()
    mem = recall(db, p.company_id, subject_code=cv.control.code, limit=20)
    return {
        **control_row(cv, risk, snap),
        "requirements_detail": [{"id": r.id, "code": r.code, "title": r.title, "version": r.current_version, "status": r.status,
                                 "framework": snap.frameworks[r.framework_id].code} for r in reqs],
        "test_procedure": cv.control.test_procedure, "owner_history": cv.owner_history,
        "tests": [{"id": t.id, "code": t.code, "tested_at": iso(t.tested_at), "result": t.result, "method": t.method,
                   "tester_type": t.tester_type, "notes": t.notes, "questions": t.questions} for t in cv.tests],
        "evidence": [evidence_row(e, snap) for e in cv.evidence],
        "findings": [finding_row(f, snap) for f in cv.findings],
        "recurring": rec,
        "plans": [{"id": pl.id, "code": pl.code, "title": pl.title, "status": pl.status} for pl in plans],
        "verifications": [{"code": v.code, "result": v.result, "at": iso(v.verified_at), "checks": v.checks} for v in verifs],
        "timeline": [{"type": e.event_type, "title": e.title, "at": iso(e.occurred_at), "actor_type": e.actor_type} for e in events],
        "memory": [serialize(m, snap) for m in mem],
        "lineage": lineage(cv, snap, plans, verifs),
        "health_history": [{"date": _aware(t.tested_at).date().isoformat(), "result": t.result} for t in reversed(cv.tests)],
    }


@router.post("/controls/{cid}/test")
def test_control(cid: int, p: Principal = Depends(require("CONTROL_TEST_RUN")), db: Session = Depends(get_db)):
    c = get_owned(db, Control, cid, p.company_id, "Control")
    out = run_control_test(db, p, cid)
    log_action(db, company_id=p.company_id, principal=p, action=f"Tested control {c.code}", resource=c.code,
               resource_type="control", result=out["result"], risk_level="LOW")
    db.commit()
    return out


# ---------------------------------------------------------------- evidence
@router.get("/evidence")
def evidence(status: str | None = None, control_id: int | None = None, include_history: bool = False,
             p: Principal = Depends(require("EVIDENCE_READ")), db: Session = Depends(get_db)):
    snap, _ = snap_and_cfg(db, p.company_id)
    visible = {cv.control.id for cv in _visible_controls(p, snap)} if not p.has("COMPLIANCE_READ_ALL") and not p.has("CONTROLS_READ") else None
    q = select(Evidence).where(Evidence.company_id == p.company_id)
    if not include_history:
        q = q.where(Evidence.is_current.is_(True))
    if control_id:
        q = q.where(Evidence.control_id == control_id)
    rows = [evidence_row(e, snap) for e in db.execute(q).scalars() if visible is None or e.control_id in visible]
    if status:
        rows = [r for r in rows if r["status"] == status]
    missing = [{"control_id": cv.control.id, "control_code": cv.control.code, "control_name": cv.control.name,
                "owner": cv.owner_name} for cv in snap.controls.values() if not cv.evidence and (visible is None or cv.control.id in visible)]
    if status == "MISSING":
        rows = []
    return {"items": sorted(rows, key=lambda r: r["valid_until"] or ""), "missing": missing}


@router.get("/evidence/{eid}")
def evidence_detail(eid: int, p: Principal = Depends(require("EVIDENCE_READ")), db: Session = Depends(get_db)):
    e = get_owned(db, Evidence, eid, p.company_id, "Evidence")
    snap, _ = snap_and_cfg(db, p.company_id)
    vers = db.execute(select(EvidenceVersion).where(EvidenceVersion.evidence_id == eid)).scalars().all()
    doc = db.get(Document, e.document_id) if e.document_id else None
    return {**evidence_row(e, snap), "versions": [{"version": v.version, "collected_at": iso(v.collected_at), "sha256": v.sha256,
                                                   "note": v.note} for v in vers],
            "document": {"id": doc.id, "code": doc.code, "name": doc.name, "classification": doc.classification} if doc else None}


@router.post("/evidence")
async def upload_evidence(control_id: int = Form(...), name: str = Form(..., max_length=200), valid_days: int = Form(90),
                          supersede_expired: bool = Form(True), file: UploadFile = File(...),
                          p: Principal = Depends(require("EVIDENCE_UPLOAD")), db: Session = Depends(get_db)):
    c = get_owned(db, Control, control_id, p.company_id, "Control")
    if not (1 <= valid_days <= 730):
        raise HTTPException(422, {"code": "INVALID_INPUT", "message": "valid_days must be between 1 and 730."})
    data = await file.read()
    if not data:
        raise HTTPException(422, {"code": "INVALID_FILE", "message": "The uploaded file is empty."})
    report = None
    doc_id = None
    import os

    if os.path.splitext((file.filename or "").lower())[1] in SUPPORTED:
        try:
            report = ingest_document(db, company_id=p.company_id, user_id=p.user_id, filename=file.filename, data=data,
                                     overrides={"document_type": "evidence"}, principal=p)
            doc_id = report["document"]["id"]
        except IngestionError as ex:
            raise HTTPException(422, {"code": "INVALID_FILE", "message": str(ex)})
    now = datetime.now(timezone.utc)
    if supersede_expired:
        for old in db.execute(select(Evidence).where(Evidence.control_id == c.id, Evidence.is_current.is_(True))).scalars():
            if evidence_status(old, now) == "EXPIRED":
                old.is_current = False
    codes = [int(x.split("-")[1]) for x in db.execute(select(Evidence.code).where(Evidence.company_id == p.company_id)).scalars()
             if x.split("-")[1].isdigit()]
    e = Evidence(company_id=p.company_id, code=f"EV-{(max(codes) if codes else 0) + 1:03d}", name=name, control_id=c.id,
                 owner_id=p.user_id, source=f"Upload by {p.name}", collected_at=now, valid_until=now + timedelta(days=valid_days),
                 verification_status="unverified", sha256=hashlib.sha256(data).hexdigest(), document_id=doc_id, page=1)
    db.add(e)
    db.flush()
    db.add(EvidenceVersion(company_id=p.company_id, evidence_id=e.id, version=1, collected_at=now, sha256=e.sha256, note="Uploaded"))
    from app.models import EvidenceRequest

    fulfilled = []
    for req in db.execute(select(EvidenceRequest).where(EvidenceRequest.company_id == p.company_id, EvidenceRequest.control_id == c.id,
                                                        EvidenceRequest.status == "OPEN")).scalars():
        req.status, req.fulfilled_evidence_id = "FULFILLED", e.id
        fulfilled.append(req.code)
    db.add(ComplianceEvent(company_id=p.company_id, event_type="evidence_uploaded", title=f"Evidence uploaded: {name}",
                           entity_type="evidence", entity_code=e.code, control_id=c.id, occurred_at=now, actor_id=p.user_id))
    log_action(db, company_id=p.company_id, principal=p, action=f"Uploaded evidence {e.code} for {c.code}", resource=e.code,
               resource_type="evidence", result="UNVERIFIED", evidence_reference=e.code)
    db.commit()
    return {"evidence": {"id": e.id, "code": e.code, "status": "UNVERIFIED"}, "ingestion": report, "fulfilled_requests": fulfilled}


@router.post("/evidence/{eid}/verify")
def verify_evidence(eid: int, p: Principal = Depends(require("FINDINGS_MANAGE")), db: Session = Depends(get_db)):
    e = get_owned(db, Evidence, eid, p.company_id, "Evidence")
    e.verification_status = "verified"
    log_action(db, company_id=p.company_id, principal=p, action=f"Verified evidence {e.code}", resource=e.code,
               resource_type="evidence", result="VERIFIED", evidence_reference=e.code)
    db.commit()
    return {"ok": True, "code": e.code}


# ---------------------------------------------------------------- explanations ("Why?")
@router.get("/explain")
def explain(kind: str, code: str, p: Principal = Depends(require("DASHBOARD_READ", "CONTROLS_READ_ASSIGNED", any_of=True)),
            db: Session = Depends(get_db)):
    snap, cfg = snap_and_cfg(db, p.company_id)
    if kind == "control":
        cv = snap.by_code(code)
        if not cv:
            raise HTTPException(404, {"code": "NOT_FOUND", "message": "Control not found."})
        r = assess_control(cv, cfg)
        prior = [f for f in cv.findings if f.status == "CLOSED"]
        ev = [{"code": e.code, "name": e.name, "status": evidence_status(e, snap.now), "id": e.id,
               "freshness": evidence_freshness(e, snap.now)} for e in cv.evidence]
        rec = next((x for x in detect_recurring(snap) if x["control_code"] == code), None)
        points = [
            {"label": "Rule", "text": f"Risk = Severity × Likelihood × Criticality × Evidence freshness × Recurrence → {r.score} ({r.category})"},
            *[{"label": "Factor", "text": t} for t in r.explanation],
        ]
        if cv.days_since_test is not None:
            points.append({"label": "Testing", "text": f"Last tested {cv.days_since_test} days ago; required every {cv.control.frequency_days} days."})
        if prior:
            points.append({"label": "History", "text": f"{len(prior)} previous finding(s): " + ", ".join(f.code for f in prior[:4])})
        if rec:
            points.append({"label": "Recurrence", "text": f"{rec['occurrences']} occurrences since {rec['first_detected']} — {rec['interpretation']}"})
        return {"title": f"Why is {code} {r.category.lower()} risk?", "points": points, "evidence": ev, "risk": r.as_dict(),
                "sources": [{"kind": "evidence", **e} for e in ev] + [{"kind": "finding", "code": f.code, "id": f.id} for f in prior[:4]],
                "label": "Explanation from deterministic rules, evidence and history — not AI opinion."}
    if kind == "evidence":
        e = db.execute(select(Evidence).where(Evidence.company_id == p.company_id, Evidence.code == code)).scalar_one_or_none()
        if not e:
            raise HTTPException(404, {"code": "NOT_FOUND", "message": "Evidence not found."})
        st = evidence_status(e, snap.now)
        fr = evidence_freshness(e, snap.now)
        pts = [{"label": "Status", "text": f"{st}: collected {fr['age_days']} days ago, validity {fr['validity_days']} days, "
                                           f"{'expired ' + str(-fr['remaining_days']) + ' days ago' if fr['remaining_days'] < 0 else str(fr['remaining_days']) + ' days remaining'}."}]
        if e.completeness < 1:
            pts.append({"label": "Completeness", "text": f"Covers {round(e.completeness * 100)}% of the required population."})
        if e.verification_status != "verified":
            pts.append({"label": "Verification", "text": "Not yet verified by a reviewer."})
        if e.is_conflicting:
            pts.append({"label": "Conflict", "text": "Conflicting evidence detected — another source disagrees."})
        return {"title": f"Why is {code} {st.lower()}?", "points": pts, "evidence": [], "sources": []}
    raise HTTPException(422, {"code": "INVALID_INPUT", "message": "Unsupported explanation kind."})


@router.get("/frameworks/{fid}")
def framework_detail(fid: int, p: Principal = Depends(require("REQUIREMENTS_READ")), db: Session = Depends(get_db)):
    f = get_owned(db, Framework, fid, p.company_id, "Framework")
    return {"id": f.id, "code": f.code, "name": f.name, "description": f.description, "is_demo_mapping": f.is_demo_mapping}

