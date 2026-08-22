"""Authentication endpoints."""
import uuid
from fastapi import APIRouter, Depends, HTTPException

from ..db import repo
from ..schemas import Register, Login
from ..security import current_user, hash_password, verify_password, token_for, now

router = APIRouter()


@router.post("/auth/register")
async def register(data: Register):
    r = repo()
    if await r.get_user_by_email(data.email):
        raise HTTPException(409, "An account with this email already exists")
    user = {
        "id": str(uuid.uuid4()),
        "name": data.name,
        "email": data.email.lower(),
        "password": hash_password(data.password),
        "role": "PATIENT",
        "status": "ACTIVE",
        "created_at": now(),
    }
    await r.create_user(user)
    await r.audit({"user_id": user["id"], "action": "USER_REGISTERED", "entity_id": user["id"], "timestamp": now().isoformat()})
    return {"token": token_for(user), "user": {k: user[k] for k in ("id", "name", "email", "role")}}


@router.post("/auth/login")
async def login(data: Login):
    user = await repo().get_user_by_email(data.email)
    if not user or not verify_password(data.password, user["password"]):
        raise HTTPException(401, "Invalid email or password")
    return {"token": token_for(user), "user": {k: user[k] for k in ("id", "name", "email", "role")}}


@router.get("/auth/me")
async def me(user=Depends(current_user)):
    return {k: user[k] for k in ("id", "name", "email", "role")}
