# PulseCare — Product Requirements Document

## Original Problem
Build a production-style Healthcare Appointment & Follow-up Manager with
patient/doctor/admin roles, safe concurrent booking, provider-agnostic LLM
integration, medication reminders, email notifications, Google Calendar
sync, background jobs, and deployment configuration.

## Architecture (implemented)
- **Frontend**: React 19 (CRA) + Tailwind + shadcn/ui + axios
- **Backend**: FastAPI, Pydantic 2, SQLAlchemy async, Motor
- **Persistence**: MongoDB (default, current preview). PostgreSQL adapter
  activates when `DATABASE_URL` is set. Both share the same repository
  interface.
- **Auth**: JWT + bcrypt, role-based deps (PATIENT / DOCTOR / ADMIN)
- **Jobs**: APScheduler (preview) + Celery + Redis config for production
- **LLM adapter**: `LLM_PROVIDER` ∈ anthropic / openai / emergent (graceful
  fallback to `UNAVAILABLE`)
- **Email adapter**: SMTP (Mailtrap-compatible), exponential retries
- **Calendar adapter**: Google OAuth 2.0 (server-side tokens only)

## Delivered (2026-02-22)
- Modular backend package: `backend/app/{config,security,schemas,services,jobs,seed}.py`, `db/{mongo_repo,postgres_repo,postgres_models}.py`, `integrations/{llm,email,calendar}.py`, `routes/{auth,doctors,appointments,admin,calendar}.py`
- Repository interface swappable via `DATABASE_URL`
- Slot hold mechanism (5-min TTL) + partial unique index guaranteeing double-booking prevention
- Symptom form + pre-visit AI + doctor visit + prescription + post-visit AI
- Medication reminders scheduling and email dispatch (graceful without SMTP)
- Google Calendar connect/disconnect UI and status endpoint
- Doctor leave management with automatic cancellation of affected appointments
- Admin portal: doctors CRUD, leave management, appointments, notifications, audit
- Slot hold countdown UI, reschedule and cancel flows
- Docker Compose config for production stack (postgres + redis + celery worker)
- Docs: `/app/docs/{system-design,database-schema,api}.md`, `.env.example`, README
- 7 pytest tests covering login, role auth, double-booking, out-of-hours, past slot, admin leave, LLM failure fallback — all passing

## User Personas
- **Patient**: registers, finds specialist, holds/confirms slot, sees visit summary, gets medication reminders
- **Doctor**: sees today's schedule, reviews symptoms + AI, writes clinical notes + prescription
- **Admin**: creates doctors, sets working hours, manages leave, monitors integrations

## Core requirements (implemented)
- End-to-end booking → visit → follow-up
- Database-level concurrency safety
- Graceful degradation when LLM / SMTP / Google are absent
- Provider-agnostic integrations

## Backlog (P1)
- Post-visit AI automatic retry via APScheduler (currently on-demand only)
- Rate limiting for auth endpoints
- Admin edit-doctor form (backend endpoint exists; simple UI to be added)
- SendGrid HTTP adapter alongside SMTP

## Backlog (P2)
- Alembic migrations for PostgreSQL (schema currently created via `create_all`)
- OAuth login (Emergent Google)
- Multi-tenant support
- Patient profile edit + medical history
- Doctor working schedule editor UI

## Known limitations
- APScheduler runs in-process; production should run the Celery worker
- Google Calendar redirect URL must be added to the Google Cloud Console
- LLM & SMTP credentials are optional; features degrade to `UNAVAILABLE` when unset
