"""Authentication: password hashing (PBKDF2) and cookie sessions."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request

from backend import config
from backend.database import get_db

_ITERATIONS = 240_000


def _utcnow() -> datetime:
    """Current UTC time as a naive datetime (stored as ISO text in SQLite)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, expected = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(digest.hex(), expected)   # constant-time comparison
    except (ValueError, TypeError):
        return False


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = (_utcnow() + timedelta(days=config.SESSION_DAYS)).isoformat()
    with get_db() as db:
        db.execute("INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
                   (token, user_id, expires))
    return token


def delete_session(token: str) -> None:
    with get_db() as db:
        db.execute("DELETE FROM sessions WHERE token = ?", (token,))


def current_user(request: Request) -> dict:
    """FastAPI dependency: returns the logged-in user or raises 401."""
    token = request.cookies.get(config.COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Please log in")
    with get_db() as db:
        row = db.execute(
            """SELECT u.id, u.name, u.email, s.expires_at FROM sessions s
               JOIN users u ON u.id = s.user_id WHERE s.token = ?""", (token,)).fetchone()
    if not row or row["expires_at"] < _utcnow().isoformat():
        raise HTTPException(status_code=401, detail="Session expired, please log in again")
    return {"id": row["id"], "name": row["name"], "email": row["email"]}
