"""Notification service — enqueues emails and generates AI summaries.

Every side-effect call (email, LLM, calendar sync) is executed **after** the
appointment transaction commits, so external failures never block booking.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from .db import repo
from .integrations import email as email_adapter
from .integrations import llm as llm_adapter
from .integrations import calendar as gcal
from . import config


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso() -> str:
    return _now().isoformat()


# ---------------------------------------------------------------------------
# Email queueing
# ---------------------------------------------------------------------------
async def queue_email(kind: str, to: str, subject: str, body: str):
    if not to:
        return
    await repo().enqueue_notification(
        {
            "id": str(uuid.uuid4()),
            "kind": kind,
            "to_email": to,
            "subject": subject,
            "body": body,
            "status": "PENDING",
            "retry_count": 0,
            "last_error": None,
            "next_retry_at": _iso(),
            "created_at": _iso(),
            "sent_at": None,
        }
    )


async def process_pending_emails():
    due = await repo().list_due_notifications(limit=50)
    for n in due:
        if not email_adapter.configured():
            await repo().update_notification(n["id"], {"status": "UNAVAILABLE", "last_error": "SMTP not configured"})
            continue
        ok, err = await email_adapter.send_email(n["to_email"], n["subject"], n["body"])
        if ok:
            await repo().update_notification(n["id"], {"status": "SENT", "sent_at": _iso(), "last_error": None})
        else:
            retries = (n.get("retry_count") or 0) + 1
            backoff_min = {1: 1, 2: 5, 3: 15}.get(retries, 60)
            if retries > config.NOTIFICATION_MAX_RETRIES:
                await repo().update_notification(
                    n["id"], {"status": "FAILED", "retry_count": retries, "last_error": err}
                )
            else:
                next_at = (_now() + timedelta(minutes=backoff_min)).isoformat()
                await repo().update_notification(
                    n["id"],
                    {"status": "RETRY", "retry_count": retries, "last_error": err, "next_retry_at": next_at},
                )


# ---------------------------------------------------------------------------
# AI summaries — invoked from background, never during the booking transaction
# ---------------------------------------------------------------------------
async def generate_pre_visit(appt: dict):
    result = await llm_adapter.generate_pre_visit_summary(appt.get("symptoms") or {})
    await repo().set_ai_summary(
        appt["id"],
        "PRE_VISIT",
        {
            "status": result["status"],
            "payload": result.get("payload"),
            "error": result.get("error"),
            "model": result.get("model"),
        },
    )
    await repo().update_appointment(appt["id"], {"ai_status": result["status"]})


async def generate_post_visit(appt_id: str, clinical: dict):
    result = await llm_adapter.generate_post_visit_summary(clinical)
    await repo().set_ai_summary(
        appt_id,
        "POST_VISIT",
        {
            "status": result["status"],
            "payload": result.get("payload"),
            "error": result.get("error"),
            "model": result.get("model"),
        },
    )
    await repo().update_appointment(appt_id, {"post_ai_status": result["status"]})


# ---------------------------------------------------------------------------
# Calendar sync
# ---------------------------------------------------------------------------
async def sync_calendar_create(appt: dict):
    r = repo()
    doctor = await r.get_user_by_id(appt["doctor_id"])
    patient = await r.get_user_by_id(appt["patient_id"])
    title = f"PulseCare consultation · {doctor.get('name') if doctor else 'Doctor'} & {patient.get('name') if patient else 'Patient'}"
    description = (appt.get("symptoms") or {}).get("chief_complaint", "")
    for user, field in ((patient, "patient_event_id"), (doctor, "doctor_event_id")):
        if not user:
            continue
        conn = await r.get_calendar_connection(user["id"])
        if not conn:
            continue
        event_id, err = await gcal.create_event(conn, title, appt["start"], appt["end"], description)
        if event_id:
            await r.update_appointment(appt["id"], {field: event_id, "calendar_status": "SYNCED"})
        else:
            await r.update_appointment(appt["id"], {"calendar_status": "FAILED"})


async def sync_calendar_cancel(appt: dict):
    r = repo()
    for user_id, field in ((appt["patient_id"], "patient_event_id"), (appt["doctor_id"], "doctor_event_id")):
        conn = await r.get_calendar_connection(user_id)
        event_id = appt.get(field)
        if conn and event_id:
            await gcal.delete_event(conn, event_id)


# ---------------------------------------------------------------------------
# Medication reminder scheduling
# ---------------------------------------------------------------------------
def _plan_times(frequency: str, duration: str, start: datetime) -> list[datetime]:
    """Best-effort schedule from natural strings like "2 times/day", "3 days"."""
    import re

    per_day = 1
    m = re.search(r"(\d+)\s*(?:x|times?)/?day", frequency, re.IGNORECASE)
    if m:
        per_day = max(1, min(6, int(m.group(1))))
    days = 3
    d = re.search(r"(\d+)", duration or "")
    if d:
        days = max(1, min(30, int(d.group(1))))
    slots_by_count = {
        1: [9],
        2: [9, 20],
        3: [9, 14, 20],
        4: [8, 12, 16, 20],
        5: [8, 11, 14, 17, 20],
        6: [7, 10, 13, 16, 19, 22],
    }
    hours = slots_by_count[per_day]
    times: list[datetime] = []
    for day in range(days):
        d0 = (start + timedelta(days=day)).date()
        for h in hours:
            t = datetime.combine(d0, datetime.min.time(), tzinfo=timezone.utc).replace(hour=h)
            if t > _now():
                times.append(t)
    return times


async def schedule_medication_reminders(appt: dict, medications: list[dict]):
    if not medications:
        return
    reminders = []
    for med in medications:
        for t in _plan_times(med.get("frequency", ""), med.get("duration", ""), _now()):
            reminders.append(
                {
                    "id": str(uuid.uuid4()),
                    "patient_id": appt["patient_id"],
                    "appointment_id": appt["id"],
                    "medicine_name": med.get("medicine_name") or med.get("name") or "Medication",
                    "dosage": med.get("dosage", ""),
                    "instructions": med.get("instructions", ""),
                    "scheduled_at": t.isoformat(),
                    "status": "PENDING",
                    "retry_count": 0,
                    "sent_at": None,
                }
            )
    await repo().add_medication_reminders(reminders)


async def process_due_reminders():
    r = repo()
    due = await r.list_due_reminders(limit=50)
    for rem in due:
        patient = await r.get_user_by_id(rem["patient_id"])
        subj = f"Medication reminder · {rem['medicine_name']}"
        body = (
            f"<p>Hi {patient.get('name') if patient else 'there'},</p>"
            f"<p>Time to take <strong>{rem['medicine_name']}</strong> ({rem['dosage']}).</p>"
            f"<p>{rem.get('instructions','')}</p>"
        )
        await queue_email("MEDICATION_REMINDER", patient.get("email") if patient else "", subj, body)
        await r.update_reminder(rem["id"], {"status": "SENT", "sent_at": _iso()})


# ---------------------------------------------------------------------------
# Waitlist promotion
# ---------------------------------------------------------------------------
async def _notify_first_eligible_waitlister(doctor_id: str, start: str):
    """Promote the earliest WAITING waitlister for a freed slot to NOTIFIED.

    Skips any entry whose slot has moved into the past. Notification and
    Google Calendar events happen out-of-band; failures never abort the
    promotion.
    """
    r = repo()
    from . import config as _config

    candidates = await r.find_active_waitlist_for_slot(doctor_id, start)
    for entry in candidates:
        # skip past slots — the requested time has already elapsed
        try:
            if datetime.fromisoformat(entry["requested_start"]) <= _now():
                await r.update_waitlist(entry["id"], {"status": "EXPIRED", "updated_at": _iso()})
                continue
        except Exception:
            pass
        claim_expires = (_now() + timedelta(minutes=_config.WAITLIST_CLAIM_MINUTES)).isoformat()
        promoted = await r.update_waitlist(
            entry["id"],
            {"status": "NOTIFIED", "claim_expires_at": claim_expires, "updated_at": _iso()},
        )
        if not promoted:
            continue
        patient = await r.get_user_by_id(entry["patient_id"])
        doctor = await r.get_user_by_id(doctor_id)
        when = entry["requested_start"]
        await queue_email(
            "WAITLIST_SLOT_OPEN",
            patient.get("email") if patient else "",
            "A PulseCare slot just opened for you",
            (
                f"<p>Hi {patient.get('name') if patient else 'there'},</p>"
                f"<p>A slot with <strong>{doctor.get('name') if doctor else 'your requested doctor'}</strong> "
                f"has just opened at <strong>{when}</strong>.</p>"
                f"<p>You have {_config.WAITLIST_CLAIM_MINUTES} minutes to claim it in PulseCare.</p>"
            ),
        )
        await r.audit(
            {
                "user_id": entry["patient_id"],
                "action": "WAITLIST_NOTIFIED",
                "entity_id": entry["id"],
                "metadata": {"doctor_id": doctor_id, "start": start},
                "timestamp": _iso(),
            }
        )
        return promoted
    return None


async def promote_waitlist_for_freed_slot(doctor_id: str, start: str):
    """Public entry point — always safe to call, never raises."""
    try:
        await _notify_first_eligible_waitlister(doctor_id, start)
    except Exception as e:  # pragma: no cover
        import logging
        logging.getLogger("waitlist").warning("promote failed: %s", e)


async def process_expired_waitlist():
    """Background sweep: any NOTIFIED entry whose claim window elapsed is
    EXPIRED, and the next eligible waiter is promoted."""
    r = repo()
    expired = await r.expire_notified_waitlist()
    for entry in expired:
        await r.audit(
            {
                "user_id": entry["patient_id"],
                "action": "WAITLIST_CLAIM_EXPIRED",
                "entity_id": entry["id"],
                "timestamp": _iso(),
            }
        )
        # promote the next eligible waiter (skip if slot is now occupied)
        busy = await r.busy_starts(entry["doctor_id"])
        if entry["requested_start"] not in busy:
            await promote_waitlist_for_freed_slot(entry["doctor_id"], entry["requested_start"])
