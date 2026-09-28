"""Application configuration. All secrets and model names come from the environment."""
import logging
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_SECRETS = {"change-me-in-env", "replace-with-a-long-random-string-at-least-32-bytes", "secret", "changeme"}


def normalize_database_url(url: str) -> str:
    """Accept the URL formats hosting providers hand out and route them to the installed psycopg (v3) driver.

    postgres://…  postgresql://…  postgresql+psycopg2://…  ->  postgresql+psycopg://…
    """
    url = (url or "").strip()
    for prefix in ("postgres://", "postgresql://", "postgresql+psycopg2://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "NovaTech Compliance Intelligence"
    environment: str = "demo"  # demo | production
    demo_mode: bool = True

    database_url: str = "postgresql+psycopg://postgres@localhost:5432/novatech"
    redis_url: str | None = None
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_recycle_seconds: int = 300  # managed Postgres (Render/Neon/Supabase) drops idle connections

    jwt_secret: str = "change-me-in-env"  # overridden by JWT_SECRET
    jwt_algorithm: str = "HS256"
    session_ttl_minutes: int = 480

    # --- AI / model routing (never hardcode model names in business logic) ---
    openai_api_key: str | None = None
    openai_model: str | None = None  # reasoning-capable model for analysis/orchestration
    openai_fast_model: str | None = None  # cheap model for intent classification
    openai_embedding_model: str | None = None
    embedding_provider: str = "hash"  # hash | openai
    embedding_dim: int = 256

    # --- Storage ---
    storage_bucket: str | None = None
    storage_endpoint: str | None = None
    storage_access_key: str | None = None
    storage_secret_key: str | None = None
    local_storage_dir: str = "./storage"

    # --- Agent behaviour ---
    demo_step_delay_ms: int = 350  # pacing so judges can follow the live activity panel
    rate_limit_per_minute: int = 60
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    cors_origin_regex: str | None = None  # optional, e.g. ^https://novatech-.*\.vercel\.app$ for Vercel preview URLs

    @field_validator("database_url")
    @classmethod
    def _normalize_db(cls, v: str) -> str:
        return normalize_database_url(v)

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in ("production", "prod")

    @property
    def cors_origin_list(self) -> list[str]:
        """Comma-separated origins; whitespace and trailing slashes are removed (browsers never send them)."""
        out: list[str] = []
        for o in self.cors_origins.split(","):
            o = o.strip().rstrip("/")
            if o and o != "*" and o not in out:
                out.append(o)
        return out

    def jwt_secret_problem(self) -> str | None:
        s = (self.jwt_secret or "").strip()
        if not s or s.lower() in _PLACEHOLDER_SECRETS:
            return "JWT_SECRET is not set (still the placeholder value)"
        if len(s) < 32:
            return "JWT_SECRET is shorter than 32 characters"
        return None

    def validate_runtime(self) -> None:
        """Fail fast with a clear message on unsafe production configuration. Never logs secret values."""
        log = logging.getLogger("novatech.config")
        problem = self.jwt_secret_problem()
        if problem and self.is_production:
            raise RuntimeError(f"Unsafe configuration: {problem}. Set JWT_SECRET to a random value of 32+ characters "
                               "(for example: python -c \"import secrets; print(secrets.token_urlsafe(48))\").")
        if problem:
            log.warning("%s — acceptable for local development only (ENVIRONMENT=%s).", problem, self.environment)
        if "*" in [o.strip() for o in self.cors_origins.split(",")]:
            log.warning("CORS_ORIGINS contains '*', which is ignored because the API uses credentials; list origins explicitly.")
        if self.is_production and not self.cors_origin_list and not self.cors_origin_regex:
            raise RuntimeError("Unsafe configuration: CORS_ORIGINS is empty. Set it to your frontend origin, e.g. https://your-app.vercel.app")

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key and self.openai_model)

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")


@lru_cache
def get_settings() -> Settings:
    return Settings()
