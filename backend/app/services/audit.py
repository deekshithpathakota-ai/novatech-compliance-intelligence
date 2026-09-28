"""Immutable audit trail + security event recording. Every call writes to the database."""
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.models import AuditLog, SecurityEvent

if TYPE_CHECKING:
    from app.auth.deps import Principal


def log_action(
    db: Session,
    *,
    company_id: int,
    action: str,
    principal: "Principal | None" = None,
    actor_type: str = "user",
    resource: str | None = None,
    resource_type: str | None = None,
    risk_level: str | None = None,
    authorization_result: str = "ALLOWED",
    tool_name: str | None = None,
    agent_run_id: int | None = None,
    approval_id: int | None = None,
    result: str | None = None,
    reason: str | None = None,
    evidence_reference: str | None = None,
    commit: bool = False,
) -> AuditLog:
    entry = AuditLog(
        company_id=company_id,
        user_id=principal.user_id if principal else None,
        actor_type=actor_type,
        actor_label="Compliance Agent" if actor_type == "agent" else (principal.name if principal else "System"),
        role=principal.role_code if principal else None,
        action=action,
        resource=resource,
        resource_type=resource_type,
        risk_level=risk_level,
        authorization_result=authorization_result,
        tool_name=tool_name,
        agent_run_id=agent_run_id,
        approval_id=approval_id,
        result=result,
        reason=reason,
        evidence_reference=evidence_reference,
    )
    db.add(entry)
    if commit:
        db.commit()
    else:
        db.flush()
    return entry


def record_security_event(
    db: Session,
    *,
    company_id: int,
    event_type: str,
    severity: str,
    description: str,
    user_id: int | None = None,
    details: dict[str, Any] | None = None,
    commit: bool = False,
) -> SecurityEvent:
    ev = SecurityEvent(
        company_id=company_id,
        user_id=user_id,
        event_type=event_type,
        severity=severity,
        description=description,
        details=details or {},
    )
    db.add(ev)
    if commit:
        db.commit()
    else:
        db.flush()
    return ev
