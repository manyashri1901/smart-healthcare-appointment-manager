"""Waitlist endpoints — patient join / claim, admin visibility.

The claim flow reuses the existing concurrency-safe booking primitives
(``create_hold`` + ``create_appointment``) so slot-hold and double-booking
logic remain the single source of truth.
"""
import logging
import uuid
from datetime import timedelta
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from ..db import repo
from ..schemas import WaitlistJoin, WaitlistClaim
from ..security import current_user, require_role, now
from .. import services, config

log = logging.getLogger("waitlist")
router = APIRouter()


@router.post("/waitlist")
async def join(data: WaitlistJoin, user=Depends(require_role("PATIENT"))):
    r = repo()
    if data.start <= now():
        raise HTTPException(400, "Cannot join the waitlist for a past slot")
    doctor = await r.get_user_by_id(data.doctor_id)
    if not doctor or doctor.get("role") != "DOCTOR":
        raise HTTPException(404, "Doctor not found")
    entry = {
        "id": str(uuid.uuid4()),
        "patient_id": user["id"],
        "doctor_id": data.doctor_id,
        "requested_start": data.start.isoformat(),
        "requested_end": data.end.isoformat(),
        "status": "WAITING",
        "claim_expires_at": None,
        "appointment_id": None,
        "created_at": now(),
        "updated_at": None,
    }
    created = await r.create_waitlist_entry(entry)
    if not created:
        raise HTTPException(409, "You are already on the waitlist for this slot")
    await r.audit(
        {
            "user_id": user["id"],
            "action": "WAITLIST_JOINED",
            "entity_id": created["id"],
            "metadata": {"doctor_id": data.doctor_id, "start": entry["requested_start"]},
            "timestamp": now().isoformat(),
        }
    )
    # If the slot is already free (rare — user joined right after cancel),
    # promote them immediately so they get a notification email.
    busy = await r.busy_starts(data.doctor_id)
    if entry["requested_start"] not in busy:
        await services.promote_waitlist_for_freed_slot(data.doctor_id, entry["requested_start"])
    return created


@router.get("/waitlist/mine")
async def mine(user=Depends(require_role("PATIENT"))):
    r = repo()
    entries = await r.list_waitlist_for_patient(user["id"])
    # decorate with doctor name
    out = []
    for e in entries:
        d = await r.get_user_by_id(e["doctor_id"])
        e["doctor_name"] = d.get("name") if d else "Doctor"
        out.append(e)
    return out


@router.delete("/waitlist/{entry_id}")
async def cancel(entry_id: str, user=Depends(require_role("PATIENT"))):
    r = repo()
    entry = await r.get_waitlist_entry(entry_id)
    if not entry or entry["patient_id"] != user["id"]:
        raise HTTPException(404, "Waitlist entry not found")
    if entry["status"] not in ("WAITING", "NOTIFIED"):
        raise HTTPException(400, "This entry cannot be cancelled")
    await r.update_waitlist(entry_id, {"status": "CANCELLED", "updated_at": now().isoformat()})
    await r.audit(
        {"user_id": user["id"], "action": "WAITLIST_CANCELLED", "entity_id": entry_id, "timestamp": now().isoformat()}
    )
    # If the cancelled entry was NOTIFIED, promote the next eligible waiter.
    if entry["status"] == "NOTIFIED":
        await services.promote_waitlist_for_freed_slot(entry["doctor_id"], entry["requested_start"])
    return {"status": "CANCELLED"}


@router.post("/waitlist/{entry_id}/claim")
async def claim(entry_id: str, data: WaitlistClaim, background: BackgroundTasks, user=Depends(require_role("PATIENT"))):
    """Claim a notified waitlist slot — reuses the existing booking flow."""
    r = repo()
    entry = await r.get_waitlist_entry(entry_id)
    if not entry or entry["patient_id"] != user["id"]:
        raise HTTPException(404, "Waitlist entry not found")
    if entry["status"] != "NOTIFIED":
        raise HTTPException(409, "This waitlist entry is no longer claimable")
    if entry.get("claim_expires_at") and entry["claim_expires_at"] <= now().isoformat():
        await r.update_waitlist(entry_id, {"status": "EXPIRED", "updated_at": now().isoformat()})
        raise HTTPException(409, "Your claim window has expired")

    # Reuse the concurrency-safe hold + confirm primitives.
    hold_doc = {
        "id": str(uuid.uuid4()),
        "doctor_id": entry["doctor_id"],
        "patient_id": user["id"],
        "start": entry["requested_start"],
        "end": entry["requested_end"],
        "status": "HELD",
        "expires_at": (now() + timedelta(minutes=config.SLOT_HOLD_MINUTES)).isoformat(),
        "created_at": now(),
        "updated_at": None,
    }
    busy = await r.busy_starts(entry["doctor_id"])
    if hold_doc["start"] in busy:
        # Someone else booked the slot in the meantime — mark this claim expired
        # and promote the next eligible waiter.
        await r.update_waitlist(entry_id, {"status": "EXPIRED", "updated_at": now().isoformat()})
        raise HTTPException(409, "This slot is no longer available")
    try:
        hold = await r.create_hold(hold_doc)
    except Exception:
        log.exception("Unexpected error creating hold while claiming waitlist entry=%s", entry_id)
        raise HTTPException(500, "We couldn't claim this slot due to an unexpected error. Please try again.")
    if not hold:
        await r.update_waitlist(entry_id, {"status": "EXPIRED", "updated_at": now().isoformat()})
        raise HTTPException(409, "This slot is no longer available")
    consumed = await r.consume_hold(hold["id"])
    if not consumed:
        raise HTTPException(409, "This slot is no longer available")

    appt = {
        "id": str(uuid.uuid4()),
        "doctor_id": entry["doctor_id"],
        "patient_id": user["id"],
        "start": entry["requested_start"],
        "end": entry["requested_end"],
        "status": "CONFIRMED",
        "symptoms": {
            "chief_complaint": data.chief_complaint,
            "symptoms": data.symptoms,
            "symptom_duration": data.symptom_duration,
            "severity": data.severity,
            "additional_notes": data.additional_notes,
        },
        "ai_status": "PENDING",
        "notification_status": "PENDING",
        "created_at": now(),
    }
    try:
        created = await r.create_appointment(appt)
    except Exception:
        log.exception("Unexpected error creating appointment while claiming waitlist entry=%s", entry_id)
        raise HTTPException(500, "We couldn't confirm this appointment due to an unexpected error. Please try again.")
    if not created:
        # Someone else beat us to the atomic insert.
        await r.update_waitlist(entry_id, {"status": "EXPIRED", "updated_at": now().isoformat()})
        raise HTTPException(409, "This slot is no longer available")

    await r.update_waitlist(
        entry_id,
        {"status": "BOOKED", "appointment_id": created["id"], "updated_at": now().isoformat()},
    )
    await r.audit(
        {
            "user_id": user["id"],
            "action": "WAITLIST_CLAIMED",
            "entity_id": entry_id,
            "metadata": {"appointment_id": created["id"]},
            "timestamp": now().isoformat(),
        }
    )

    # Post-transactional side effects — never block the appointment on them.
    doctor = await r.get_user_by_id(entry["doctor_id"])
    invite_ics = services.build_appointment_ics(appt, doctor, user, method="REQUEST")
    await services.queue_email(
        "BOOKING_CONFIRMED",
        user.get("email"),
        "Your SmartCare appointment is confirmed",
        f"<p>Your waitlist claim succeeded — appointment confirmed for {appt['start']}.</p>"
        f"<p>A calendar invite (.ics) is attached — most calendar apps will add it automatically.</p>",
        attachment_filename="smartcare-appointment.ics",
        attachment_content=invite_ics,
        ics_method="REQUEST",
    )
    if doctor and doctor.get("email"):
        await services.queue_email(
            "BOOKING_NOTIFY_DOCTOR",
            doctor["email"],
            "New SmartCare appointment (from waitlist)",
            f"<p>New consultation booked for {appt['start']} with {user.get('name')}.</p>",
            attachment_filename="smartcare-appointment.ics",
            attachment_content=invite_ics,
            ics_method="REQUEST",
        )
    background.add_task(services.generate_pre_visit, appt)
    return created


# ---------------------------------------------------------------- admin
@router.get("/admin/waitlist")
async def admin_list(user=Depends(require_role("ADMIN"))):
    r = repo()
    entries = await r.list_all_waitlist()
    out = []
    for e in entries:
        p = await r.get_user_by_id(e["patient_id"])
        d = await r.get_user_by_id(e["doctor_id"])
        e["patient_name"] = p.get("name") if p else "Patient"
        e["doctor_name"] = d.get("name") if d else "Doctor"
        out.append(e)
    return out
