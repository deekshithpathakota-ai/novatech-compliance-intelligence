"""Evidence-based control testing. Each test question is answered from evidence facts, never assumed."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.compliance.snapshot import _aware, evidence_status, load_snapshot
from app.models import ComplianceEvent, ControlTest


def assess(cv, now: datetime) -> dict:
    c = cv.control
    ev = [e for e in cv.evidence]
    usable = [e for e in ev if evidence_status(e, now) in ("VALID", "EXPIRING")]
    latest = max(ev, key=lambda e: _aware(e.collected_at)) if ev else None
    age = (now - _aware(latest.collected_at)).days if latest else None
    facts = {}
    for e in ev:
        facts.update(e.extracted or {})

    def ans(ok: bool | None, why: str, ref=None):
        return {"answer": "Yes" if ok else ("No" if ok is False else "Insufficient evidence"), "basis": why,
                "evidence": ref}

    qs: list[dict] = []
    for q in (c.test_procedure or []):
        ql = q.lower()
        if "performed" in ql and "frequency" not in ql:
            qs.append({"question": q, **ans(latest is not None, f"Latest evidence {latest.code} collected {age} days ago" if latest else "No evidence on file", latest.code if latest else None)})
        elif "frequency" in ql:
            ok = None if age is None else age <= c.frequency_days
            qs.append({"question": q, **ans(ok, f"Evidence age {age} days vs {c.frequency_days}-day frequency" if age is not None else "No dated evidence", latest.code if latest else None)})
        elif "all users" in ql or "complete" in ql:
            ok = None if not ev else all(e.completeness >= 1.0 for e in usable) and bool(usable)
            qs.append({"question": q, **ans(ok, "Evidence covers the full population" if ok else "Evidence incomplete or expired", latest.code if latest else None)})
        elif "privileged" in ql:
            v = facts.get("privileged_reviewed")
            ok = None if v is None else bool(v)
            qs.append({"question": q, **ans(ok, f"Evidence records privileged_reviewed={v}" if v is not None else "Evidence does not state this", latest.code if latest else None)})
        elif "terminated" in ql:
            v = facts.get("terminated_still_active")
            ok = None if v is None and not usable else (v in (0, None) and bool(usable))
            qs.append({"question": q, **ans(ok, "No terminated users with active access in current evidence" if ok else "Current evidence does not confirm removal", latest.code if latest else None)})
        elif "approved" in ql or "reviewed and approved" in ql:
            ok = None if not ev else any(e.verification_status == "verified" for e in usable)
            qs.append({"question": q, **ans(ok, "Evidence verified by reviewer" if ok else "No verified, current evidence", latest.code if latest else None)})
        elif "evidence" in ql:
            qs.append({"question": q, **ans(bool(usable), f"{len(usable)} current evidence item(s)" if usable else "No current evidence (missing or expired)", latest.code if latest else None)})
        else:
            qs.append({"question": q, **ans(None, "Not determinable from evidence")})
    yes = sum(q["answer"] == "Yes" for q in qs)
    no = sum(q["answer"] == "No" for q in qs)
    if not ev:
        result = "INSUFFICIENT_EVIDENCE"
    elif no == 0 and yes == len(qs):
        result = "PASS"
    elif yes == 0 or (qs and qs[0]["answer"] == "No"):
        result = "FAIL"
    elif any(q["answer"] == "No" and "frequency" in q["question"].lower() for q in qs) and not usable:
        result = "FAIL"
    else:
        result = "PARTIAL"
    quality = "HIGH" if usable and all(e.verification_status == "verified" for e in usable) else ("MEDIUM" if usable else "LOW")
    return {"result": result, "questions": qs, "evidence_quality": quality,
            "coverage": f"{yes}/{len(qs)} test questions satisfied by evidence", "source_count": len(ev)}


def run_control_test(db: Session, principal, control_id: int) -> dict:
    now = datetime.now(timezone.utc)
    snap = load_snapshot(db, principal.company_id)
    cv = snap.controls[control_id]
    out = assess(cv, now)
    codes = [int(c.split("-")[1]) for c in db.execute(select(ControlTest.code).where(ControlTest.company_id == principal.company_id)).scalars()
             if c.startswith("CT-") and c.split("-")[1].isdigit()]
    t = ControlTest(company_id=principal.company_id, code=f"CT-{(max(codes) if codes else 0) + 1:03d}", control_id=control_id,
                    tested_at=now, tester_id=principal.user_id, tester_type="user", result=out["result"],
                    method="evidence-based assessment", questions=out["questions"],
                    evidence_ids=[e.id for e in cv.evidence], notes=out["coverage"])
    db.add(t)
    c = cv.control
    c.last_tested_at, c.last_result = now, out["result"]
    db.add(ComplianceEvent(company_id=principal.company_id, event_type="control_tested",
                           title=f"Control tested: {c.code} {out['result']}", entity_type="control_test", entity_code=t.code,
                           control_id=c.id, occurred_at=now, actor_id=principal.user_id))
    db.flush()
    snap2 = load_snapshot(db, principal.company_id)
    c.status = snap2.controls[control_id].status
    return {"test": {"code": t.code, "result": t.result, "tested_at": now.isoformat()}, **out, "control_status": c.status}
