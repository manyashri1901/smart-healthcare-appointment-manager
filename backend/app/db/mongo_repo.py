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

    # ------------------------------------------------------------ calendar
    async def get_calendar_connection(self, user_id: str) -> Optional[dict]:
        return _clean(await self.db.calendar_connections.find_one({"user_id": user_id}))

    async def upsert_calendar_connection(self, user_id: str, patch: dict):
        await self.db.calendar_connections.update_one(
            {"user_id": user_id}, {"$set": {"user_id": user_id, **patch}}, upsert=True
        )

    async def delete_calendar_connection(self, user_id: str):
        await self.db.calendar_connections.delete_one({"user_id": user_id})

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
        }
