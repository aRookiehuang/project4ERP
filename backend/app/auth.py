import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from fastapi import Request
from sqlalchemy import delete, select

from .errors import DomainError
from .models import sessions, users


def hash_password(password: str, salt: str | None = None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"scrypt${salt}${digest}"


def verify_password(password: str, encoded: str):
    try:
        _, salt, _ = encoded.split("$")
        return hmac.compare_digest(hash_password(password, salt), encoded)
    except (ValueError, TypeError):
        return False


def create_session(db, user_id, hours):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with db.begin() as conn:
        conn.execute(
            sessions.insert().values(
                id=hashlib.sha256(token.encode()).hexdigest(),
                user_id=user_id,
                csrf=csrf,
                expires_at=datetime.utcnow() + timedelta(hours=hours),
            )
        )
    return token, csrf


def current_user(request: Request):
    token = request.cookies.get("erp_session", "")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with request.app.state.db.app.connect() as conn:
        row = (
            conn.execute(
                select(users.c.id, users.c.username, users.c.role, sessions.c.csrf)
                .join(sessions, sessions.c.user_id == users.c.id)
                .where(sessions.c.id == token_hash, sessions.c.expires_at > datetime.utcnow())
            )
            .mappings()
            .first()
        )
    if not row:
        raise DomainError("UNAUTHORIZED", "请先登录。", 401)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), row["csrf"]):
            raise DomainError("FORBIDDEN", "会话校验失败，请刷新后重试。", 403)
    return dict(row)


def logout(request: Request):
    token_hash = hashlib.sha256(request.cookies.get("erp_session", "").encode()).hexdigest()
    with request.app.state.db.app.begin() as conn:
        conn.execute(delete(sessions).where(sessions.c.id == token_hash))
