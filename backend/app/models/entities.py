"""Relational compliance knowledge model.

FRAMEWORK -> REQUIREMENT -> CONTROL -> EVIDENCE -> CONTROL TEST -> FINDING -> REMEDIATION -> VERIFICATION

Every tenant-owned table carries `company_id`; the query layer (app.services.tenancy) always filters on it.
"""
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import get_settings
from app.database.session import Base, EmbeddingType, TimestampMixin, utcnow

EMBED_DIM = get_settings().embedding_dim


def company_fk() -> Mapped[int]:
    return mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)


# ---------------------------------------------------------------- organisation / identity
class Company(TimestampMixin, Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)


class Department(TimestampMixin, Base):
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    name: Mapped[str] = mapped_column(String(120))


class Role(TimestampMixin, Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")


class Permission(TimestampMixin, Base):
    __tablename__ = "permissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")


class RolePermission(Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_id: Mapped[int] = mapped_column(ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True)


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    email: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(150))
    title: Mapped[str] = mapped_column(String(150), default="")
    password_hash: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo_persona: Mapped[bool] = mapped_column(Boolean, default=False)

    role: Mapped[Role] = relationship(lazy="joined")
    department: Mapped[Department | None] = relationship(lazy="joined")


class SessionRecord(TimestampMixin, Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    company_id: Mapped[int] = company_fk()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auth_method: Mapped[str] = mapped_column(String(40), default="demo")
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


# ---------------------------------------------------------------- frameworks & requirements
class Framework(TimestampMixin, Base):
    __tablename__ = "frameworks"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(150))
    version: Mapped[str] = mapped_column(String(40), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    is_demo_mapping: Mapped[bool] = mapped_column(Boolean, default=True)


class Requirement(TimestampMixin, Base):
    __tablename__ = "requirements"
    __table_args__ = (UniqueConstraint("company_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    framework_id: Mapped[int] = mapped_column(ForeignKey("frameworks.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(250))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(80))
    current_version: Mapped[str] = mapped_column(String(20), default="1.0")
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active")  # active | changed | retired

    framework: Mapped[Framework] = relationship(lazy="joined")


class RequirementVersion(TimestampMixin, Base):
    __tablename__ = "requirement_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), index=True)
    version: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text)
    change_summary: Mapped[str] = mapped_column(Text, default="")
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)  # e.g. {"max_interval_days": 90}


class RequirementControlMap(Base):
    __tablename__ = "requirement_control_map"
    __table_args__ = (UniqueConstraint("requirement_id", "control_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), index=True)
    control_id: Mapped[int] = mapped_column(ForeignKey("controls.id", ondelete="CASCADE"), index=True)


# ---------------------------------------------------------------- controls
class Control(TimestampMixin, Base):
    __tablename__ = "controls"
    __table_args__ = (UniqueConstraint("company_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    domain: Mapped[str] = mapped_column(String(80))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    frequency_days: Mapped[int] = mapped_column(Integer, default=90)
    criticality: Mapped[int] = mapped_column(Integer, default=3)  # 1..5
    automation: Mapped[str] = mapped_column(String(20), default="manual")
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_result: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # persisted operational status written by backend workflows (tests / verification)
    status: Mapped[str] = mapped_column(String(30), default="NOT_TESTED")
    test_procedure: Mapped[list] = mapped_column(JSON, default=list)
    implementation_notes: Mapped[str] = mapped_column(Text, default="")

    department: Mapped[Department | None] = relationship(lazy="joined")


class ControlOwner(TimestampMixin, Base):
    __tablename__ = "control_owners"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    control_id: Mapped[int] = mapped_column(ForeignKey("controls.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    unassigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped[User] = relationship(lazy="joined")


class ControlTest(TimestampMixin, Base):
    __tablename__ = "control_tests"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    code: Mapped[str] = mapped_column(String(20), index=True)
    control_id: Mapped[int] = mapped_column(ForeignKey("controls.id", ondelete="CASCADE"), index=True)
    audit_id: Mapped[int | None] = mapped_column(ForeignKey("audits.id"), nullable=True)
    tested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    tester_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    tester_type: Mapped[str] = mapped_column(String(20), default="user")  # user | agent | auditor
    result: Mapped[str] = mapped_column(String(30))  # PASS | FAIL | PARTIAL | INSUFFICIENT_EVIDENCE
    method: Mapped[str] = mapped_column(String(40), default="inspection")
    questions: Mapped[list] = mapped_column(JSON, default=list)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    agent_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


# ---------------------------------------------------------------- documents & RAG
class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    code: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(250))
    document_type: Mapped[str] = mapped_column(String(50))  # policy | evidence | report | procedure | other
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    classification: Mapped[str] = mapped_column(String(30), default="internal")  # public|internal|confidential|restricted
    framework_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    version: Mapped[str] = mapped_column(String(20), default="1.0")
    source: Mapped[str] = mapped_column(String(60), default="upload")
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="indexed")  # processing|indexed|flagged|failed
    mime_type: Mapped[str] = mapped_column(String(100), default="text/plain")
    page_count: Mapped[int] = mapped_column(Integer, default=1)
    security_flags: Mapped[list] = mapped_column(JSON, default=list)
    required_permission: Mapped[str | None] = mapped_column(String(80), nullable=True)
    storage_path: Mapped[str | None] = mapped_column(String(400), nullable=True)


class DocumentVersion(TimestampMixin, Base):
    __tablename__ = "document_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    version: Mapped[str] = mapped_column(String(20))
    sha256: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str | None] = mapped_column(String(400), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class DocumentChunk(TimestampMixin, Base):
    __tablename__ = "document_chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    page: Mapped[int] = mapped_column(Integer, default=1)
    section: Mapped[str] = mapped_column(String(250), default="")
    content: Mapped[str] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(String(30), default="internal")
    is_quarantined: Mapped[bool] = mapped_column(Boolean, default=False)  # suspicious instructions isolated
    token_count: Mapped[int] = mapped_column(Integer, default=0)


class DocumentEmbedding(TimestampMixin, Base):
    __tablename__ = "document_embeddings"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    chunk_id: Mapped[int] = mapped_column(ForeignKey("document_chunks.id", ondelete="CASCADE"), unique=True)
    embedding = mapped_column(EmbeddingType(EMBED_DIM))
    model: Mapped[str] = mapped_column(String(80))


# ---------------------------------------------------------------- evidence
class Evidence(TimestampMixin, Base):
    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    code: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(250))
    description: Mapped[str] = mapped_column(Text, default="")
    control_id: Mapped[int] = mapped_column(ForeignKey("controls.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(80), default="manual upload")
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verification_status: Mapped[str] = mapped_column(String(20), default="verified")  # verified|unverified|rejected
    sha256: Mapped[str] = mapped_column(String(64))
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audit_id: Mapped[int | None] = mapped_column(ForeignKey("audits.id"), nullable=True)
    is_conflicting: Mapped[bool] = mapped_column(Boolean, default=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)  # superseded evidence stays for history
    completeness: Mapped[float] = mapped_column(Float, default=1.0)
    extracted: Mapped[dict] = mapped_column(JSON, default=dict)  # structured facts (e.g. inactive_accounts)

    control: Mapped[Control] = relationship(lazy="joined")


class EvidenceVersion(TimestampMixin, Base):
    __tablename__ = "evidence_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    evidence_id: Mapped[int] = mapped_column(ForeignKey("evidence.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sha256: Mapped[str] = mapped_column(String(64))
    note: Mapped[str] = mapped_column(Text, default="")


# ---------------------------------------------------------------- audits & findings
class Audit(TimestampMixin, Base):
    __tablename__ = "audits"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    code: Mapped[str] = mapped_column(String(30), index=True)
    name: Mapped[str] = mapped_column(String(200))
    framework_id: Mapped[int] = mapped_column(ForeignKey("frameworks.id"))
    audit_type: Mapped[str] = mapped_column(String(30))  # external | internal | surveillance | agent_review
    status: Mapped[str] = mapped_column(String(30))  # planned | in_progress | completed
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    auditor: Mapped[str] = mapped_column(String(150), default="")
    outcome: Mapped[str | None] = mapped_column(String(60), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")

    framework: Mapped[Framework] = relationship(lazy="joined")


class AuditScope(Base):
    __tablename__ = "audit_scope"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    control_id: Mapped[int | None] = mapped_column(ForeignKey("controls.id"), nullable=True)
    requirement_id: Mapped[int | None] = mapped_column(ForeignKey("requirements.id"), nullable=True)


class Finding(TimestampMixin, Base):
    __tablename__ = "findings"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    code: Mapped[str] = mapped_column(String(30), index=True)
    title: Mapped[str] = mapped_column(String(250))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(60))  # stable key used for recurrence detection
    control_id: Mapped[int] = mapped_column(ForeignKey("controls.id"), index=True)
    requirement_id: Mapped[int | None] = mapped_column(ForeignKey("requirements.id"), nullable=True)
    audit_id: Mapped[int | None] = mapped_column(ForeignKey("audits.id"), nullable=True)
    severity: Mapped[str] = mapped_column(String(20))  # LOW | MEDIUM | HIGH | CRITICAL
    status: Mapped[str] = mapped_column(String(30), default="OPEN")
    # OPEN | IN_REMEDIATION | READY_FOR_CLOSURE | CLOSED | RISK_ACCEPTED
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    root_cause: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(30), default="audit")  # audit | agent | manual
    previous_finding_id: Mapped[int | None] = mapped_column(ForeignKey("findings.id"), nullable=True)

    control: Mapped[Control] = relationship(lazy="joined")
    owner: Mapped[User | None] = relationship(lazy="joined")


class AuditFinding(Base):
    __tablename__ = "audit_findings"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), index=True)


class FindingComment(TimestampMixin, Base):
    __tablename__ = "finding_comments"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    body: Mapped[str] = mapped_column(Text)


class FindingHistory(TimestampMixin, Base):
    __tablename__ = "finding_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), index=True)
    event: Mapped[str] = mapped_column(String(60))
    from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(20), default="user")
    note: Mapped[str] = mapped_column(Text, default="")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------- remediation & verification
class RemediationPlan(TimestampMixin, Base):
    __tablename__ = "remediation_plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    code: Mapped[str] = mapped_column(String(30), index=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(250))
    rationale: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="IN_PROGRESS")
    # DRAFT | PENDING_APPROVAL | IN_PROGRESS | VERIFYING | COMPLETED | FAILED | CANCELLED
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_by_agent: Mapped[bool] = mapped_column(Boolean, default=False)
    agent_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary_of_actions: Mapped[str] = mapped_column(Text, default="")
    context: Mapped[dict] = mapped_column(JSON, default=dict)  # working state (e.g. before-counts for verification)


class RemediationTask(TimestampMixin, Base):
    __tablename__ = "remediation_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    plan_id: Mapped[int] = mapped_column(ForeignKey("remediation_plans.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(250))
    description: Mapped[str] = mapped_column(Text, default="")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    priority: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    # PENDING | IN_PROGRESS | AWAITING_APPROVAL | COMPLETED | BLOCKED | FAILED | CANCELLED
    depends_on_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_required: Mapped[str] = mapped_column(String(250), default="")
    risk_level: Mapped[str] = mapped_column(String(20), default="LOW")
    action_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    action_params: Mapped[dict] = mapped_column(JSON, default=dict)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    owner: Mapped[User | None] = relationship(lazy="joined")


class RemediationAction(TimestampMixin, Base):
    __tablename__ = "remediation_actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    task_id: Mapped[int] = mapped_column(ForeignKey("remediation_tasks.id", ondelete="CASCADE"), index=True)
    action_type: Mapped[str] = mapped_column(String(60))
    connector: Mapped[str] = mapped_column(String(60), default="")
    executed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    executed_by_agent: Mapped[bool] = mapped_column(Boolean, default=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(20))  # SUCCEEDED | FAILED
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    approval_id: Mapped[int | None] = mapped_column(ForeignKey("approval_requests.id"), nullable=True)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True)


class VerificationRecord(TimestampMixin, Base):
    __tablename__ = "verification_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    code: Mapped[str] = mapped_column(String(30), index=True)
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("remediation_plans.id"), nullable=True)
    finding_id: Mapped[int | None] = mapped_column(ForeignKey("findings.id"), nullable=True)
    control_id: Mapped[int | None] = mapped_column(ForeignKey("controls.id"), nullable=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    result: Mapped[str] = mapped_column(String(20))  # PASSED | FAILED | INCONCLUSIVE
    checks: Mapped[list] = mapped_column(JSON, default=list)  # [{name, expected, actual, passed}]
    evidence_id: Mapped[int | None] = mapped_column(ForeignKey("evidence.id"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    verified_by_agent: Mapped[bool] = mapped_column(Boolean, default=True)


# ---------------------------------------------------------------- policies & change
class Policy(TimestampMixin, Base):
    __tablename__ = "policies"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    code: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(200))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    current_version: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")  # ACTIVE | REVIEW_DUE | EXPIRED | CHANGE_REQUIRED
    review_frequency_days: Mapped[int] = mapped_column(Integer, default=365)
    last_reviewed_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)


class PolicyVersion(TimestampMixin, Base):
    __tablename__ = "policy_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    policy_id: Mapped[int] = mapped_column(ForeignKey("policies.id", ondelete="CASCADE"), index=True)
    version: Mapped[str] = mapped_column(String(20))
    summary: Mapped[str] = mapped_column(Text, default="")
    change_summary: Mapped[str] = mapped_column(Text, default="")
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)


class ComplianceEvent(TimestampMixin, Base):
    __tablename__ = "compliance_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    title: Mapped[str] = mapped_column(String(250))
    description: Mapped[str] = mapped_column(Text, default="")
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entity_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    control_id: Mapped[int | None] = mapped_column(ForeignKey("controls.id"), nullable=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(20), default="user")
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class RegulatoryChange(TimestampMixin, Base):
    __tablename__ = "regulatory_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    code: Mapped[str] = mapped_column(String(20))
    requirement_id: Mapped[int | None] = mapped_column(ForeignKey("requirements.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(250))
    change_type: Mapped[str] = mapped_column(String(20))  # NEW | UPDATED
    old_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    new_version: Mapped[str] = mapped_column(String(20))
    summary: Mapped[str] = mapped_column(Text)
    effective_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(40), default="IMPACT_ASSESSMENT_REQUIRED")
    risk: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    action_required: Mapped[str] = mapped_column(Text, default="")
    source_label: Mapped[str] = mapped_column(String(120), default="Synthetic demo change record")


class RiskAssessment(TimestampMixin, Base):
    __tablename__ = "risk_assessments"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    entity_type: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    score: Mapped[float] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String(20))
    factors: Mapped[dict] = mapped_column(JSON, default=dict)
    model_version: Mapped[str] = mapped_column(String(40))
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    agent_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


# ---------------------------------------------------------------- agent runtime
class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(250))


class Message(TimestampMixin, Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    cards: Mapped[list] = mapped_column(JSON, default=list)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AgentRun(TimestampMixin, Base):
    __tablename__ = "agent_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    conversation_id: Mapped[int | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    objective: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(30), default="RUNNING")
    # RUNNING | AWAITING_APPROVAL | COMPLETED | FAILED
    plan: Mapped[list] = mapped_column(JSON, default=list)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engine: Mapped[str] = mapped_column(String(40), default="deterministic")  # deterministic | openai-agents
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentStep(Base):
    __tablename__ = "agent_steps"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(60))
    phase: Mapped[str] = mapped_column(String(30), default="")
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20))  # running | done | warning | failed | info
    tool_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ToolCall(Base):
    __tablename__ = "tool_calls"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=True, index=True)
    tool_name: Mapped[str] = mapped_column(String(80))
    args: Mapped[dict] = mapped_column(JSON, default=dict)
    authorized: Mapped[bool] = mapped_column(Boolean)
    risk_level: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))  # SUCCEEDED | FAILED | DENIED | APPROVAL_REQUIRED
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApprovalRequest(TimestampMixin, Base):
    __tablename__ = "approval_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    code: Mapped[str] = mapped_column(String(30), index=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("remediation_plans.id"), nullable=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("remediation_tasks.id"), nullable=True)
    action_type: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(250))
    reason: Mapped[str] = mapped_column(Text)
    risk_level: Mapped[str] = mapped_column(String(20))
    affected: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    required_permission: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    # PENDING | APPROVED | REJECTED | CHANGES_REQUESTED | EXECUTED | EXECUTION_FAILED
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    requested_by_agent: Mapped[bool] = mapped_column(Boolean, default=True)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, default="")


# ---------------------------------------------------------------- audit trail / security / misc
class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_company_created", "company_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(20), default="user")  # user | agent | system
    actor_label: Mapped[str] = mapped_column(String(150), default="")
    role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    action: Mapped[str] = mapped_column(String(200))
    resource: Mapped[str | None] = mapped_column(String(120), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    authorization_result: Mapped[str] = mapped_column(String(20), default="ALLOWED")
    tool_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    agent_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approval_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SecurityEvent(Base):
    __tablename__ = "security_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    severity: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")  # OPEN | INVESTIGATING | RESOLVED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(250))
    body: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(20), default="info")
    link: Mapped[str | None] = mapped_column(String(250), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    is_simulated_delivery: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Integration(TimestampMixin, Base):
    __tablename__ = "integrations"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    key: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40))  # CONNECTED | DEMO | UNAVAILABLE | REQUIRES_CONFIGURATION
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryRecord(TimestampMixin, Base):
    __tablename__ = "memory_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    category: Mapped[str] = mapped_column(String(30), index=True)
    # REGULATORY | CONTROL | AUDIT | REMEDIATION | EVIDENCE | POLICY | BEHAVIOR | VERIFICATION
    subject_type: Mapped[str] = mapped_column(String(30))
    subject_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subject_code: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    summary: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    source_type: Mapped[str] = mapped_column(String(30))
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_label: Mapped[str] = mapped_column(String(150), default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(60), nullable=True)
    verification: Mapped[str | None] = mapped_column(String(40), nullable=True)
    importance: Mapped[int] = mapped_column(Integer, default=3)
    written_by: Mapped[str] = mapped_column(String(30), default="system")  # system | agent | seed


class Report(TimestampMixin, Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    code: Mapped[str] = mapped_column(String(30))
    report_type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(250))
    audit_id: Mapped[int | None] = mapped_column(ForeignKey("audits.id"), nullable=True)
    generated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    agent_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class IamAccount(TimestampMixin, Base):
    """Data behind the *IAM Demo Connector*. Never a real identity system."""

    __tablename__ = "iam_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    username: Mapped[str] = mapped_column(String(80))
    display_name: Mapped[str] = mapped_column(String(150))
    department: Mapped[str] = mapped_column(String(80))
    system: Mapped[str] = mapped_column(String(60))
    is_privileged: Mapped[bool] = mapped_column(Boolean, default=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")  # ACTIVE | DISABLED
    employment_status: Mapped[str] = mapped_column(String(20), default="EMPLOYED")  # EMPLOYED | TERMINATED
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvidenceRequest(TimestampMixin, Base):
    """Evidence request workflow: agent/officer asks a control owner for specific evidence (Demo Notification)."""

    __tablename__ = "evidence_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = company_fk()
    code: Mapped[str] = mapped_column(String(30), index=True)
    control_id: Mapped[int] = mapped_column(ForeignKey("controls.id", ondelete="CASCADE"), index=True)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    requested_by_agent: Mapped[bool] = mapped_column(Boolean, default=False)
    recipient_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    evidence_required: Mapped[str] = mapped_column(String(250))
    reason: Mapped[str] = mapped_column(Text)
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")  # OPEN | FULFILLED | CANCELLED
    fulfilled_evidence_id: Mapped[int | None] = mapped_column(ForeignKey("evidence.id"), nullable=True)
    notification_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
