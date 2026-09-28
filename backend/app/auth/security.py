import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import get_settings

settings = get_settings()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=10)).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def new_jti() -> str:
    return secrets.token_hex(16)


def create_access_token(*, user_id: int, company_id: int, role: str, jti: str) -> tuple[str, datetime]:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.session_ttl_minutes)
    payload = {"sub": str(user_id), "cid": company_id, "role": role, "jti": jti, "exp": exp}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm), exp


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
