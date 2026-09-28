"""Tenant isolation helpers. All tenant-owned reads go through these so company_id is never optional."""
from typing import TypeVar

from fastapi import HTTPException
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

T = TypeVar("T")


def scoped(model: type[T], company_id: int) -> Select:
    if company_id is None:
        raise ValueError("company_id is required for tenant-scoped queries")
    return select(model).where(model.company_id == company_id)  # type: ignore[attr-defined]


def get_owned(db: Session, model: type[T], obj_id: int, company_id: int, label: str = "Resource") -> T:
    """Fetch by id *and* tenant. A record owned by another tenant is indistinguishable from a missing one."""
    obj = db.execute(scoped(model, company_id).where(model.id == obj_id)).scalar_one_or_none()  # type: ignore[attr-defined]
    if obj is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": f"{label} not found."})
    return obj


def get_by_code(db: Session, model: type[T], code: str, company_id: int) -> T | None:
    return db.execute(scoped(model, company_id).where(model.code == code)).scalar_one_or_none()  # type: ignore[attr-defined]
