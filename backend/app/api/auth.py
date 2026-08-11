"""Email/password registration + login, session cookie issuance."""
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.auth import (
    SESSION_COOKIE,
    SESSION_TTL_SEC,
    create_session_jwt,
    get_current_user,
    hash_password,
    verify_password,
)
from app.database import User, get_db

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterBody(BaseModel):
    email: EmailStr
    password: str
    name: str = ""


class LoginBody(BaseModel):
    email: EmailStr
    password: str


def _validate_password_strength(password: str) -> None:
    problems = []
    if len(password) < 8:
        problems.append("at least 8 characters")
    if not re.search(r"[a-z]", password):
        problems.append("a lowercase letter")
    if not re.search(r"[A-Z]", password):
        problems.append("an uppercase letter")
    if not re.search(r"\d", password):
        problems.append("a number")
    if not re.search(r"[^\w\s]", password):
        problems.append("a special character")
    if problems:
        raise HTTPException(400, f"Password must contain {', '.join(problems)}.")


def _user_dict(user: User) -> dict:
    return {"id": user.id, "email": user.email, "name": user.name}


def _set_session_cookie(response: Response, user: User) -> None:
    token = create_session_jwt(user)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_SEC,
        httponly=True,
        samesite="lax",
        secure=False,  # local http dev — set True behind https in production
    )


@router.post("/register")
def register(body: RegisterBody, db: Session = Depends(get_db)):
    _validate_password_strength(body.password)
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(409, "an account with this email already exists")

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        name=body.name or body.email.split("@")[0],
        created_at=int(time.time() * 1000),
    )
    db.add(user)
    db.commit()
    # Deliberately does not set a session cookie — the user logs in separately.
    return _user_dict(user)


@router.post("/login")
def login(body: LoginBody, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "invalid email or password")
    _set_session_cookie(response, user)
    return _user_dict(user)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return _user_dict(user)
