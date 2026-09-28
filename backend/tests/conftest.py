import os
import time

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://postgres@localhost:5432/novatech_test")
os.environ["DEMO_STEP_DELAY_MS"] = "0"
os.environ["DISABLE_SCHEDULER"] = "1"
os.environ["RATE_LIMIT_SCALE"] = "20"
os.environ["OPENAI_API_KEY"] = ""
os.environ["JWT_SECRET"] = "test-secret-not-for-production-use-only-0123456789"
os.environ["LOCAL_STORAGE_DIR"] = "/tmp/novatech-test-storage"

from fastapi.testclient import TestClient  # noqa: E402

from app.database.init import reset_schema  # noqa: E402
from app.database.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed.seeder import seed  # noqa: E402


def _ensure_db():
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgresql"):
        from sqlalchemy import create_engine, text

        admin = create_engine(url.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
        with admin.connect() as c:
            if not c.execute(text("SELECT 1 FROM pg_database WHERE datname='novatech_test'")).scalar():
                c.execute(text("CREATE DATABASE novatech_test"))
        admin.dispose()


def reseed():
    reset_schema(engine)
    with SessionLocal() as db:
        return seed(db)


@pytest.fixture(scope="session", autouse=True)
def seeded():
    _ensure_db()
    return reseed()


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


_tokens: dict[str, str] = {}


def token_for(client, role: str | None = None, email: str | None = None) -> str:
    key = role or email
    if key not in _tokens:
        body = {"mode": "demo", "role": role} if role else {"mode": "password", "email": email, "password": "NovaTech-Demo-2026"}
        r = client.post("/api/auth/login", json=body)
        assert r.status_code == 200, r.text
        _tokens[key] = r.json()["token"]
    return _tokens[key]


def as_role(client, role):
    return {"Authorization": f"Bearer {token_for(client, role=role)}"}


def as_email(client, email):
    return {"Authorization": f"Bearer {token_for(client, email=email)}"}


def wait_run(client, headers, run_id, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = client.get(f"/api/agent/runs/{run_id}", headers=headers).json()
        if r["status"] in ("COMPLETED", "FAILED", "AWAITING_APPROVAL") and r["completed_at"]:
            return r
        time.sleep(0.1)
    raise AssertionError("agent run did not finish")
