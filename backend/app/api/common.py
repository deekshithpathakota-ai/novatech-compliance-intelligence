from sqlalchemy.orm import Session

from app.compliance.snapshot import Snapshot, _aware, load_snapshot
from app.models import ApprovalRequest, Company, RemediationPlan, RemediationTask
from app.risk.engine import merged_config


def snap_and_cfg(db: Session, company_id: int, audit_id: int | None = None) -> tuple[Snapshot, dict]:
    c = db.get(Company, company_id)
    return load_snapshot(db, company_id, audit_id=audit_id), merged_config(c.settings if c else {})


def iso(dt):
    if dt is None:
        return None
    return _aware(dt).isoformat() if hasattr(dt, "hour") else dt.isoformat()


def task_json(t: RemediationTask) -> dict:
    from app.remediation.service import overdue

    return {"id": t.id, "seq": t.seq, "title": t.title, "owner": t.owner.name if t.owner else None, "owner_id": t.owner_id,
            "priority": t.priority, "due_date": iso(t.due_date), "status": t.status, "depends_on": t.depends_on_seq,
            "evidence_required": t.evidence_required, "risk": t.risk_level, "action_type": t.action_type,
            "completed_at": iso(t.completed_at), "overdue": overdue(t)}


def plan_json(p: RemediationPlan, tasks: list[RemediationTask], finding=None) -> dict:
    done = sum(t.status == "COMPLETED" for t in tasks)
    return {"id": p.id, "code": p.code, "title": p.title, "status": p.status, "rationale": p.rationale,
            "created_at": iso(p.created_at), "completed_at": iso(p.completed_at), "created_by_agent": p.created_by_agent,
            "summary": p.summary_of_actions, "progress": round(done / len(tasks) * 100) if tasks else 0,
            "tasks": [task_json(t) for t in tasks],
            "finding": {"id": finding.id, "code": finding.code, "title": finding.title, "severity": finding.severity,
                        "control_code": finding.control.code, "control_id": finding.control_id, "status": finding.status}
            if finding else None}


def approval_json(a: ApprovalRequest, principal=None) -> dict:
    return {"id": a.id, "code": a.code, "title": a.title, "reason": a.reason, "risk_level": a.risk_level,
            "affected": a.affected, "evidence_refs": a.evidence_refs, "required_permission": a.required_permission,
            "status": a.status, "action_type": a.action_type, "plan_id": a.plan_id, "task_id": a.task_id, "run_id": a.run_id,
            "requested_by_agent": a.requested_by_agent, "created_at": iso(a.created_at), "decided_at": iso(a.decided_at),
            "decision_note": a.decision_note,
            "can_decide": bool(principal and principal.has(a.required_permission) and a.status == "PENDING")}
