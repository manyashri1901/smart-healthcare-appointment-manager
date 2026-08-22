"""PostgreSQL repository (SQLAlchemy async).

Uses database-level partial unique index + row locking to guarantee
double-booking prevention at the storage layer.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select, update, delete, and_, text, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from . import postgres_models as m
from .postgres_models import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso() -> str:
    return _now().isoformat()


def _dump(obj) -> Optional[dict]:
    if obj is None:
        return None
    d = {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
    d.pop("password", None)
    return d


class PostgresRepo:
    kind = "postgres"

    def __init__(self, url: str):
        # Normalise to asyncpg driver
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        self.engine = create_async_engine(url, pool_pre_ping=True, future=True)
        self.session: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )

    async def init(self):
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self):
        await self.engine.dispose()

    async def ping(self):
        async with self.engine.connect() as c:
            await c.execute(text("SELECT 1"))

    # ------------------------------------------------------------------ users
    async def get_user_by_id(self, user_id: str) -> Optional[dict]:
        async with self.session() as s:
            u = (await s.execute(select(m.User).where(m.User.id == user_id))).scalar_one_or_none()
            return _dump(u)

    async def get_user_by_email(self, email: str) -> Optional[dict]:
        async with self.session() as s:
            u = (
                await s.execute(select(m.User).where(m.User.email == email.lower()))
            ).scalar_one_or_none()
            if not u:
                return None
            d = {c.name: getattr(u, c.name) for c in u.__table__.columns}
            return d  # includes password for auth

    async def create_user(self, user: dict) -> dict:
        async with self.session() as s:
            u = m.User(**{k: user.get(k) for k in m.User.__table__.columns.keys() if k in user})
            if not u.created_at:
                u.created_at = _now()
            s.add(u)
            await s.commit()
            return _dump(u)

    async def list_users(self, role: Optional[str] = None) -> list[dict]:
        async with self.session() as s:
            q = select(m.User)
            if role:
                q = q.where(m.User.role == role)
            rows = (await s.execute(q)).scalars().all()
            return [_dump(r) for r in rows]

    async def list_doctors(self, specialization: Optional[str] = None) -> list[dict]:
        async with self.session() as s:
            q = select(m.User).where(m.User.role == "DOCTOR", m.User.status == "ACTIVE")
            if specialization:
                q = q.where(m.User.specialization.ilike(f"%{specialization}%"))
            rows = (await s.execute(q)).scalars().all()
            return [_dump(r) for r in rows]

    async def update_user(self, user_id: str, patch: dict) -> Optional[dict]:
        async with self.session() as s:
            await s.execute(update(m.User).where(m.User.id == user_id).values(**patch, updated_at=_now()))
            await s.commit()
            return await self.get_user_by_id(user_id)

    # ----------------------------------------------------------------- leaves
    async def add_leave(self, doctor_id: str, date: str):
        async with self.session() as s:
            existing = (
                await s.execute(
                    select(m.Leave).where(m.Leave.doctor_id == doctor_id, m.Leave.date == date)
                )
            ).scalar_one_or_none()
            if not existing:
                s.add(m.Leave(doctor_id=doctor_id, date=date))
                await s.commit()

    async def remove_leave(self, doctor_id: str, date: str):
        async with self.session() as s:
            await s.execute(delete(m.Leave).where(m.Leave.doctor_id == doctor_id, m.Leave.date == date))
            await s.commit()

    async def get_leave(self, doctor_id: str, date: str) -> Optional[dict]:
        async with self.session() as s:
            row = (
                await s.execute(select(m.Leave).where(m.Leave.doctor_id == doctor_id, m.Leave.date == date))
            ).scalar_one_or_none()
            return _dump(row)

    async def list_leaves(self, doctor_id: str) -> list[dict]:
        async with self.session() as s:
            rows = (await s.execute(select(m.Leave).where(m.Leave.doctor_id == doctor_id))).scalars().all()
            return [_dump(r) for r in rows]

    # ----------------------------------------------------------- availability
    async def busy_starts(self, doctor_id: str) -> set[str]:
        async with self.session() as s:
            rows = await s.execute(
                select(m.Appointment.start).where(
                    m.Appointment.doctor_id == doctor_id,
                    m.Appointment.status.in_(["HELD", "CONFIRMED"]),
                )
            )
            return {r for (r,) in rows.all()}

    async def held_starts(self, doctor_id: str) -> set[str]:
        async with self.session() as s:
            rows = await s.execute(
                select(m.Hold.start).where(
                    m.Hold.doctor_id == doctor_id,
                    m.Hold.status == "HELD",
                    m.Hold.expires_at > _iso(),
                )
            )
            return {r for (r,) in rows.all()}

    # ------------------------------------------------------------------ holds
    async def create_hold(self, hold: dict) -> Optional[dict]:
        """Concurrency safe: transactional insert; conflicts raise IntegrityError.

        We also lock the (doctor_id, start) row range with SELECT ... FOR UPDATE
        against any competing HELD hold to prevent race conditions with the
        booking flow.
        """
        async with self.session() as s:
            try:
                # Lock existing conflicting rows
                await s.execute(
                    select(m.Hold).where(
                        m.Hold.doctor_id == hold["doctor_id"],
                        m.Hold.start == hold["start"],
                        m.Hold.status == "HELD",
                    ).with_for_update()
                )
                # Also check appointments (no active row can coexist)
                conflict = (
                    await s.execute(
                        select(m.Appointment.id).where(
                            m.Appointment.doctor_id == hold["doctor_id"],
                            m.Appointment.start == hold["start"],
                            m.Appointment.status.in_(["HELD", "CONFIRMED"]),
                        )
                    )
                ).first()
                if conflict:
                    await s.rollback()
                    return None
                # Reject if there is a valid HELD hold
                valid_hold = (
                    await s.execute(
                        select(m.Hold.id).where(
                            m.Hold.doctor_id == hold["doctor_id"],
                            m.Hold.start == hold["start"],
                            m.Hold.status == "HELD",
                            m.Hold.expires_at > _iso(),
                        )
                    )
                ).first()
                if valid_hold:
                    await s.rollback()
                    return None
                row = m.Hold(**{k: hold.get(k) for k in m.Hold.__table__.columns.keys() if k in hold})
                if not row.created_at:
                    row.created_at = _now()
                s.add(row)
                await s.commit()
                return _dump(row)
            except IntegrityError:
                await s.rollback()
                return None

    async def get_hold(self, hold_id: str, patient_id: str) -> Optional[dict]:
        async with self.session() as s:
            row = (
                await s.execute(
                    select(m.Hold).where(
                        m.Hold.id == hold_id,
                        m.Hold.patient_id == patient_id,
                        m.Hold.status == "HELD",
                    )
                )
            ).scalar_one_or_none()
            return _dump(row)

    async def consume_hold(self, hold_id: str) -> Optional[dict]:
        async with self.session() as s:
            row = (
                await s.execute(
                    select(m.Hold).where(m.Hold.id == hold_id).with_for_update()
                )
            ).scalar_one_or_none()
            if not row or row.status != "HELD" or row.expires_at <= _iso():
                await s.rollback()
                return None
            row.status = "CONSUMED"
            row.updated_at = _now()
            await s.commit()
            return _dump(row)

    async def expire_holds(self) -> int:
        async with self.session() as s:
            r = await s.execute(
                update(m.Hold)
                .where(m.Hold.status == "HELD", m.Hold.expires_at <= _iso())
                .values(status="EXPIRED")
            )
            await s.commit()
            return r.rowcount or 0

    # ------------------------------------------------------------ appointments
    async def create_appointment(self, appt: dict) -> Optional[dict]:
        async with self.session() as s:
            try:
                row = m.Appointment(
                    **{k: appt.get(k) for k in m.Appointment.__table__.columns.keys() if k in appt}
                )
                if not row.created_at:
                    row.created_at = _now()
                s.add(row)
                await s.commit()
                return _dump(row)
            except IntegrityError:
                await s.rollback()
                return None

    async def get_appointment(self, appt_id: str) -> Optional[dict]:
        async with self.session() as s:
            row = (
                await s.execute(select(m.Appointment).where(m.Appointment.id == appt_id))
            ).scalar_one_or_none()
            return _dump(row)

    async def list_appointments(self, filters: dict) -> list[dict]:
        async with self.session() as s:
            q = select(m.Appointment)
            if "patient_id" in filters:
                q = q.where(m.Appointment.patient_id == filters["patient_id"])
            if "doctor_id" in filters:
                q = q.where(m.Appointment.doctor_id == filters["doctor_id"])
            q = q.order_by(m.Appointment.start.asc())
            rows = (await s.execute(q)).scalars().all()
            return [_dump(r) for r in rows]

    async def update_appointment(self, appt_id: str, patch: dict) -> Optional[dict]:
        async with self.session() as s:
            await s.execute(update(m.Appointment).where(m.Appointment.id == appt_id).values(**patch))
            await s.commit()
            return await self.get_appointment(appt_id)

    async def find_confirmed_on_date(self, doctor_id: str, date: str) -> list[dict]:
        async with self.session() as s:
            rows = (
                await s.execute(
                    select(m.Appointment).where(
                        m.Appointment.doctor_id == doctor_id,
                        m.Appointment.status == "CONFIRMED",
                        m.Appointment.start.like(f"{date}%"),
                    )
                )
            ).scalars().all()
            return [_dump(r) for r in rows]

    # ----------------------------------------------------- clinical / summaries
    async def upsert_clinical(self, appt_id: str, data: dict):
        async with self.session() as s:
            existing = (
                await s.execute(select(m.Clinical).where(m.Clinical.appointment_id == appt_id))
            ).scalar_one_or_none()
            if existing:
                for k, v in data.items():
                    setattr(existing, k, v)
            else:
                s.add(m.Clinical(appointment_id=appt_id, created_at=_now(), **data))
            await s.commit()

    async def get_clinical(self, appt_id: str) -> Optional[dict]:
        async with self.session() as s:
            row = (
                await s.execute(select(m.Clinical).where(m.Clinical.appointment_id == appt_id))
            ).scalar_one_or_none()
            return _dump(row)

    async def set_ai_summary(self, appt_id: str, kind: str, payload: dict):
        async with self.session() as s:
            existing = (
                await s.execute(
                    select(m.AISummary).where(
                        m.AISummary.appointment_id == appt_id, m.AISummary.kind == kind
                    )
                )
            ).scalar_one_or_none()
            if existing:
                for k, v in payload.items():
                    setattr(existing, k, v)
                existing.updated_at = _now()
            else:
                s.add(m.AISummary(appointment_id=appt_id, kind=kind, updated_at=_now(), **payload))
            await s.commit()

    async def get_ai_summaries(self, appt_id: str) -> list[dict]:
        async with self.session() as s:
            rows = (
                await s.execute(
                    select(m.AISummary).where(m.AISummary.appointment_id == appt_id)
                )
            ).scalars().all()
            return [_dump(r) for r in rows]

    # -------------------------------------------------------- notifications
    async def enqueue_notification(self, event: dict):
        async with self.session() as s:
            s.add(m.Notification(**event))
            await s.commit()

    async def list_due_notifications(self, limit: int = 50) -> list[dict]:
        async with self.session() as s:
            rows = (
                await s.execute(
                    select(m.Notification)
                    .where(
                        m.Notification.status.in_(["PENDING", "RETRY"]),
                        m.Notification.next_retry_at <= _iso(),
                    )
                    .limit(limit)
                )
            ).scalars().all()
            return [_dump(r) for r in rows]

    async def update_notification(self, notif_id: str, patch: dict):
        async with self.session() as s:
            await s.execute(update(m.Notification).where(m.Notification.id == notif_id).values(**patch))
            await s.commit()

    async def list_notifications(self, filters: dict | None = None) -> list[dict]:
        async with self.session() as s:
            rows = (
                await s.execute(select(m.Notification).order_by(m.Notification.created_at.desc()).limit(200))
            ).scalars().all()
            return [_dump(r) for r in rows]

    # ----------------------------------------------------- medication reminders
    async def add_medication_reminders(self, reminders: list[dict]):
        if not reminders:
            return
        async with self.session() as s:
            for r in reminders:
                s.add(m.MedicationReminder(**r))
            await s.commit()

    async def list_due_reminders(self, limit: int = 50) -> list[dict]:
        async with self.session() as s:
            rows = (
                await s.execute(
                    select(m.MedicationReminder)
                    .where(m.MedicationReminder.status == "PENDING", m.MedicationReminder.scheduled_at <= _iso())
                    .limit(limit)
                )
            ).scalars().all()
            return [_dump(r) for r in rows]

    async def update_reminder(self, rem_id: str, patch: dict):
        async with self.session() as s:
            await s.execute(update(m.MedicationReminder).where(m.MedicationReminder.id == rem_id).values(**patch))
            await s.commit()

    async def list_reminders_for_patient(self, patient_id: str) -> list[dict]:
        async with self.session() as s:
            rows = (
                await s.execute(
                    select(m.MedicationReminder)
                    .where(m.MedicationReminder.patient_id == patient_id)
                    .order_by(m.MedicationReminder.scheduled_at.asc())
                )
            ).scalars().all()
            return [_dump(r) for r in rows]

    # ------------------------------------------------------------ calendar
    async def get_calendar_connection(self, user_id: str) -> Optional[dict]:
        async with self.session() as s:
            row = (
                await s.execute(select(m.CalendarConnection).where(m.CalendarConnection.user_id == user_id))
            ).scalar_one_or_none()
            return _dump(row)

    async def upsert_calendar_connection(self, user_id: str, patch: dict):
        async with self.session() as s:
            existing = (
                await s.execute(select(m.CalendarConnection).where(m.CalendarConnection.user_id == user_id))
            ).scalar_one_or_none()
            if existing:
                for k, v in patch.items():
                    setattr(existing, k, v)
                existing.updated_at = _iso()
            else:
                s.add(m.CalendarConnection(user_id=user_id, updated_at=_iso(), **patch))
            await s.commit()

    async def delete_calendar_connection(self, user_id: str):
        async with self.session() as s:
            await s.execute(delete(m.CalendarConnection).where(m.CalendarConnection.user_id == user_id))
            await s.commit()

    # ---------------------------------------------------------------- audit
    async def audit(self, entry: dict):
        async with self.session() as s:
            e = dict(entry)
            if "metadata" in e:
                e["metadata_json"] = e.pop("metadata")
            s.add(m.Audit(**e))
            await s.commit()

    async def list_audit(self, limit: int = 200) -> list[dict]:
        async with self.session() as s:
            rows = (
                await s.execute(select(m.Audit).order_by(m.Audit.timestamp.desc()).limit(limit))
            ).scalars().all()
            return [_dump(r) for r in rows]

    # ------------------------------------------------------------- counters
    async def counts(self) -> dict:
        async with self.session() as s:
            def c(where):
                return func.count()
            patients = (await s.execute(select(func.count()).where(m.User.role == "PATIENT").select_from(m.User))).scalar()
            doctors = (await s.execute(select(func.count()).where(m.User.role == "DOCTOR").select_from(m.User))).scalar()
            appts = (await s.execute(select(func.count()).select_from(m.Appointment))).scalar()
            failed = (
                await s.execute(select(func.count()).where(m.Notification.status == "FAILED").select_from(m.Notification))
            ).scalar()
            waitlist_active = (
                await s.execute(
                    select(func.count()).where(m.Waitlist.status.in_(["WAITING", "NOTIFIED"])).select_from(m.Waitlist)
                )
            ).scalar()
            return {
                "patients": patients or 0,
                "doctors": doctors or 0,
                "appointments": appts or 0,
                "failed_integrations": failed or 0,
                "waitlist_active": waitlist_active or 0,
            }

    # -------------------------------------------------------------- waitlist
    async def create_waitlist_entry(self, entry: dict) -> Optional[dict]:
        async with self.session() as s:
            try:
                row = m.Waitlist(
                    **{k: entry.get(k) for k in m.Waitlist.__table__.columns.keys() if k in entry}
                )
                if not row.created_at:
                    row.created_at = _now()
                s.add(row)
                await s.commit()
                return _dump(row)
            except IntegrityError:
                await s.rollback()
                return None

    async def get_waitlist_entry(self, entry_id: str) -> Optional[dict]:
        async with self.session() as s:
            row = (
                await s.execute(select(m.Waitlist).where(m.Waitlist.id == entry_id))
            ).scalar_one_or_none()
            return _dump(row)

    async def find_active_waitlist_for_slot(self, doctor_id: str, start: str) -> list[dict]:
        async with self.session() as s:
            rows = (
                await s.execute(
                    select(m.Waitlist)
                    .where(
                        m.Waitlist.doctor_id == doctor_id,
                        m.Waitlist.requested_start == start,
                        m.Waitlist.status == "WAITING",
                    )
                    .order_by(m.Waitlist.created_at.asc())
                )
            ).scalars().all()
            return [_dump(r) for r in rows]

    async def update_waitlist(self, entry_id: str, patch: dict) -> Optional[dict]:
        async with self.session() as s:
            await s.execute(update(m.Waitlist).where(m.Waitlist.id == entry_id).values(**patch))
            await s.commit()
            return await self.get_waitlist_entry(entry_id)

    async def list_waitlist_for_patient(self, patient_id: str) -> list[dict]:
        async with self.session() as s:
            rows = (
                await s.execute(
                    select(m.Waitlist)
                    .where(m.Waitlist.patient_id == patient_id)
                    .order_by(m.Waitlist.created_at.desc())
                )
            ).scalars().all()
            return [_dump(r) for r in rows]

    async def list_all_waitlist(self, limit: int = 200) -> list[dict]:
        async with self.session() as s:
            rows = (
                await s.execute(select(m.Waitlist).order_by(m.Waitlist.created_at.desc()).limit(limit))
            ).scalars().all()
            return [_dump(r) for r in rows]

    async def expire_notified_waitlist(self) -> list[dict]:
        async with self.session() as s:
            now_iso = _iso()
            rows = (
                await s.execute(
                    select(m.Waitlist).where(
                        m.Waitlist.status == "NOTIFIED",
                        m.Waitlist.claim_expires_at <= now_iso,
                    )
                )
            ).scalars().all()
            expired = [_dump(r) for r in rows]
            if expired:
                ids = [e["id"] for e in expired]
                await s.execute(
                    update(m.Waitlist).where(m.Waitlist.id.in_(ids)).values(status="EXPIRED", updated_at=now_iso)
                )
                await s.commit()
            return expired
