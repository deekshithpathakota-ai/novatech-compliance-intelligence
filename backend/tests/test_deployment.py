"""Deployment hardening: URL normalisation, CORS parsing, JWT validation, health/readiness, CORS headers."""
import pytest

from app.config import Settings, normalize_database_url

STRONG = "x" * 40


@pytest.mark.parametrize("raw,expected", [
    ("postgres://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
    ("postgresql://u:p@h/db?sslmode=require", "postgresql+psycopg://u:p@h/db?sslmode=require"),
    ("postgresql+psycopg2://u@h/db", "postgresql+psycopg://u@h/db"),
    ("postgresql+psycopg://u@h/db", "postgresql+psycopg://u@h/db"),
    ("  postgresql://u@h/db \n", "postgresql+psycopg://u@h/db"),
    ("sqlite:///./x.db", "sqlite:///./x.db"),
])
def test_database_url_normalisation(raw, expected):
    assert normalize_database_url(raw) == expected
    assert Settings(database_url=raw, jwt_secret=STRONG).database_url == expected


def test_cors_origins_parsing():
    s = Settings(cors_origins=" https://a.vercel.app/ ,http://localhost:5173,,*,https://a.vercel.app", jwt_secret=STRONG)
    assert s.cors_origin_list == ["https://a.vercel.app", "http://localhost:5173"]


def test_production_rejects_placeholder_or_short_jwt_secret():
    for bad in ("change-me-in-env", "short-secret", ""):
        with pytest.raises(RuntimeError, match="JWT_SECRET"):
            Settings(environment="production", jwt_secret=bad, cors_origins="https://a.vercel.app").validate_runtime()
    Settings(environment="production", jwt_secret=STRONG, cors_origins="https://a.vercel.app").validate_runtime()
    Settings(environment="development", jwt_secret="change-me-in-env").validate_runtime()  # dev: warning only


def test_production_requires_cors_origins():
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        Settings(environment="production", jwt_secret=STRONG, cors_origins="").validate_runtime()


def test_health_and_readiness(client):
    assert client.get("/api/health").json()["status"] == "ok"
    r = client.get("/api/health/ready")
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ok"
    assert body["checks"]["database"] == "ok" and body["checks"]["pgvector"] == "ok" and body["checks"]["demo_data"] == "ok"
    assert "secret" not in r.text.lower() and "postgres" not in r.text.lower()


def test_cors_preflight_allows_configured_origin_only(client):
    ok = client.options("/api/auth/login", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
                                                     "Access-Control-Request-Headers": "authorization,content-type"})
    assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == "http://localhost:5173"
    bad = client.options("/api/auth/login", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers
