"""Google Calendar OAuth connect/callback/disconnect."""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse

from ..db import repo
from ..security import current_user, now
from ..integrations import calendar as gcal
from .. import config

router = APIRouter()

# Simple in-memory state map for CSRF protection (per-process; suitable for preview).
_states: dict[str, str] = {}


@router.get("/calendar/google/connect")
async def connect(user=Depends(current_user)):
    if not gcal.configured():
        raise HTTPException(503, "Google Calendar not configured on the server")
    state = str(uuid.uuid4())
    _states[state] = user["id"]
    return {"url": gcal.auth_url(state)}


@router.get("/calendar/google/callback")
async def callback(code: str, state: str):
    user_id = _states.pop(state, None)
    if not user_id:
        raise HTTPException(400, "Invalid state")
    tokens = await gcal.exchange_code(code)
    if not tokens:
        raise HTTPException(400, "Token exchange failed")
    await repo().upsert_calendar_connection(user_id, tokens)
    await repo().audit({"user_id": user_id, "action": "CALENDAR_CONNECTED", "entity_id": user_id, "timestamp": now().isoformat()})
    return RedirectResponse(f"{config.FRONTEND_URL}/?calendar=connected")


@router.delete("/calendar/google/disconnect")
async def disconnect(user=Depends(current_user)):
    await repo().delete_calendar_connection(user["id"])
    return {"status": "DISCONNECTED"}


@router.get("/calendar/status")
async def status(user=Depends(current_user)):
    conn = await repo().get_calendar_connection(user["id"])
    return {"connected": bool(conn), "configured": gcal.configured()}
