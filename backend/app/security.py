"""Auth utilities and FastAPI dependencies for role-based access."""
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import Depends, Header, HTTPException
import bcrypt, jwt

from . import config
from .db import repo


def now() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except ValueError:
        return False


def token_for(user: dict) -> str:
    return jwt.encode(
        {"sub": user["id"], "role": user["role"], "exp": now() + timedelta(hours=12)},
        config.JWT_SECRET,
        algorithm="HS256",
    )


async def current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Authentication required")
    try:
        payload = jwt.decode(authorization[7:], config.JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Session expired")
    user = await repo().get_user_by_id(payload["sub"])
    if not user:
        raise HTTPException(401, "User not found")
    return user


def require_role(*allowed: str):
    async def check(user=Depends(current_user)):
        if user["role"] not in allowed:
            raise HTTPException(403, "You do not have access to this area")
        return user

    return check
