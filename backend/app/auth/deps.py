"""Request identity: every API call resolves a server-side Principal from a signed, non-revoked session.

The frontend never supplies company_id or role — both come from the verified session.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import decode_token
from app.database.session import get_db
from app.models import Permission, RolePermission, SessionRecord, User
from app.services.audit import log_action, record_security_event


@dataclass
class Principal:
    user_id: int
    company_id: int
    name: str
    email: str
    role_code: str
    role_name: str
    department: str | None
    permissions: set[str] = field(default_factory=set)
    jti: str | None = None

    def has(self, perm: str) -> bool:
        return perm in self.permissions


class PermissionDenied(HTTPException):
    """403 carrying a safe, user-facing 'Why was I denied?' explanation."""

    def __init__(self, principal: Principal, permission: str, resource: str | None = None):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "PERMISSION_DENIED",
                "message": "You don't have access to this resource.",
                "why": {
                    "your_role": principal.role_name,
                    "required_permission": permission,
                    "has_permission": False,
                    "resource": resource,
                    "recommended_action": "Request access from your Compliance Administrator.",
                },
            },
        )


def load_permissions(db: Session, role_id: int) -> set[str]:
    rows = db.execute(
        select(Permission.code).join(RolePermission, RolePermission.permission_id == Permission.id).where(
            RolePermission.role_id == role_id
        )
    ).scalars()
    return set(rows)


def principal_for_user(db: Session, user: User, jti: str | None = None) -> Principal:
    return Principal(
        user_id=user.id,
        company_id=user.company_id,
        name=user.name,
        email=user.email,
        role_code=user.role.code,
        role_name=user.role.name,
        department=user.department.name if user.department else None,
        permissions=load_permissions(db, user.role_id),
        jti=jti,
    )


def _unauthorized(msg: str = "Your session has expired. Please sign in again.") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "UNAUTHENTICATED", "message": msg})


def get_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else None
    if not token:
        raise _unauthorized("Authentication required.")
    try:
        claims = decode_token(token)
    except jwt.ExpiredSignatureError:
        raise _unauthorized()
    except jwt.PyJWTError:
        # forged / tampered token
        raise _unauthorized("Invalid session token.")

    sess = db.execute(select(SessionRecord).where(SessionRecord.jti == claims.get("jti"))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if not sess or sess.revoked_at is not None or sess.expires_at.replace(tzinfo=sess.expires_at.tzinfo or timezone.utc) < now:
        raise _unauthorized()
    user = db.get(User, int(claims["sub"]))
    if not user or not user.is_active or user.company_id != sess.company_id or user.company_id != claims.get("cid"):
        raise _unauthorized("Invalid session token.")
    p = principal_for_user(db, user, jti=sess.jti)
    request.state.principal = p
    return p


def require(*perms: str, any_of: bool = False):
    """Dependency factory: enforce permissions server-side and write denials to the audit trail."""

    def dep(request: Request, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> Principal:
        ok = any(principal.has(p) for p in perms) if any_of else all(principal.has(p) for p in perms)
        if not ok:
            missing = next(p for p in perms if not principal.has(p))
            log_action(
                db,
                company_id=principal.company_id,
                principal=principal,
                action=f"{request.method} {request.url.path}",
                resource=request.url.path,
                resource_type="api",
                authorization_result="DENIED",
                result="DENIED",
                reason=f"missing {missing}",
            )
            record_security_event(
                db,
                company_id=principal.company_id,
                user_id=principal.user_id,
                event_type="permission_denied",
                severity="LOW",
                description=f"{principal.name} ({principal.role_name}) was denied {request.url.path}",
                details={"permission": missing},
            )
            db.commit()
            raise PermissionDenied(principal, missing, request.url.path)
        return principal

    return dep
