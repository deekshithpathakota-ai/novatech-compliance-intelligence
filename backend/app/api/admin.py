"""Security Center, audit trail, documents, settings and AI usage."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.agents.llm import router as model_router
from app.api.common import iso
from app.auth.deps import Principal, PermissionDenied, get_principal, require
from app.connectors.base import CONNECTOR_CATALOG
from app.database.session import get_db
from app.documents.ingest import IngestionError, ingest_document
from app.models import (AgentRun, AuditLog, Company, Document, DocumentChunk, Integration, SecurityEvent, ToolCall, User)
from app.rag.retrieval import hybrid_search
from app.risk.engine import DEFAULT_RISK_CONFIG, merged_config
from app.security import anomaly
from app.services.audit import log_action
from app.services.tenancy import get_owned

router = APIRouter(prefix="/api", tags=["admin"])


# ---------------------------------------------------------------- security
@router.get("/security/events")
def security_events(status: str | None = None, limit: int = 100, p: Principal = Depends(require("SECURITY_EVENTS_READ")),
                    db: Session = Depends(get_db)):
    q = select(SecurityEvent, User).join(User, User.id == SecurityEvent.user_id, isouter=True).where(SecurityEvent.company_id == p.company_id)
    if status:
        q = q.where(SecurityEvent.status == status)
    rows = db.execute(q.order_by(SecurityEvent.created_at.desc()).limit(min(limit, 300))).all()
    return [{"id": e.id, "type": e.event_type, "severity": e.severity, "description": e.description, "status": e.status,
             "user": u.name if u else None, "details": e.details, "at": iso(e.created_at)} for e, u in rows]


@router.get("/security/status")
def security_status(p: Principal = Depends(require("SECURITY_EVENTS_READ")), db: Session = Depends(get_db)):
    raised = anomaly.analyze(db, p.company_id)
    db.commit()
    since = datetime.now(timezone.utc) - timedelta(days=30)
    by_type = dict(db.execute(select(SecurityEvent.event_type, func.count(SecurityEvent.id)).where(
        SecurityEvent.company_id == p.company_id, SecurityEvent.created_at >= since).group_by(SecurityEvent.event_type)).all())
    denials = db.execute(select(func.count(AuditLog.id)).where(AuditLog.company_id == p.company_id,
                                                              AuditLog.authorization_result == "DENIED",
                                                              AuditLog.created_at >= since)).scalar_one()
    flagged = db.execute(select(func.count(Document.id)).where(Document.company_id == p.company_id, Document.status == "flagged")).scalar_one()
    open_alerts = db.execute(select(func.count(SecurityEvent.id)).where(SecurityEvent.company_id == p.company_id,
                                                                       SecurityEvent.status.in_(["OPEN", "INVESTIGATING"]))).scalar_one()
    return {
        "label": anomaly.LABEL, "new_alerts": raised, "open_alerts": open_alerts, "events_30d": by_type,
        "denials_30d": denials, "flagged_documents": flagged, "rules": anomaly.RULES,
        "protections": [
            {"name": "Tenant isolation", "status": "ENFORCED", "detail": "company_id filter on every query; cross-tenant records return 404"},
            {"name": "RBAC + contextual authorization", "status": "ENFORCED", "detail": "Server-side permission checks on every route and tool"},
            {"name": "Tool Gateway", "status": "ENFORCED", "detail": "authN → authZ → risk → approval → execute → audit log"},
            {"name": "Risk-based approvals", "status": "ENFORCED", "detail": "MEDIUM/HIGH/CRITICAL actions require a permitted human decision"},
            {"name": "Prompt-injection defense", "status": "ENFORCED", "detail": "Suspicious document spans quarantined and never sent to the model"},
            {"name": "DLP", "status": "ENFORCED", "detail": "Aadhaar/PAN/card/bank/API-key/password patterns masked in chunks and agent output"},
            {"name": "Rate limiting", "status": "ENFORCED", "detail": "Per-client limits on agent and login endpoints"},
            {"name": "Session management", "status": "ENFORCED", "detail": "Signed JWT bound to a revocable server-side session"},
            {"name": "WAF / DDoS", "status": "PROTOTYPE SIMULATION", "detail": "Not active in this prototype — provided by the hosting edge in production"},
        ],
    }


class EventUpdate(BaseModel):
    status: str = Field(pattern=r"^(OPEN|INVESTIGATING|RESOLVED)$")


@router.post("/security/events/{eid}")
def update_event(eid: int, body: EventUpdate, p: Principal = Depends(require("SECURITY_MANAGE")), db: Session = Depends(get_db)):
    e = get_owned(db, SecurityEvent, eid, p.company_id, "Security event")
    e.status = body.status
    log_action(db, company_id=p.company_id, principal=p, action=f"Security event #{e.id} → {body.status}", resource=str(e.id),
               resource_type="security_event", result=body.status)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- audit trail
@router.get("/audit-logs")
def audit_logs(page: int = 1, page_size: int = 50, actor_type: str | None = None, authorization: str | None = None,
               q: str | None = None, p: Principal = Depends(require("AUDIT_LOGS_READ")), db: Session = Depends(get_db)):
    page_size = max(10, min(page_size, 200))
    stmt = select(AuditLog).where(AuditLog.company_id == p.company_id)
    if actor_type:
        stmt = stmt.where(AuditLog.actor_type == actor_type)
    if authorization:
        stmt = stmt.where(AuditLog.authorization_result == authorization)
    if q:
        like = f"%{q[:80]}%"
        stmt = stmt.where(or_(AuditLog.action.ilike(like), AuditLog.resource.ilike(like), AuditLog.actor_label.ilike(like)))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {"total": total, "page": page, "page_size": page_size, "items": [
        {"id": a.id, "at": iso(a.created_at), "actor": a.actor_label, "actor_type": a.actor_type, "role": a.role, "action": a.action,
         "resource": a.resource, "resource_type": a.resource_type, "risk_level": a.risk_level,
         "authorization": a.authorization_result, "tool": a.tool_name, "agent_run_id": a.agent_run_id, "approval_id": a.approval_id,
         "result": a.result, "reason": a.reason, "evidence_reference": a.evidence_reference, "company_id": a.company_id,
         "user_id": a.user_id} for a in rows]}


# ---------------------------------------------------------------- documents
def _doc_access(p: Principal, d: Document) -> str | None:
    """Returns the missing permission, or None when the principal may read the document."""
    if d.required_permission and not p.has(d.required_permission):
        return d.required_permission
    if d.classification in ("confidential", "restricted") and not p.has("DOCUMENTS_CONFIDENTIAL_READ"):
        return "DOCUMENTS_CONFIDENTIAL_READ"
    if not p.has("DOCUMENTS_READ") and not (d.document_type == "policy" and p.has("POLICIES_READ")):
        return "DOCUMENTS_READ"
    return None


def doc_json(d: Document, p: Principal) -> dict:
    missing = _doc_access(p, d)
    return {"id": d.id, "code": d.code, "name": d.name, "type": d.document_type, "classification": d.classification,
            "framework": d.framework_code, "version": d.version, "status": d.status, "pages": d.page_count,
            "effective_date": iso(d.effective_date), "sha256": d.sha256, "security_flags": d.security_flags, "source": d.source,
            "uploaded_at": iso(d.created_at), "accessible": missing is None, "required_permission": missing}


@router.get("/documents")
def documents(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    rows = db.execute(select(Document).where(Document.company_id == p.company_id).order_by(Document.id.desc())).scalars().all()
    return [doc_json(d, p) for d in rows]


@router.get("/documents/{did}")
def document(did: int, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    d = get_owned(db, Document, did, p.company_id, "Document")
    missing = _doc_access(p, d)
    if missing:
        log_action(db, company_id=p.company_id, principal=p, action=f"Denied document {d.code}", resource=d.code,
                   resource_type="document", authorization_result="DENIED", result="DENIED", reason=f"missing {missing}")
        from app.services.audit import record_security_event

        record_security_event(db, company_id=p.company_id, user_id=p.user_id, event_type="permission_denied", severity="LOW",
                              description=f"{p.name} denied {d.code} ({d.classification})", details={"permission": missing})
        db.commit()
        raise PermissionDenied(p, missing, d.name)
    chunks = db.execute(select(DocumentChunk).where(DocumentChunk.document_id == d.id).order_by(DocumentChunk.chunk_index)).scalars().all()
    if d.classification in ("confidential", "restricted"):
        log_action(db, company_id=p.company_id, principal=p, action=f"Viewed confidential document {d.code}", resource=d.code,
                   resource_type="document", result="OK")
        db.commit()
    return {**doc_json(d, p), "chunks": [{"index": c.chunk_index, "page": c.page, "section": c.section,
                                          "content": "[Quarantined — untrusted instruction detected; not sent to the model]" if c.is_quarantined else c.content,
                                          "quarantined": c.is_quarantined} for c in chunks]}


@router.post("/documents")
async def upload_document(file: UploadFile = File(...), p: Principal = Depends(require("DOCUMENTS_UPLOAD")), db: Session = Depends(get_db)):
    data = await file.read()
    try:
        report = ingest_document(db, company_id=p.company_id, user_id=p.user_id, filename=file.filename or "upload.txt",
                                 data=data, principal=p)
    except IngestionError as e:
        raise HTTPException(422, {"code": "INVALID_FILE", "message": str(e)})
    db.commit()
    return report


@router.get("/search")
def search(q: str, p: Principal = Depends(require("AGENT_USE")), db: Session = Depends(get_db)):
    """Direct hybrid retrieval (used by the RAG inspector). Authorization is applied inside the SQL query."""
    if len(q) < 2:
        raise HTTPException(422, {"code": "INVALID_INPUT", "message": "Query too short."})
    return hybrid_search(db, p, q[:400], k=6)


# ---------------------------------------------------------------- settings
@router.get("/settings")
def settings(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    c = db.get(Company, p.company_id)
    integrations = db.execute(select(Integration).where(Integration.company_id == p.company_id)).scalars().all()
    return {"company": c.name, "environment": "DEMO", "risk_model": merged_config(c.settings), "default_risk_model": DEFAULT_RISK_CONFIG,
            "fault_injection": (c.settings or {}).get("fault_injection", {}), "model_routing": model_router.describe(),
            "can_manage": p.has("SETTINGS_MANAGE"),
            "connectors": [{"key": i.key, "name": i.name, "kind": i.kind, "status": i.status,
                            "last_sync_at": iso(i.last_sync_at)} for i in integrations] or CONNECTOR_CATALOG}


class RiskModelIn(BaseModel):
    weights: dict[str, float] | None = None
    thresholds: dict[str, float] | None = None


@router.put("/settings/risk-model")
def update_risk_model(body: RiskModelIn, p: Principal = Depends(require("SETTINGS_MANAGE")), db: Session = Depends(get_db)):
    c = db.get(Company, p.company_id)
    s = dict(c.settings or {})
    rm = dict(s.get("risk_model") or {})
    if body.weights:
        if any(k not in DEFAULT_RISK_CONFIG["weights"] or not (0 <= v <= 3) for k, v in body.weights.items()):
            raise HTTPException(422, {"code": "INVALID_INPUT", "message": "Weights must be known factors between 0 and 3."})
        rm["weights"] = {**DEFAULT_RISK_CONFIG["weights"], **rm.get("weights", {}), **body.weights}
    if body.thresholds:
        t = {**DEFAULT_RISK_CONFIG["thresholds"], **body.thresholds}
        if not (0 < t["MEDIUM"] < t["HIGH"] < t["CRITICAL"] <= 100):
            raise HTTPException(422, {"code": "INVALID_INPUT", "message": "Thresholds must satisfy 0 < MEDIUM < HIGH < CRITICAL ≤ 100."})
        rm["thresholds"] = t
    s["risk_model"] = rm
    c.settings = s
    log_action(db, company_id=p.company_id, principal=p, action="Updated risk model configuration", resource="risk_model",
               resource_type="settings", result="UPDATED", risk_level="MEDIUM")
    db.commit()
    return merged_config(c.settings)


@router.post("/settings/risk-model/reset")
def reset_risk_model(p: Principal = Depends(require("SETTINGS_MANAGE")), db: Session = Depends(get_db)):
    c = db.get(Company, p.company_id)
    c.settings = {**(c.settings or {}), "risk_model": {}}
    log_action(db, company_id=p.company_id, principal=p, action="Reset risk model", resource="risk_model", resource_type="settings", result="RESET")
    db.commit()
    return merged_config(c.settings)


class FaultIn(BaseModel):
    connector: str = Field(pattern=r"^(iam|email|jira|evidence_store)$")
    enabled: bool


@router.put("/settings/fault-injection")
def fault_injection(body: FaultIn, p: Principal = Depends(require("SETTINGS_MANAGE")), db: Session = Depends(get_db)):
    """Demo Simulation: make a connector 'unavailable' to demonstrate self-recovery and fail-safe verification."""
    c = db.get(Company, p.company_id)
    s = dict(c.settings or {})
    fi = dict(s.get("fault_injection") or {})
    fi[body.connector] = body.enabled
    s["fault_injection"] = fi
    c.settings = s
    log_action(db, company_id=p.company_id, principal=p, action=f"Fault injection {body.connector}={body.enabled}",
               resource=body.connector, resource_type="settings", result="UPDATED")
    db.commit()
    return fi


# ---------------------------------------------------------------- AI usage / observability
@router.get("/ai-usage")
def ai_usage(p: Principal = Depends(require("DASHBOARD_READ")), db: Session = Depends(get_db)):
    runs = db.execute(select(AgentRun).where(AgentRun.company_id == p.company_id)).scalars().all()
    tools = db.execute(select(ToolCall).where(ToolCall.company_id == p.company_id)).scalars().all()
    done = [r for r in runs if r.status in ("COMPLETED", "AWAITING_APPROVAL")]
    tok_in, tok_out = sum(r.tokens_in for r in runs), sum(r.tokens_out for r in runs)
    return {"label": "Prototype estimate", "agent_runs": len(runs),
            "success_rate": round(len(done) / len(runs) * 100) if runs else None,
            "avg_run_ms": round(sum(r.duration_ms or 0 for r in runs) / len(runs)) if runs else None,
            "model_calls": sum(r.llm_calls for r in runs), "tokens_in": tok_in, "tokens_out": tok_out,
            "estimated_cost_usd": round((tok_in * 1.25 + tok_out * 10) / 1_000_000, 4),
            "cost_basis": "Illustrative per-token rates for a reasoning-class model; configure actual pricing in production.",
            "tool_calls": len(tools), "tool_failures": sum(t.status == "FAILED" for t in tools),
            "tool_denials": sum(t.status == "DENIED" for t in tools),
            "engine": model_router.describe()}
