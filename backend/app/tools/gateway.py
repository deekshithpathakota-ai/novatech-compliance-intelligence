"""Tool Gateway: Agent -> gateway -> authN -> authZ -> risk check -> approval check -> execute -> audit log.

The model can only *request* a tool. This gateway (application code) decides whether it runs.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.auth.deps import Principal
from app.compliance.snapshot import Snapshot, load_snapshot
from app.connectors.base import ConnectorUnavailable
from app.models import Company, ToolCall
from app.observability.telemetry import span
from app.risk.engine import merged_config
from app.security.dlp import redact_obj
from app.services.audit import log_action, record_security_event


class ToolError(Exception):
    def __init__(self, code: str, message: str, detail: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.detail = code, message, detail or {}


@dataclass
class ToolSpec:
    name: str
    description: str
    required_permission: str
    risk_level: str  # LOW | MEDIUM | HIGH | CRITICAL
    requires_approval: bool
    allowed_roles: set[str] | None
    args_model: type[BaseModel]
    fn: Callable[["ToolContext", Any], dict]
    safe_to_retry: bool = True
    mutates: bool = False

    def public(self) -> dict:
        return {"tool_name": self.name, "description": self.description, "required_permission": self.required_permission,
                "risk_level": self.risk_level, "requires_approval": self.requires_approval,
                "allowed_roles": sorted(self.allowed_roles) if self.allowed_roles else "any role with permission",
                "mutates_state": self.mutates}


@dataclass
class ToolContext:
    db: Session
    principal: Principal
    run_id: int | None = None
    approval_id: int | None = None  # set only by backend after a human approved
    audit_id: int | None = None
    _snap: Snapshot | None = None
    cache: dict = field(default_factory=dict)

    @property
    def company_id(self) -> int:
        return self.principal.company_id

    def snapshot(self, refresh: bool = False) -> Snapshot:
        if self._snap is None or refresh:
            self._snap = load_snapshot(self.db, self.company_id, audit_id=self.audit_id)
        return self._snap

    def risk_cfg(self) -> dict:
        c = self.db.get(Company, self.company_id)
        return merged_config(c.settings if c else {})


REGISTRY: dict[str, ToolSpec] = {}


def tool(name: str, *, description: str, permission: str, risk: str = "LOW", requires_approval: bool = False,
         roles: set[str] | None = None, args: type[BaseModel], safe_to_retry: bool = True, mutates: bool = False):
    def deco(fn):
        REGISTRY[name] = ToolSpec(name, description, permission, risk, requires_approval, roles, args, fn,
                                  safe_to_retry, mutates)
        return fn
    return deco


def call_tool(ctx: ToolContext, name: str, raw_args: dict | None = None, *, max_attempts: int = 2) -> dict:
    spec = REGISTRY.get(name)
    if spec is None:
        raise ToolError("UNKNOWN_TOOL", f"Tool '{name}' does not exist.")
    p, db = ctx.principal, ctx.db
    record = ToolCall(company_id=p.company_id, run_id=ctx.run_id, tool_name=name, args=redact_obj(raw_args or {})[0],
                      authorized=False, risk_level=spec.risk_level, status="PENDING")
    db.add(record)

    def audit(result: str, auth: str = "ALLOWED", reason: str | None = None):
        log_action(db, company_id=p.company_id, principal=p, actor_type="agent" if ctx.run_id else "user",
                   action=f"Tool {name}", resource=name, resource_type="tool", risk_level=spec.risk_level,
                   authorization_result=auth, tool_name=name, agent_run_id=ctx.run_id, approval_id=ctx.approval_id,
                   result=result, reason=reason)

    # 1. validate arguments
    try:
        args = spec.args_model.model_validate(raw_args or {})
    except ValidationError as e:
        record.status, record.error = "FAILED", "invalid parameters"
        audit("INVALID_ARGS", reason=str(e.errors()[:2]))
        raise ToolError("INVALID_TOOL_PARAMETERS", "Invalid tool parameters.",
                        {"errors": [{"loc": list(x["loc"]), "msg": x["msg"]} for x in e.errors()]})
    # 2. authorization (never delegated to the model)
    if not p.has(spec.required_permission) or (spec.allowed_roles and p.role_code not in spec.allowed_roles):
        record.status = "DENIED"
        audit("DENIED", "DENIED", f"requires {spec.required_permission}")
        record_security_event(db, company_id=p.company_id, user_id=p.user_id, event_type="tool_denied",
                              severity="MEDIUM", description=f"Tool {name} denied for {p.role_name}",
                              details={"tool": name, "permission": spec.required_permission})
        raise ToolError("PERMISSION_DENIED", f"You don't have permission to use {name}.",
                        {"your_role": p.role_name, "required_permission": spec.required_permission,
                         "recommended_action": "Request access from your Compliance Administrator."})
    record.authorized = True
    # 3/4. risk + approval check
    if spec.requires_approval and ctx.approval_id is None:
        record.status = "APPROVAL_REQUIRED"
        audit("APPROVAL_REQUIRED")
        raise ToolError("APPROVAL_REQUIRED", f"{name} is a {spec.risk_level.lower()}-risk action and needs human approval.",
                        {"risk_level": spec.risk_level})
    # 5. execute (retry transient connector failures when safe)
    t0 = time.perf_counter()
    attempts, last_err = 0, None
    while attempts < (max_attempts if spec.safe_to_retry else 1):
        attempts += 1
        try:
            with span(f"tool.{name}", {"tool": name, "run_id": ctx.run_id, "attempt": attempts}):
                out = spec.fn(ctx, args)
            out, dlp_types = redact_obj(out)
            if dlp_types:
                out["_dlp_notice"] = "Sensitive information redacted by policy."
            record.status, record.attempts = "SUCCEEDED", attempts
            record.duration_ms = int((time.perf_counter() - t0) * 1000)
            record.result_summary = str(out.get("_summary", ""))[:500]
            audit("SUCCEEDED")
            db.flush()
            return out
        except ConnectorUnavailable as e:
            last_err = e
            continue
        except ToolError:
            record.status = "FAILED"
            raise
    record.status, record.attempts, record.error = "FAILED", attempts, str(last_err)
    record.duration_ms = int((time.perf_counter() - t0) * 1000)
    audit("FAILED", reason=str(last_err))
    raise ToolError("TOOL_UNAVAILABLE", str(last_err), {"attempts": attempts})
