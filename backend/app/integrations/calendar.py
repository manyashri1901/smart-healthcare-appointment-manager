"""Google Calendar OAuth 2.0 adapter.

If Google credentials are absent every method returns UNAVAILABLE; the
booking workflow always remains valid.

Tokens are stored in the ``calendar_connections`` collection/table and never
exposed to the frontend.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx

from .. import config

log = logging.getLogger("calendar")

SCOPES = "https://www.googleapis.com/auth/calendar.events openid email"


def configured() -> bool:
    return bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET)


def auth_url(state: str) -> str:
    if not configured():
        return ""
    params = {
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": config.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


async def exchange_code(code: str) -> Optional[dict]:
    if not configured():
        return None
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": config.GOOGLE_CLIENT_ID,
                "client_secret": config.GOOGLE_CLIENT_SECRET,
                "redirect_uri": config.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        if r.status_code != 200:
            log.warning("Google token exchange failed: %s", r.text[:200])
            return None
        data = r.json()
        return {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token"),
            "token_expiry": data.get("expires_in"),
            "scope": data.get("scope"),
        }


async def _refresh(conn: dict) -> Optional[str]:
    if not conn.get("refresh_token"):
        return None
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": config.GOOGLE_CLIENT_ID,
                "client_secret": config.GOOGLE_CLIENT_SECRET,
                "refresh_token": conn["refresh_token"],
                "grant_type": "refresh_token",
            },
        )
        if r.status_code != 200:
            return None
        return r.json().get("access_token")


async def _authed_request(conn: dict, method: str, url: str, **kwargs) -> tuple[Optional[dict], str]:
    token = conn.get("access_token")
    async with httpx.AsyncClient(timeout=15) as c:
        for attempt in range(2):
            r = await c.request(method, url, headers={"Authorization": f"Bearer {token}"}, **kwargs)
            if r.status_code == 401 and attempt == 0:
                token = await _refresh(conn)
                if not token:
                    return None, "Token refresh failed"
                continue
            if r.status_code >= 400:
                return None, f"HTTP {r.status_code}: {r.text[:200]}"
            return (r.json() if r.text else {}), ""
    return None, "unreachable"


async def create_event(conn: dict, title: str, start_iso: str, end_iso: str, description: str = "") -> tuple[Optional[str], str]:
    if not configured() or not conn:
        return None, "Calendar not connected"
    data, err = await _authed_request(
        conn,
        "POST",
        "https://www.googleapis.com/calendar/v3/calendars/primary/events",
        json={
            "summary": title,
            "description": description,
            "start": {"dateTime": start_iso},
            "end": {"dateTime": end_iso},
        },
    )
    return (data.get("id") if data else None), err


async def delete_event(conn: dict, event_id: str) -> tuple[bool, str]:
    if not configured() or not conn or not event_id:
        return False, "Not connected"
    _, err = await _authed_request(
        conn,
        "DELETE",
        f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}",
    )
    return (err == "", err)


async def update_event(conn: dict, event_id: str, start_iso: str, end_iso: str) -> tuple[bool, str]:
    if not configured() or not conn or not event_id:
        return False, "Not connected"
    _, err = await _authed_request(
        conn,
        "PATCH",
        f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{event_id}",
        json={"start": {"dateTime": start_iso}, "end": {"dateTime": end_iso}},
    )
    return (err == "", err)
