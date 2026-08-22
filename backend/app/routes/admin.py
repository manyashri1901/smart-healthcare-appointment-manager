"""Admin endpoints."""
import uuid
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from ..db import repo
from ..schemas import DoctorCreate, DoctorUpdate, LeaveRequest
from ..security import require_role, hash_password, now
from .. import services

router = APIRouter()


@router.get("/admin/overview")
async def overview(user=Depends(require_role("ADMIN"))):
    return await repo().counts()


@router.get("/admin/users")
async def list_users(role: str | None = None, user=Depends(require_role("ADMIN"))):
    return await repo().list_users(role)


@router.get("/admin/doctors")
async def list_all_doctors(user=Depends(require_role("ADMIN"))):
    return await repo().list_users("DOCTOR")


@router.post("/admin/doctors")
async def create_doctor(data: DoctorCreate, user=Depends(require_role("ADMIN"))):
    r = repo()
    if await r.get_user_by_email(data.email):
        raise HTTPException(409, "Email already exists")
    doc = {
        "id": str(uuid.uuid4()),
        "name": data.name,
        "email": data.email.lower(),
        "password": hash_password("Welcome123!"),
        "role": "DOCTOR",
        "status": "ACTIVE",
        "specialization": data.specialization,
        "qualification": data.qualification,
        "experience": data.experience,
        "phone": data.phone,
        "work_start": data.work_start,
        "work_end": data.work_end,
        "slot_duration": data.slot_duration,
        "created_at": now(),
    }
    await r.create_user(doc)
    await r.audit({"user_id": user["id"], "action": "DOCTOR_CREATED", "entity_id": doc["id"], "timestamp": now().isoformat()})
    d = dict(doc)
    d.pop("password", None)
    return d


@router.patch("/admin/doctors/{doctor_id}")
async def update_doctor(doctor_id: str, data: DoctorUpdate, user=Depends(require_role("ADMIN"))):
    patch = {k: v for k, v in data.model_dump().items() if v is not None}
    d = await repo().update_user(doctor_id, patch)
    if not d:
        raise HTTPException(404, "Doctor not found")
    await repo().audit({"user_id": user["id"], "action": "DOCTOR_UPDATED", "entity_id": doctor_id, "timestamp": now().isoformat()})
    return d


@router.post("/admin/doctors/{doctor_id}/leave")
async def add_leave(doctor_id: str, data: LeaveRequest, background: BackgroundTasks, user=Depends(require_role("ADMIN"))):
    r = repo()
    doctor = await r.get_user_by_id(doctor_id)
    if not doctor or doctor.get("role") != "DOCTOR":
        raise HTTPException(404, "Doctor not found")
    affected = await r.find_confirmed_on_date(doctor_id, data.date)
    await r.add_leave(doctor_id, data.date)
    for appt in affected:
        await r.update_appointment(appt["id"], {"status": "CANCELLED", "cancellation_reason": "DOCTOR_LEAVE"})
        patient = await r.get_user_by_id(appt["patient_id"])
        await services.queue_email(
            "LEAVE_CONFLICT",
            patient.get("email") if patient else "",
            "Your PulseCare appointment needs to be rescheduled",
            f"<p>Unfortunately your appointment on {data.date} is cancelled as your doctor is on leave. Please reschedule at your convenience.</p>",
        )
        background.add_task(services.sync_calendar_cancel, appt)
    await r.audit({"user_id": user["id"], "action": "DOCTOR_LEAVE_CREATED", "entity_id": doctor_id, "metadata": {"date": data.date, "affected": len(affected)}, "timestamp": now().isoformat()})
    return {"date": data.date, "status": "LEAVE_ADDED", "affected_appointments": len(affected)}


@router.delete("/admin/doctors/{doctor_id}/leave/{date}")
async def remove_leave(doctor_id: str, date: str, user=Depends(require_role("ADMIN"))):
    await repo().remove_leave(doctor_id, date)
    await repo().audit({"user_id": user["id"], "action": "DOCTOR_LEAVE_REMOVED", "entity_id": doctor_id, "metadata": {"date": date}, "timestamp": now().isoformat()})
    return {"status": "LEAVE_REMOVED"}


@router.get("/admin/doctors/{doctor_id}/leaves")
async def list_leaves(doctor_id: str, user=Depends(require_role("ADMIN"))):
    return await repo().list_leaves(doctor_id)


@router.get("/admin/appointments")
async def list_appointments(user=Depends(require_role("ADMIN"))):
    return await repo().list_appointments({})


@router.get("/admin/notifications")
async def list_notifications(user=Depends(require_role("ADMIN"))):
    return await repo().list_notifications()


@router.get("/admin/audit")
async def audit(user=Depends(require_role("ADMIN"))):
    return await repo().list_audit()


@router.get("/admin/insights")
async def insights(days: int = 7, user=Depends(require_role("ADMIN"))):
    days = max(1, min(30, days))
    return await repo().insights(days)
