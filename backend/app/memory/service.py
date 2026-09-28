"""Persistent compliance memory: durable, sourced records the agent writes and recalls across audits."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.compliance.snapshot import Snapshot, _aware, now_utc
from app.models import MemoryRecord
from app.rag.embeddings import tokenize

CATEGORIES = ["REGULATORY", "CONTROL", "AUDIT", "FINDING", "REMEDIATION", "EVIDENCE", "POLICY", "BEHAVIOR", "VERIFICATION"]


def remember(db: Session, *, company_id: int, category: str, subject_type: str, summary: str,
             subject_id: int | None = None, subject_code: str | None = None, details: dict | None = None,
             source_type: str = "system", source_id: int | None = None, source_label: str = "",
             occurred_at: datetime | None = None, outcome: str | None = None, verification: str | None = None,
             importance: int = 3, written_by: str = "agent") -> MemoryRecord:
    assert category in CATEGORIES, category
    rec = MemoryRecord(company_id=company_id, category=category, subject_type=subject_type, subject_id=subject_id,
                       subject_code=subject_code, summary=summary, details=details or {}, source_type=source_type,
                       source_id=source_id, source_label=source_label, occurred_at=occurred_at or now_utc(),
                       outcome=outcome, verification=verification, importance=importance, written_by=written_by)
    db.add(rec)
    db.flush()
    return rec


def recall(db: Session, company_id: int, *, subject_code: str | None = None, category: str | None = None,
           query: str | None = None, limit: int = 50) -> list[MemoryRecord]:
    stmt = select(MemoryRecord).where(MemoryRecord.company_id == company_id)
    if subject_code:
        stmt = stmt.where(MemoryRecord.subject_code == subject_code)
    if category:
        stmt = stmt.where(MemoryRecord.category == category)
    if query:
        toks = [t for t in tokenize(query) if len(t) > 2][:8]
        if toks:
            stmt = stmt.where(or_(*[MemoryRecord.summary.ilike(f"%{t}%") for t in toks],
                                  *[MemoryRecord.subject_code.ilike(f"%{t}%") for t in toks]))
    rows = db.execute(stmt.order_by(MemoryRecord.occurred_at.desc()).limit(limit * 3 if query else limit)).scalars().all()
    if query:
        qt = set(tokenize(query))
        rows = sorted(rows, key=lambda r: -len(qt & set(tokenize(r.summary + " " + (r.subject_code or "")))))[:limit]
    return rows


def current_relevance(rec: MemoryRecord, snap: Snapshot | None) -> str | None:
    """Explains why a past memory matters *now* — computed live from current state, never stored."""
    if not snap or not rec.subject_code:
        return None
    cv = snap.by_code(rec.subject_code)
    if not cv:
        return None
    if cv.status in ("OVERDUE", "FAIL", "EXPIRED") and rec.category in ("AUDIT", "FINDING", "BEHAVIOR", "VERIFICATION", "REMEDIATION"):
        return f"Same control is {cv.status.lower()} again."
    if cv.open_findings:
        return f"{len(cv.open_findings)} open finding(s) on this control today."
    if cv.status == "PASS":
        return "Control currently appears satisfied based on available evidence."
    return f"Control status today: {cv.status.replace('_', ' ').lower()}."


def serialize(rec: MemoryRecord, snap: Snapshot | None = None) -> dict:
    return {"id": rec.id, "category": rec.category, "subject_type": rec.subject_type, "subject_code": rec.subject_code,
            "summary": rec.summary, "details": rec.details, "source_type": rec.source_type, "source_id": rec.source_id,
            "source_label": rec.source_label, "occurred_at": _aware(rec.occurred_at).isoformat(),
            "outcome": rec.outcome, "verification": rec.verification, "importance": rec.importance,
            "written_by": rec.written_by, "created_at": _aware(rec.created_at).isoformat() if rec.created_at else None,
            "current_relevance": current_relevance(rec, snap)}
