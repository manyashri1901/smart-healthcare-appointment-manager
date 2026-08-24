"""MongoDB repository implementation.

Uses atomic ``find_one_and_update``/unique partial indexes to guarantee that
only one active hold or one CONFIRMED/HELD appointment can exist for the same
(doctor_id, start) tuple at any moment.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Optional
import uuid
from motor.motor_asyncio import AsyncIOMotorClient


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(doc: dict | None) -> dict | None:
    if not doc:
        return None
    doc = dict(doc)
    doc.pop("_id", None)
    doc.pop("password", None)
    return doc


class MongoRepo:
    kind = "mongo"

    def __init__(self, url: str, name: str):
        self.client = AsyncIOMotorClient(url)
        self.db = self.client[name]

    async def init(self):
        await self.db.appointments.create_index(
            [("doctor_id", 1), ("start", 1)],
            unique=True,
            partialFilterExpression={"status": {"$in": ["HELD", "CONFIRMED"]}},
            name="unique_active_appt",
        )
        await self.db.holds.create_index(
            [("doctor_id", 1), ("start", 1)],
            unique=True,
            partialFilterExpression={"status": "HELD"},
            name="unique_active_hold",
        )
        await self.db.holds.create_index("expires_at")
        await self.db.notifications.create_index([("status", 1), ("next_retry_at", 1)])
        await self.db.medication_reminders.create_index([("status", 1), ("scheduled_at", 1)])
        # Waitlist: prevent duplicate entries for the same (patient, doctor, start)
        await self.db.waitlist.create_index(
            [("patient_id", 1), ("doctor_id", 1), ("requested_start", 1)],
            unique=True,
            partialFilterExpression={"status": {"$in": ["WAITING", "NOTIFIED"]}},
            name="unique_active_waitlist",
        )
        await self.db.waitlist.create_index([("doctor_id", 1), ("requested_start", 1), ("status", 1)])

    async def close(self):
        self.client.close()

    async def ping(self):
        await self.db.command("ping")

    # ------------------------------------------------------------------ users
    async def get_user_by_id(self, user_id: str) -> Optional[dict]:
        return _clean(await self.db.users.find_one({"id": user_id}))

    async def get_user_by_email(self, email: str) -> Optional[dict]:
        return await self.db.users.find_one({"email": email.lower()})

    async def create_user(self, user: dict) -> dict:
        await self.db.users.insert_one(user)
        return _clean(user)

    async def list_users(self, role: Optional[str] = None) -> list[dict]:
        q: dict = {}
        if role:
            q["role"] = role
        return [_clean(u) async for u in self.db.users.find(q)]

    async def list_doctors(self, specialization: Optional[str] = None) -> list[dict]:
        q: dict = {"role": "DOCTOR", "status": "ACTIVE"}
        if specialization:
            q["specialization"] = {"$regex": specialization, "$options": "i"}
        return [_clean(d) async for d in self.db.users.find(q)]

    async def update_user(self, user_id: str, patch: dict) -> Optional[dict]:
        await self.db.users.update_one({"id": user_id}, {"$set": patch})
        return await self.get_user_by_id(user_id)

    # ----------------------------------------------------------------- leaves
    async def add_leave(self, doctor_id: str, date: str):
        await self.db.leaves.update_one(
            {"doctor_id": doctor_id, "date": date},
            {"$set": {"doctor_id": doctor_id, "date": date}},
            upsert=True,
        )

    async def remove_leave(self, doctor_id: str, date: str):
        await self.db.leaves.delete_one({"doctor_id": doctor_id, "date": date})

    async def get_leave(self, doctor_id: str, date: str) -> Optional[dict]:
        return _clean(await self.db.leaves.find_one({"doctor_id": doctor_id, "date": date}))

    async def list_leaves(self, doctor_id: str) -> list[dict]:
        return [_clean(x) async for x in self.db.leaves.find({"doctor_id": doctor_id})]

    # ----------------------------------------------------------- availability
    async def busy_starts(self, doctor_id: str) -> set[str]:
        cur = self.db.appointments.find(
            {"doctor_id": doctor_id, "status": {"$in": ["HELD", "CONFIRMED"]}},
            {"start": 1, "_id": 0},
        )
        return {x["start"] async for x in cur}

    async def held_starts(self, doctor_id: str) -> set[str]:
        cur = self.db.holds.find(
            {"doctor_id": doctor_id, "status": "HELD", "expires_at": {"$gt": _now_iso()}},
            {"start": 1, "_id": 0},
        )
        return {x["start"] async for x in cur}

    # ------------------------------------------------------------------ holds
    async def create_hold(self, hold: dict) -> Optional[dict]:
        try:
            await self.db.holds.insert_one(hold)
            return _clean(hold)
        except Exception:
            return None

    async def get_hold(self, hold_id: str, patient_id: str) -> Optional[dict]:
        return _clean(
            await self.db.holds.find_one({"id": hold_id, "patient_id": patient_id, "status": "HELD"})
        )

    async def consume_hold(self, hold_id: str) -> Optional[dict]:
        """Atomically flip a HELD hold to CONSUMED; None if it was expired/taken."""
        now = _now_iso()
        doc = await self.db.holds.find_one_and_update(
            {"id": hold_id, "status": "HELD", "expires_at": {"$gt": now}},
            {"$set": {"status": "CONSUMED", "updated_at": now}},
        )
        return _clean(doc)

    async def expire_holds(self) -> int:
        r = await self.db.holds.update_many(
            {"status": "HELD", "expires_at": {"$lte": _now_iso()}},
            {"$set": {"status": "EXPIRED"}},
        )
        return r.modified_count

    # ------------------------------------------------------------ appointments
    async def create_appointment(self, appt: dict) -> Optional[dict]:
        try:
            await self.db.appointments.insert_one(appt)
            return _clean(appt)
        except Exception:
            return None  # duplicate-key -> slot taken

    async def get_appointment(self, appt_id: str) -> Optional[dict]:
        return _clean(await self.db.appointments.find_one({"id": appt_id}))

    async def list_appointments(self, filters: dict) -> list[dict]:
        return [_clean(a) async for a in self.db.appointments.find(filters).sort("start", 1)]

    async def update_appointment(self, appt_id: str, patch: dict) -> Optional[dict]:
        await self.db.appointments.update_one({"id": appt_id}, {"$set": patch})
        return await self.get_appointment(appt_id)

    async def find_confirmed_on_date(self, doctor_id: str, date: str) -> list[dict]:
        return [
            _clean(a)
            async for a in self.db.appointments.find(
                {
                    "doctor_id": doctor_id,
                    "status": "CONFIRMED",
                    "start": {"$regex": f"^{date}"},
                }
            )
        ]

    # ----------------------------------------------------- clinical / summaries
    async def upsert_clinical(self, appt_id: str, data: dict):
        await self.db.clinical.update_one(
            {"appointment_id": appt_id}, {"$set": data}, upsert=True
        )

    async def get_clinical(self, appt_id: str) -> Optional[dict]:
        return _clean(await self.db.clinical.find_one({"appointment_id": appt_id}))

    async def set_ai_summary(self, appt_id: str, kind: str, payload: dict):
        await self.db.ai_summaries.update_one(
            {"appointment_id": appt_id, "kind": kind},
            {"$set": {"appointment_id": appt_id, "kind": kind, **payload}},
            upsert=True,
        )

    async def get_ai_summaries(self, appt_id: str) -> list[dict]:
        return [_clean(x) async for x in self.db.ai_summaries.find({"appointment_id": appt_id})]

    # -------------------------------------------------------- notifications
    async def enqueue_notification(self, event: dict):
        await self.db.notifications.insert_one(event)

    async def list_due_notifications(self, limit: int = 50) -> list[dict]:
        return [
            _clean(x)
            async for x in self.db.notifications.find(
                {
                    "status": {"$in": ["PENDING", "RETRY"]},
                    "next_retry_at": {"$lte": _now_iso()},
                }
            ).limit(limit)
        ]

    async def update_notification(self, notif_id: str, patch: dict):
        await self.db.notifications.update_one({"id": notif_id}, {"$set": patch})

    async def list_notifications(self, filters: dict | None = None) -> list[dict]:
        return [_clean(x) async for x in self.db.notifications.find(filters or {}).sort("created_at", -1).limit(200)]

    # ----------------------------------------------------- medication reminders
    async def add_medication_reminders(self, reminders: list[dict]):
        if reminders:
            await self.db.medication_reminders.insert_many(reminders)

    async def list_due_reminders(self, limit: int = 50) -> list[dict]:
        return [
            _clean(x)
            async for x in self.db.medication_reminders.find(
                {"status": "PENDING", "scheduled_at": {"$lte": _now_iso()}}
            ).limit(limit)
        ]

    async def update_reminder(self, rem_id: str, patch: dict):
        await self.db.medication_reminders.update_one({"id": rem_id}, {"$set": patch})

    async def list_reminders_for_patient(self, patient_id: str) -> list[dict]:
        return [
            _clean(x)
            async for x in self.db.medication_reminders.find({"patient_id": patient_id}).sort(
                "scheduled_at", 1
            )
        ]

    # ---------------------------------------------------------------- audit
    async def audit(self, entry: dict):
        await self.db.audit.insert_one(entry)

    async def list_audit(self, limit: int = 200) -> list[dict]:
        return [_clean(x) async for x in self.db.audit.find({}).sort("timestamp", -1).limit(limit)]

    # ------------------------------------------------------------- counters
    async def counts(self) -> dict:
        return {
            "patients": await self.db.users.count_documents({"role": "PATIENT"}),
            "doctors": await self.db.users.count_documents({"role": "DOCTOR"}),
            "appointments": await self.db.appointments.count_documents({}),
            "failed_integrations": await self.db.notifications.count_documents({"status": "FAILED"}),
            "waitlist_active": await self.db.waitlist.count_documents({"status": {"$in": ["WAITING", "NOTIFIED"]}}),
        }

    # -------------------------------------------------------------- waitlist
    async def create_waitlist_entry(self, entry: dict) -> Optional[dict]:
        try:
            await self.db.waitlist.insert_one(entry)
            return _clean(entry)
        except Exception:
            return None

    async def get_waitlist_entry(self, entry_id: str) -> Optional[dict]:
        return _clean(await self.db.waitlist.find_one({"id": entry_id}))

    async def find_active_waitlist_for_slot(self, doctor_id: str, start: str) -> list[dict]:
        return [
            _clean(x)
            async for x in self.db.waitlist.find(
                {"doctor_id": doctor_id, "requested_start": start, "status": "WAITING"}
            ).sort("created_at", 1)
        ]

    async def update_waitlist(self, entry_id: str, patch: dict) -> Optional[dict]:
        await self.db.waitlist.update_one({"id": entry_id}, {"$set": patch})
        return await self.get_waitlist_entry(entry_id)

    async def list_waitlist_for_patient(self, patient_id: str) -> list[dict]:
        return [
            _clean(x)
            async for x in self.db.waitlist.find({"patient_id": patient_id}).sort("created_at", -1)
        ]

    async def list_all_waitlist(self, limit: int = 200) -> list[dict]:
        return [_clean(x) async for x in self.db.waitlist.find({}).sort("created_at", -1).limit(limit)]

    async def expire_notified_waitlist(self) -> list[dict]:
        """Return entries whose NOTIFIED claim window has expired, then flip them."""
        now_iso = _now_iso()
        expired = [
            _clean(x)
            async for x in self.db.waitlist.find(
                {"status": "NOTIFIED", "claim_expires_at": {"$lte": now_iso}}
            )
        ]
        if expired:
            ids = [e["id"] for e in expired]
            await self.db.waitlist.update_many(
                {"id": {"$in": ids}}, {"$set": {"status": "EXPIRED", "updated_at": now_iso}}
            )
        return expired

    # -------------------------------------------------------------- insights
    async def insights(self, days: int = 7) -> dict:
        from datetime import timedelta
        now_dt = datetime.now(timezone.utc)
        cutoff_dt = now_dt - timedelta(days=days)
        cutoff = cutoff_dt.isoformat()

        # Cancellations by day (from audit log)
        by_day: dict[str, int] = {}
        for i in range(days):
            day = (now_dt - timedelta(days=days - 1 - i)).date().isoformat()
            by_day[day] = 0

        cancellations = 0
        rebooked_patients: set[str] = set()
        cancelled_by_patient: dict[str, str] = {}  # patient_id -> earliest cancel ts
        async for a in self.db.audit.find({"timestamp": {"$gte": cutoff}}):
            action = a.get("action")
            ts = a.get("timestamp") or ""
            if action == "APPOINTMENT_CANCELLED":
                cancellations += 1
                d = ts[:10]
                if d in by_day:
                    by_day[d] += 1
                uid = a.get("user_id")
                if uid and uid not in cancelled_by_patient:
                    cancelled_by_patient[uid] = ts
            elif action in ("APPOINTMENT_CREATED", "WAITLIST_CLAIMED", "APPOINTMENT_RESCHEDULED"):
                uid = a.get("user_id")
                if uid and uid in cancelled_by_patient and ts > cancelled_by_patient[uid]:
                    rebooked_patients.add(uid)

        # Waitlist metrics in window (use updated_at when present, else created_at)
        waitlist_booked = 0
        waitlist_expired = 0
        waitlist_active = 0
        total_wait_seconds = 0.0
        wait_samples = 0
        async for w in self.db.waitlist.find({}):
            ref = w.get("updated_at") or (w.get("created_at").isoformat() if hasattr(w.get("created_at"), "isoformat") else w.get("created_at")) or ""
            if not isinstance(ref, str):
                continue
            if ref < cutoff:
                # only skip terminal statuses outside window; count active
                if w.get("status") in ("WAITING", "NOTIFIED"):
                    waitlist_active += 1
                continue
            status = w.get("status")
            if status == "BOOKED":
                waitlist_booked += 1
                try:
                    created = w.get("created_at")
                    updated = w.get("updated_at")
                    c_dt = created if isinstance(created, datetime) else datetime.fromisoformat(created)
                    u_dt = datetime.fromisoformat(updated) if isinstance(updated, str) else now_dt
                    total_wait_seconds += max(0.0, (u_dt - c_dt).total_seconds())
                    wait_samples += 1
                except Exception:
                    pass
            elif status == "EXPIRED":
                waitlist_expired += 1
            elif status in ("WAITING", "NOTIFIED"):
                waitlist_active += 1

        promoted = waitlist_booked + waitlist_expired
        conversion_rate = round((waitlist_booked / promoted) * 100, 1) if promoted else 0.0
        avg_wait_minutes = round((total_wait_seconds / wait_samples) / 60, 1) if wait_samples else 0.0

        return {
            "days": days,
            "cancellations": cancellations,
            "waitlist_conversions": waitlist_booked,
            "waitlist_expired": waitlist_expired,
            "waitlist_conversion_rate": conversion_rate,
            "avg_wait_minutes": avg_wait_minutes,
            "slots_recovered": waitlist_booked,
            "patients_rebooked": len(rebooked_patients),
            "waitlist_active": waitlist_active,
            "cancellations_by_day": [{"date": d, "count": c} for d, c in by_day.items()],
        }
