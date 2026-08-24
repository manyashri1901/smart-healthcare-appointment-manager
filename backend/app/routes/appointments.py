"""Appointment lifecycle: hold, confirm, cancel, reschedule, clinical notes."""
import logging
import uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from ..db import repo
from ..schemas import HoldRequest, ConfirmRequest, ClinicalRequest, RescheduleRequest
from ..security import current_user, require_role, now
from .. import services, config

log = logging.getLogger("appointments")
router = APIRouter()


async def _validate_slot(r, data_start, data_end, doctor_id: str):
    if data_start <= now():
        raise HTTPException(400, "Past slots cannot be booked")
    doctor = await r.get_user_by_id(doctor_id)
    if not doctor or doctor.get("role") != "DOCTOR" or doctor.get("status") != "ACTIVE":
        raise HTTPException(404, "Doctor not found")
    date = data_start.date().isoformat()
    if await r.get_leave(doctor_id, date):
        raise HTTPException(409, "This doctor is on leave that day")
    if data_start.weekday() >= 5:
        raise HTTPException(400, "This doctor is not available on weekends")
    duration = int(doctor.get("slot_duration", 30))
    if (data_end - data_start).total_seconds() != duration * 60:
        raise HTTPException(400, "Invalid slot duration")
    work_start = datetime.strptime(doctor.get("work_start", "09:00"), "%H:%M").time()
    work_end = datetime.strptime(doctor.get("work_end", "17:00"), "%H:%M").time()
    if data_start.time() < work_start or data_end.time() > work_end:
        raise HTTPException(409, "This slot is outside working hours")
    return doctor


@router.post("/appointments/hold")
async def hold(data: HoldRequest, user=Depends(require_role("PATIENT"))):
    r = repo()
    await _validate_slot(r, data.start, data.end, data.doctor_id)
    hold_doc = {
        "id": str(uuid.uuid4()),
        "doctor_id": data.doctor_id,
        "patient_id": user["id"],
        "start": data.start.isoformat(),
        "end": data.end.isoformat(),
        "status": "HELD",
        "expires_at": (now() + timedelta(minutes=config.SLOT_HOLD_MINUTES)).isoformat(),
        "created_at": now(),
        "updated_at": None,
    }
    # Pre-check existing appointments before the transaction-level check below.
    busy = await r.busy_starts(data.doctor_id)
    if hold_doc["start"] in busy:
        raise HTTPException(409, "This slot is no longer available")
    try:
        result = await r.create_hold(hold_doc)
    except Exception:
        log.exception("Unexpected error creating slot hold for doctor=%s start=%s", data.doctor_id, hold_doc["start"])
        raise HTTPException(500, "We couldn't hold this slot due to an unexpected error. Please try again.")
    if not result:
        raise HTTPException(409, "This slot is no longer available")
    await r.audit({"user_id": user["id"], "action": "SLOT_HOLD_CREATED", "entity_id": result["id"], "timestamp": now().isoformat()})
    return result


@router.post("/appointments/confirm")
async def confirm(data: ConfirmRequest, background: BackgroundTasks, user=Depends(require_role("PATIENT"))):
    r = repo()
    hold_doc = await r.consume_hold(data.hold_id)
    if not hold_doc or hold_doc["patient_id"] != user["id"]:
        raise HTTPException(409, "Your slot hold has expired")

    appt = {
        "id": str(uuid.uuid4()),
        "doctor_id": hold_doc["doctor_id"],
        "patient_id": user["id"],
        "start": hold_doc["start"],
        "end": hold_doc["end"],
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
        log.exception("Unexpected error creating appointment for hold=%s", data.hold_id)
        raise HTTPException(500, "We couldn't confirm this appointment due to an unexpected error. Please try again.")
    if not created:
        raise HTTPException(409, "This slot is no longer available")

    await r.audit({"user_id": user["id"], "action": "APPOINTMENT_CREATED", "entity_id": appt["id"], "timestamp": now().isoformat()})

    # Enqueue email + AI AFTER commit. Never block booking on them.
    doctor = await r.get_user_by_id(hold_doc["doctor_id"])
    patient_email = user.get("email")
    doctor_email = doctor.get("email") if doctor else None
    when = appt["start"]
    invite_ics = services.build_appointment_ics(appt, doctor, user, method="REQUEST")
    await services.queue_email(
        "BOOKING_CONFIRMED", patient_email,
        "Your SmartCare appointment is confirmed",
        f"<p>Your appointment with {doctor.get('name') if doctor else 'your doctor'} is confirmed for {when}.</p>"
        f"<p>A calendar invite (.ics) is attached — most calendar apps will add it automatically.</p>",
        attachment_filename="smartcare-appointment.ics",
        attachment_content=invite_ics,
        ics_method="REQUEST",
    )
    if doctor_email:
        await services.queue_email(
            "BOOKING_NOTIFY_DOCTOR", doctor_email,
            "New SmartCare appointment",
            f"<p>New consultation booked for {when} with {user.get('name')}.</p>",
            attachment_filename="smartcare-appointment.ics",
            attachment_content=invite_ics,
            ics_method="REQUEST",
        )
    background.add_task(services.generate_pre_visit, appt)
    return created


@router.get("/appointments")
async def list_appointments(user=Depends(current_user)):
    r = repo()
    if user["role"] == "PATIENT":
        items = await r.list_appointments({"patient_id": user["id"]})
    elif user["role"] == "DOCTOR":
        items = await r.list_appointments({"doctor_id": user["id"]})
    else:
        items = await r.list_appointments({})
    # decorate with names — one batched lookup for all patients/doctors involved
    user_ids = {item["patient_id"] for item in items} | {item["doctor_id"] for item in items}
    users = await r.get_users_by_ids(list(user_ids))
    out = []
    for item in items:
        p = users.get(item["patient_id"])
        d = users.get(item["doctor_id"])
        item["patient_name"] = p.get("name") if p else "Patient"
        item["doctor_name"] = d.get("name") if d else "Doctor"
        out.append(item)
    return out


@router.get("/appointments/{appointment_id}")
async def get_appointment(appointment_id: str, user=Depends(current_user)):
    r = repo()
    item = await r.get_appointment(appointment_id)
    if not item:
        raise HTTPException(404, "Appointment not found")
    if user["role"] == "PATIENT" and item["patient_id"] != user["id"]:
        raise HTTPException(403, "Not authorized")
    if user["role"] == "DOCTOR" and item["doctor_id"] != user["id"]:
        raise HTTPException(403, "Not authorized")
    item["clinical"] = await r.get_clinical(appointment_id)
    item["ai_summaries"] = await r.get_ai_summaries(appointment_id)
    p = await r.get_user_by_id(item["patient_id"])
    d = await r.get_user_by_id(item["doctor_id"])
    item["patient_name"] = p.get("name") if p else "Patient"
    item["doctor_name"] = d.get("name") if d else "Doctor"
    return item


@router.patch("/appointments/{appointment_id}/cancel")
async def cancel(appointment_id: str, background: BackgroundTasks, user=Depends(current_user)):
    r = repo()
    item = await r.get_appointment(appointment_id)
    allowed = item and (
        user["role"] == "ADMIN"
        or (user["role"] == "PATIENT" and item["patient_id"] == user["id"])
        or (user["role"] == "DOCTOR" and item["doctor_id"] == user["id"])
    )
    if not allowed:
        raise HTTPException(404, "Appointment not found")
    await r.update_appointment(appointment_id, {"status": "CANCELLED"})
    await r.audit({"user_id": user["id"], "action": "APPOINTMENT_CANCELLED", "entity_id": appointment_id, "timestamp": now().isoformat()})

    patient = await r.get_user_by_id(item["patient_id"])
    doctor = await r.get_user_by_id(item["doctor_id"])
    cancel_ics = services.build_appointment_ics(item, doctor, patient, method="CANCEL")
    if patient and patient.get("email"):
        await services.queue_email(
            "APPOINTMENT_CANCELLED", patient["email"],
            "Your SmartCare appointment was cancelled",
            f"<p>Your appointment on {item['start']} has been cancelled.</p>",
            attachment_filename="smartcare-appointment-cancelled.ics",
            attachment_content=cancel_ics,
            ics_method="CANCEL",
        )
    if doctor and doctor.get("email"):
        await services.queue_email(
            "APPOINTMENT_CANCELLED", doctor["email"],
            "A SmartCare appointment was cancelled",
            f"<p>The appointment on {item['start']} with {patient.get('name') if patient else 'a patient'} has been cancelled.</p>",
            attachment_filename="smartcare-appointment-cancelled.ics",
            attachment_content=cancel_ics,
            ics_method="CANCEL",
        )
    background.add_task(services.promote_waitlist_for_freed_slot, item["doctor_id"], item["start"])
    return {"status": "CANCELLED"}


@router.patch("/appointments/{appointment_id}/reschedule")
async def reschedule(appointment_id: str, data: RescheduleRequest, background: BackgroundTasks, user=Depends(current_user)):
    r = repo()
    item = await r.get_appointment(appointment_id)
    if not item:
        raise HTTPException(404, "Appointment not found")
    if user["role"] == "PATIENT" and item["patient_id"] != user["id"]:
        raise HTTPException(403, "Not authorized")
    await _validate_slot(r, data.start, data.end, item["doctor_id"])
    # Attempt atomic move — put current row into CANCELLED then create a new one.
    await r.update_appointment(appointment_id, {"status": "CANCELLED"})
    new_appt = {**item, "id": str(uuid.uuid4()), "start": data.start.isoformat(), "end": data.end.isoformat(), "status": "CONFIRMED", "created_at": now()}
    try:
        created = await r.create_appointment(new_appt)
    except Exception:
        # roll back — reactivate original
        await r.update_appointment(appointment_id, {"status": "CONFIRMED"})
        log.exception("Unexpected error creating rescheduled appointment for appointment_id=%s", appointment_id)
        raise HTTPException(500, "We couldn't reschedule this appointment due to an unexpected error. Please try again.")
    if not created:
        # roll back — reactivate original
        await r.update_appointment(appointment_id, {"status": "CONFIRMED"})
        raise HTTPException(409, "This slot is no longer available")
    await r.audit({"user_id": user["id"], "action": "APPOINTMENT_RESCHEDULED", "entity_id": created["id"], "timestamp": now().isoformat()})

    patient = await r.get_user_by_id(item["patient_id"])
    doctor = await r.get_user_by_id(item["doctor_id"])
    # Reuse the original appointment's id as the calendar UID (bumped SEQUENCE)
    # so calendar clients update the existing event instead of adding a
    # second, orphaned one for the new internal row id.
    updated_ics = services.build_appointment_ics(
        created, doctor, patient, method="REQUEST", uid_source=item["id"], sequence=1
    )
    if patient and patient.get("email"):
        await services.queue_email(
            "APPOINTMENT_RESCHEDULED", patient["email"],
            "Your SmartCare appointment was rescheduled",
            f"<p>Your appointment has moved from {item['start']} to {created['start']}.</p>"
            f"<p>An updated calendar invite (.ics) is attached.</p>",
            attachment_filename="smartcare-appointment.ics",
            attachment_content=updated_ics,
            ics_method="REQUEST",
        )
    if doctor and doctor.get("email"):
        await services.queue_email(
            "APPOINTMENT_RESCHEDULED", doctor["email"],
            "A SmartCare appointment was rescheduled",
            f"<p>The appointment with {patient.get('name') if patient else 'a patient'} has moved from {item['start']} to {created['start']}.</p>",
            attachment_filename="smartcare-appointment.ics",
            attachment_content=updated_ics,
            ics_method="REQUEST",
        )
    background.add_task(services.promote_waitlist_for_freed_slot, item["doctor_id"], item["start"])
    return created


@router.post("/appointments/{appointment_id}/clinical-notes")
async def clinical_notes(appointment_id: str, data: ClinicalRequest, background: BackgroundTasks, user=Depends(require_role("DOCTOR"))):
    r = repo()
    item = await r.get_appointment(appointment_id)
    if not item or item["doctor_id"] != user["id"]:
        raise HTTPException(404, "Appointment not found")
    record = {
        "doctor_id": user["id"],
        "clinical_notes": data.clinical_notes,
        "diagnosis": data.diagnosis,
        "medications": [m.model_dump() for m in data.medications],
        "follow_up_instructions": data.follow_up_instructions,
        "follow_up_date": data.follow_up_date,
    }
    await r.upsert_clinical(appointment_id, record)
    await r.update_appointment(appointment_id, {"status": "COMPLETED", "clinical_status": "SUBMITTED"})
    await r.audit({"user_id": user["id"], "action": "VISIT_COMPLETED", "entity_id": appointment_id, "timestamp": now().isoformat()})

    # Post-visit AI + medication reminders in background.
    background.add_task(services.generate_post_visit, appointment_id, record)
    background.add_task(services.schedule_medication_reminders, item, record["medications"])
    # Notify patient with follow-up email
    patient = await r.get_user_by_id(item["patient_id"])
    await services.queue_email(
        "VISIT_COMPLETED",
        patient.get("email") if patient else "",
        "Your SmartCare visit summary",
        "<p>Your visit summary and prescription are now available in SmartCare.</p>",
    )
    return {"status": "COMPLETED"}


@router.get("/appointments/{appointment_id}/medications")
async def list_medications(appointment_id: str, user=Depends(current_user)):
    r = repo()
    item = await r.get_appointment(appointment_id)
    if not item:
        raise HTTPException(404, "Appointment not found")
    if user["role"] == "PATIENT" and item["patient_id"] != user["id"]:
        raise HTTPException(403, "Not authorized")
    reminders = await r.list_reminders_for_patient(item["patient_id"])
    return [x for x in reminders if x["appointment_id"] == appointment_id]
