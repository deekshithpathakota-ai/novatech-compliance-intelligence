"""Connector abstraction. Business logic talks to this interface, never to a vendor SDK directly.

All connectors shipped in the prototype are *Demo Connectors*: they operate on NovaTech demo tables
and never touch real systems.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, IamAccount, Notification


class ConnectorUnavailable(RuntimeError):
    """Raised when a connector's backing service cannot be reached (drives self-recovery)."""


class Connector(ABC):
    key: str
    name: str
    kind: str
    simulated = True

    def __init__(self, db: Session, company_id: int):
        self.db, self.company_id = db, company_id

    def _faults(self) -> dict:
        c = self.db.get(Company, self.company_id)
        return ((c.settings or {}).get("fault_injection") or {}) if c else {}

    def check_available(self) -> None:
        if self._faults().get(self.key):
            raise ConnectorUnavailable(f"{self.name} unavailable (fault injection enabled in Settings)")

    @abstractmethod
    def get_data(self, query: str, **params) -> dict: ...

    def create_action(self, action: str, **params) -> dict:
        raise NotImplementedError

    def update_data(self, entity: str, **params) -> dict:
        raise NotImplementedError

    def verify_action(self, action: str, **params) -> dict:
        raise NotImplementedError


INACTIVE_DAYS = 90


class IamDemoConnector(Connector):
    key, name, kind = "iam", "IAM Demo Connector", "identity"

    def _accounts(self):
        return self.db.execute(select(IamAccount).where(IamAccount.company_id == self.company_id)).scalars().all()

    def _inactive(self, accts):
        cutoff = datetime.now(timezone.utc) - timedelta(days=INACTIVE_DAYS)
        return [a for a in accts if a.status == "ACTIVE" and (
            a.employment_status == "TERMINATED" or a.last_login_at is None or
            (a.last_login_at if a.last_login_at.tzinfo else a.last_login_at.replace(tzinfo=timezone.utc)) < cutoff)]

    def get_data(self, query: str, **params) -> dict:
        self.check_available()
        accts = self._accounts()
        inactive = self._inactive(accts)
        if query == "access_report":
            return {"total_accounts": len(accts), "active_accounts": sum(a.status == "ACTIVE" for a in accts),
                    "inactive_accounts": len(inactive),
                    "privileged_accounts": sum(a.is_privileged and a.status == "ACTIVE" for a in accts),
                    "terminated_still_active": sum(a.employment_status == "TERMINATED" for a in inactive),
                    "inactive_account_ids": [a.id for a in inactive],
                    "inactive_sample": [{"username": a.username, "department": a.department, "system": a.system,
                                         "privileged": a.is_privileged,
                                         "last_login": a.last_login_at.date().isoformat() if a.last_login_at else None}
                                        for a in inactive[:25]],
                    "generated_at": datetime.now(timezone.utc).isoformat(), "connector": self.name, "simulated": True}
        if query == "privileged_accounts":
            priv = [a for a in accts if a.is_privileged and a.status == "ACTIVE"]
            return {"count": len(priv), "accounts": [{"username": a.username, "system": a.system} for a in priv]}
        raise ValueError(f"unknown query {query}")

    def create_action(self, action: str, **params) -> dict:
        self.check_available()
        if action != "disable_accounts":
            raise ValueError(f"unsupported action {action}")
        ids = set(params.get("account_ids") or [])
        now = datetime.now(timezone.utc)
        changed = []
        for a in self._accounts():
            if a.id in ids and a.status == "ACTIVE":
                a.status, a.disabled_at = "DISABLED", now
                changed.append(a.username)
        self.db.flush()
        return {"disabled": len(changed), "usernames": changed, "simulated": True, "connector": self.name}

    def verify_action(self, action: str, **params) -> dict:
        self.check_available()
        before = params.get("before", 0)
        after = len(self._inactive(self._accounts()))
        return {"check": "inactive_accounts", "before": before, "after": after, "expected": 0, "passed": after == 0}


class NotificationDemoConnector(Connector):
    key, name, kind = "email", "Demo Email Service", "notification"

    def get_data(self, query: str, **params) -> dict:
        return {}

    def create_action(self, action: str, **params) -> dict:
        self.check_available()
        n = Notification(company_id=self.company_id, user_id=params.get("user_id"), kind=params.get("kind", "request"),
                         title=params["title"], body=params.get("body", ""), severity=params.get("severity", "info"),
                         link=params.get("link"), is_simulated_delivery=True)
        self.db.add(n)
        self.db.flush()
        return {"notification_id": n.id, "delivery": "Demo Notification — not sent externally", "simulated": True}


class JiraDemoConnector(Connector):
    key, name, kind = "jira", "Jira Demo Connector", "ticketing"

    def get_data(self, query: str, **params) -> dict:
        return {}

    def create_action(self, action: str, **params) -> dict:
        self.check_available()
        import hashlib

        key = "COMP-" + str(int(hashlib.md5(params.get("title", "").encode()).hexdigest()[:4], 16) % 900 + 100)
        return {"ticket": key, "url": None, "simulated": True, "note": "Demo Connector — no real Jira ticket created"}


class EvidenceStoreConnector(Connector):
    """Evidence service used during verification; can be failed on purpose to demo self-recovery."""

    key, name, kind = "evidence_store", "Evidence Service", "storage"
    simulated = False

    def get_data(self, query: str, **params) -> dict:
        self.check_available()
        return {"ok": True}


CONNECTOR_CATALOG = [
    {"key": "iam", "name": "IAM Demo Connector", "kind": "identity", "status": "DEMO"},
    {"key": "jira", "name": "Jira Demo Connector", "kind": "ticketing", "status": "DEMO"},
    {"key": "email", "name": "Demo Email Service", "kind": "notification", "status": "DEMO"},
    {"key": "sso", "name": "Demo SAML SSO", "kind": "identity", "status": "DEMO"},
    {"key": "evidence_store", "name": "Evidence Service", "kind": "storage", "status": "CONNECTED"},
    {"key": "servicenow", "name": "ServiceNow Demo Connector", "kind": "ticketing", "status": "REQUIRES_CONFIGURATION"},
    {"key": "gdrive", "name": "Google Drive Demo Connector", "kind": "documents", "status": "REQUIRES_CONFIGURATION"},
    {"key": "sharepoint", "name": "Microsoft SharePoint Demo Connector", "kind": "documents", "status": "UNAVAILABLE"},
]

REGISTRY = {c.key: c for c in (IamDemoConnector, NotificationDemoConnector, JiraDemoConnector, EvidenceStoreConnector)}


def get_connector(key: str, db: Session, company_id: int) -> Connector:
    return REGISTRY[key](db, company_id)
