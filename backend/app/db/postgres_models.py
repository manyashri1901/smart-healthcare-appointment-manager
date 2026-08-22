"""SQLAlchemy 2.0 async models for the PostgreSQL adapter."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import (
    String, Integer, DateTime, Boolean, ForeignKey, Text, JSON, Index, UniqueConstraint, text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    password: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="ACTIVE")
    specialization: Mapped[str | None] = mapped_column(String)
    qualification: Mapped[str | None] = mapped_column(String)
    experience: Mapped[str | None] = mapped_column(String)
    phone: Mapped[str | None] = mapped_column(String)
    work_start: Mapped[str] = mapped_column(String, default="09:00")
    work_end: Mapped[str] = mapped_column(String, default="17:00")
    slot_duration: Mapped[int] = mapped_column(Integer, default=30)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Leave(Base):
    __tablename__ = "doctor_leaves"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doctor_id: Mapped[str] = mapped_column(String, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    date: Mapped[str] = mapped_column(String, index=True)
    __table_args__ = (UniqueConstraint("doctor_id", "date", name="uq_doctor_date"),)


class Appointment(Base):
    __tablename__ = "appointments"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    doctor_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    patient_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), index=True)
    start: Mapped[str] = mapped_column(String, index=True)
    end: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, index=True)
    symptoms: Mapped[dict | None] = mapped_column(JSON)
    ai_status: Mapped[str] = mapped_column(String, default="PENDING")
    notification_status: Mapped[str] = mapped_column(String, default="PENDING")
    calendar_status: Mapped[str] = mapped_column(String, default="PENDING")
    patient_event_id: Mapped[str | None] = mapped_column(String)
    doctor_event_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        # Partial unique index: only one active appointment per (doctor, start)
        Index(
            "uq_active_appt",
            "doctor_id", "start",
            unique=True,
            postgresql_where=text("status IN ('HELD','CONFIRMED')"),
        ),
    )


class Hold(Base):
    __tablename__ = "slot_holds"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    doctor_id: Mapped[str] = mapped_column(String, index=True)
    patient_id: Mapped[str] = mapped_column(String, index=True)
    start: Mapped[str] = mapped_column(String, index=True)
    end: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, index=True)  # HELD | CONSUMED | EXPIRED
    expires_at: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Clinical(Base):
    __tablename__ = "clinical_notes"
    appointment_id: Mapped[str] = mapped_column(String, primary_key=True)
    doctor_id: Mapped[str] = mapped_column(String, nullable=False)
    clinical_notes: Mapped[str] = mapped_column(Text)
    diagnosis: Mapped[str] = mapped_column(String)
    medications: Mapped[list | None] = mapped_column(JSON)
    follow_up_instructions: Mapped[str | None] = mapped_column(Text)
    follow_up_date: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AISummary(Base):
    __tablename__ = "ai_summaries"
    appointment_id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, primary_key=True)  # PRE_VISIT | POST_VISIT
    status: Mapped[str] = mapped_column(String)
    payload: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String)
    to_email: Mapped[str] = mapped_column(String)
    subject: Mapped[str] = mapped_column(String)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    next_retry_at: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[str] = mapped_column(String)
    sent_at: Mapped[str | None] = mapped_column(String)


class MedicationReminder(Base):
    __tablename__ = "medication_reminders"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    patient_id: Mapped[str] = mapped_column(String, index=True)
    appointment_id: Mapped[str] = mapped_column(String, index=True)
    medicine_name: Mapped[str] = mapped_column(String)
    dosage: Mapped[str] = mapped_column(String)
    instructions: Mapped[str | None] = mapped_column(String)
    scheduled_at: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, index=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_at: Mapped[str | None] = mapped_column(String)


class CalendarConnection(Base):
    __tablename__ = "calendar_connections"
    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text)
    token_expiry: Mapped[str | None] = mapped_column(String)
    scope: Mapped[str | None] = mapped_column(String)
    updated_at: Mapped[str] = mapped_column(String)


class Audit(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    entity_id: Mapped[str | None] = mapped_column(String)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON)
    timestamp: Mapped[str] = mapped_column(String)


class Waitlist(Base):
    __tablename__ = "waitlist"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    patient_id: Mapped[str] = mapped_column(String, index=True)
    doctor_id: Mapped[str] = mapped_column(String, index=True)
    requested_start: Mapped[str] = mapped_column(String, index=True)
    requested_end: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, index=True)  # WAITING | NOTIFIED | BOOKED | CANCELLED | EXPIRED
    claim_expires_at: Mapped[str | None] = mapped_column(String)
    appointment_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[str | None] = mapped_column(String)
    __table_args__ = (
        # Prevent duplicate active entries for the same patient/doctor/slot
        Index(
            "uq_active_waitlist",
            "patient_id", "doctor_id", "requested_start",
            unique=True,
            postgresql_where=text("status IN ('WAITING','NOTIFIED')"),
        ),
    )
