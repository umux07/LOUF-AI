import hashlib
import hmac
import secrets
import time
from datetime import timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import get_db
from app.models.entities import User, UserSession
ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    algorithm, iterations, salt, expected = encoded.split("$", maxsplit=3)
    if algorithm != "pbkdf2_sha256":
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
    return hmac.compare_digest(actual.hex(), expected)


def token_digest(token: str) -> str:
    return hmac.new(settings.secret_key.encode(), token.encode(), hashlib.sha256).hexdigest()


def get_current_session(
    request: Request, db: Session = Depends(get_db)
) -> UserSession:
    token = request.cookies.get("louf_session")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in.")
    session = db.scalar(select(UserSession).where(UserSession.token_hash == token_digest(token)))
    if not session or session.expires_at.replace(tzinfo=timezone.utc).timestamp() <= time.time():
        if session:
            db.delete(session)
            db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session has expired. Please sign in.")
    return session


def get_current_user(
    session: UserSession = Depends(get_current_session), db: Session = Depends(get_db)
) -> User:
    user = db.get(User, session.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in.")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator access is required.")
    return user


def verify_csrf_cookie(request: Request) -> None:
    cookie = request.cookies.get("louf_csrf")
    header = request.headers.get("x-csrf-token")
    if not cookie or not header or not hmac.compare_digest(cookie, header):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF validation failed. Refresh and try again.")
