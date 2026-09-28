from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import Principal, get_principal, principal_for_user
from app.auth.security import create_access_token, new_jti, verify_password
from app.database.session import get_db
from app.models import Company, Role, SessionRecord, User
from app.services.audit import log_action, record_security_event

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    mode: Literal["password", "demo", "sso"] = "password"
    email: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=40)


def principal_json(p: Principal, company: Company, auth_method: str) -> dict:
    return {"id": p.user_id, "name": p.name, "email": p.email, "role": p.role_code, "role_name": p.role_name,
            "department": p.department, "permissions": sorted(p.permissions),
            "company": {"id": company.id, "name": company.name, "slug": company.slug},
            "environment": "DEMO", "auth_method": auth_method}


@router.get("/personas")
def personas(db: Session = Depends(get_db)):
    """Demo Environment menu — clearly labelled demo identities for the NovaTech tenant."""
    rows = db.execute(select(User).join(Company).where(Company.slug == "novatech", User.is_demo_persona.is_(True))).scalars().all()
    return [{"name": u.name, "email": u.email, "role": u.role.code, "role_name": u.role.name, "title": u.title,
             "department": u.department.name if u.department else None} for u in rows]


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    user: User | None = None
    method = body.mode
    if body.mode == "password":
        user = db.execute(select(User).where(User.email == (body.email or "").lower().strip())).scalar_one_or_none()
        if not user or not verify_password(body.password or "", user.password_hash):
            if user:
                record_security_event(db, company_id=user.company_id, user_id=user.id, event_type="failed_login",
                                      severity="LOW", description=f"Failed sign-in for {user.email}", commit=True)
            raise HTTPException(401, {"code": "INVALID_CREDENTIALS", "message": "Email or password is incorrect."})
    else:  # demo persona / Demo SAML SSO — both clearly labelled simulations
        role = (body.role or "COMPLIANCE_OFFICER").upper()
        if body.email:
            user = db.execute(select(User).where(User.email == body.email.lower(), User.is_demo_persona.is_(True))).scalar_one_or_none()
        else:
            user = db.execute(select(User).join(Role).join(Company).where(
                Company.slug == "novatech", Role.code == role, User.is_demo_persona.is_(True))).scalars().first()
        if not user:
            raise HTTPException(404, {"code": "NO_DEMO_USER", "message": "No demo user for that role."})
    if not user.is_active:
        raise HTTPException(403, {"code": "INACTIVE", "message": "This account is disabled."})
    jti = new_jti()
    token, exp = create_access_token(user_id=user.id, company_id=user.company_id, role=user.role.code, jti=jti)
    db.add(SessionRecord(jti=jti, user_id=user.id, company_id=user.company_id, expires_at=exp,
                         auth_method={"sso": "Demo SAML SSO", "demo": "Demo persona", "password": "password"}[method],
                         ip=request.client.host if request.client else None))
    p = principal_for_user(db, user, jti)
    log_action(db, company_id=user.company_id, principal=p, action=f"Signed in ({'Demo SAML SSO' if method == 'sso' else method})",
               resource="session", resource_type="auth", result="SUCCESS")
    db.commit()
    return {"token": token, "expires_at": exp.isoformat(), "user": principal_json(p, db.get(Company, user.company_id), method)}


@router.post("/logout")
def logout(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    s = db.execute(select(SessionRecord).where(SessionRecord.jti == p.jti)).scalar_one_or_none()
    if s:
        s.revoked_at = datetime.now(timezone.utc)
    log_action(db, company_id=p.company_id, principal=p, action="Signed out", resource="session", resource_type="auth", result="SUCCESS")
    db.commit()
    return {"ok": True}


@router.get("/me")
def me(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    s = db.execute(select(SessionRecord).where(SessionRecord.jti == p.jti)).scalar_one()
    return principal_json(p, db.get(Company, p.company_id), s.auth_method)
