"""Schema bootstrap helpers shared by the seed script, tests and the Alembic migration."""
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.database.session import Base
import app.models  # noqa: F401  (register tables)

POSTGRES_EXTRA = [
    "CREATE INDEX IF NOT EXISTS ix_document_embeddings_hnsw ON document_embeddings USING hnsw (embedding vector_cosine_ops)",
    "CREATE INDEX IF NOT EXISTS ix_document_chunks_fts ON document_chunks USING gin (to_tsvector('english', content))",
    "CREATE INDEX IF NOT EXISTS ix_findings_company_status ON findings (company_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_evidence_company_current ON evidence (company_id, is_current)",
    "CREATE INDEX IF NOT EXISTS ix_compliance_events_company_time ON compliance_events (company_id, occurred_at DESC)",
]


def ensure_extensions(engine: Engine) -> None:
    if engine.dialect.name == "postgresql":
        with engine.begin() as c:
            c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))


def create_extra_indexes(engine: Engine) -> None:
    if engine.dialect.name == "postgresql":
        with engine.begin() as c:
            for stmt in POSTGRES_EXTRA:
                c.execute(text(stmt))


def reset_schema(engine: Engine) -> None:
    ensure_extensions(engine)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    create_extra_indexes(engine)
