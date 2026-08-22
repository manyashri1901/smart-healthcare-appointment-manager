"""Doctor directory and availability."""
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException

from ..db import repo
from ..security import current_user, now

router = APIRouter()


@router.get("/doctors")
async def list_doctors(specialization: Optional[str] = None, user=Depends(current_user)):
    return await repo().list_doctors(specialization)


@router.get("/doctors/{doctor_id}")
async def get_doctor(doctor_id: str, user=Depends(current_user)):
    d = await repo().get_user_by_id(doctor_id)
    if not d or d.get("role") != "DOCTOR":
        raise HTTPException(404, "Doctor not found")
    return d


@router.get("/doctors/{doctor_id}/availability")
async def availability(doctor_id: str, date: str, user=Depends(current_user)):
    r = repo()
    doctor = await r.get_user_by_id(doctor_id)
    if not doctor or doctor.get("role") != "DOCTOR":
        raise HTTPException(404, "Doctor not found")
    day = datetime.fromisoformat(date).date()
    if day < now().date():
        return []
    if await r.get_leave(doctor_id, date):
        return []
    if day.weekday() >= 5:
        return []
    start = datetime.combine(
        day, datetime.strptime(doctor.get("work_start", "09:00"), "%H:%M").time(), tzinfo=timezone.utc
    )
    end = datetime.combine(
        day, datetime.strptime(doctor.get("work_end", "17:00"), "%H:%M").time(), tzinfo=timezone.utc
    )
    duration = int(doctor.get("slot_duration", 30))
    busy = await r.busy_starts(doctor_id)
    held = await r.held_starts(doctor_id)
    slots = []
    cursor = start
    while cursor + timedelta(minutes=duration) <= end:
        iso = cursor.isoformat()
        if cursor > now() and iso not in busy and iso not in held:
            slots.append({"start": iso, "end": (cursor + timedelta(minutes=duration)).isoformat()})
        cursor += timedelta(minutes=duration)
    return slots
