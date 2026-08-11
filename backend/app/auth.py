"""Email/password auth: bcrypt hashing + JWT session cookie.

Session is a signed JWT stored in an httpOnly cookie. Frontend and backend are
same-site (both localhost, different ports) so the cookie travels on fetch
calls made with credentials: "include" — no token ever touches frontend JS.
"""
import time

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import User, get_db

SESSION_COOKIE = "mapflow_session"
SESSION_TTL_SEC = 7 * 24 * 3600
JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_session_jwt(user: User) -> str:
    payload = {
        "sub": user.id,
        "email": user.email,
        "name": user.name,
        "exp": int(time.time()) + SESSION_TTL_SEC,
    }
    return jwt.encode(payload, settings.session_secret, algorithm=JWT_ALGORITHM)


def decode_session_jwt(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.session_secret, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    payload = decode_session_jwt(token) if token else None
    if not payload:
        raise HTTPException(401, "not authenticated")
    user = db.get(User, payload["sub"])
    if not user:
        raise HTTPException(401, "not authenticated")
    return user
