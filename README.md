# SmartCare — Healthcare Appointment & Follow-up Manager

Production-style appointment platform with three portals (Patient, Doctor,
Admin), safe concurrent booking, provider-agnostic AI summaries, medication
reminders, transactional email, and .ics calendar invites.

## Architecture

```
React (CRA + Tailwind) ─┐
                        ├── /api ──► FastAPI (Uvicorn)
Vercel / static host    │            ├── Repository interface
                        │            │    ├── MongoRepo (default)
                        │            │    └── PostgresRepo (DATABASE_URL)
                        │            ├── LLM adapter (Anthropic / OpenAI / Emergent)
                        │            ├── SMTP email adapter (Mailtrap-compatible)
                        │            ├── .ics calendar invite builder (RFC 5545)
                        │            └── APScheduler background jobs
                        │
                        └── Optional Celery + Redis workers (production)
```

Business logic and API routes never touch a database driver directly — they
call the repository interface. Setting `DATABASE_URL` switches the backing
store from MongoDB to PostgreSQL. See `docs/system-design.md`.

## Features

- JWT auth, role-based authorization (PATIENT / DOCTOR / ADMIN)
- Dynamic slot generation from doctor working hours & leave
- **Database-level double-booking prevention** (partial unique index + row locking on Postgres, atomic `find_one_and_update` on Mongo)
- 5-minute slot holds with a background cleanup job
- Symptoms form → pre-visit AI summary → doctor visit → clinical notes → post-visit AI summary
- Medication reminder scheduling and delivery
- Transactional email queue with exponential retries
- Calendar invites via standard `.ics` attachments (RFC 5545) on booking/reschedule/cancellation emails — no OAuth, no external service (see "Calendar invites" below for why)
- Doctor leave management with cancellation of affected appointments
- Admin metrics, notification log, audit trail
- Provider-agnostic integrations — the app is fully usable with no third-party keys, gracefully degrading (AI status becomes `UNAVAILABLE`, emails including calendar invites are marked `UNAVAILABLE` if SMTP isn't configured)

## Technology stack

Frontend: React 19 (CRA), Tailwind CSS, shadcn/ui, lucide-react, axios
Backend: FastAPI, Pydantic 2, SQLAlchemy 2 async, Motor, asyncpg
Auth: bcrypt + JWT (HS256)
Jobs: APScheduler (preview) / Celery + Redis (production, see `docker-compose.yml`)
LLM: httpx-based provider-agnostic adapter (Anthropic, OpenAI-compatible, Emergent)
Calendar: standard-library .ics generation (RFC 5545) — no external service

## Folder structure

```
/app
├── backend/
│   ├── server.py                # FastAPI entrypoint
│   ├── app/
│   │   ├── config.py            # env variables
│   │   ├── security.py          # JWT + role deps
│   │   ├── schemas.py           # Pydantic models
│   │   ├── services.py          # notifications, AI, calendar, reminders
│   │   ├── jobs.py              # APScheduler jobs
│   │   ├── seed.py              # idempotent seed
│   │   ├── db/
│   │   │   ├── __init__.py      # repo selector (DATABASE_URL)
│   │   │   ├── mongo_repo.py
│   │   │   ├── postgres_repo.py
│   │   │   └── postgres_models.py
│   │   ├── integrations/
│   │   │   ├── llm.py
│   │   │   ├── email.py
│   │   │   └── calendar.py
│   │   └── routes/
│   │       ├── auth.py
│   │       ├── doctors.py
│   │       ├── appointments.py
│   │       └── admin.py
│   └── tests/
├── frontend/
│   └── src/App.js
├── docs/
│   ├── system-design.md
│   ├── database-schema.md
│   └── api.md
├── docker-compose.yml
├── .env.example
└── README.md
```

## Installation (local)

```bash
git clone <repo>
cd pulsecare
cp .env.example backend/.env

# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --reload --port 8001

# Frontend (separate shell)
cd frontend
yarn install
yarn start
```

### PostgreSQL setup

```bash
docker run -d --name pulsecare-pg -e POSTGRES_PASSWORD=pulse -p 5432:5432 postgres:16
export DATABASE_URL=postgresql://postgres:pulse@localhost:5432/pulsecare
```

Schema is created automatically on first boot via `Base.metadata.create_all`.

### Redis / Celery (optional, production)

Bring up the full stack with `docker-compose up`:

```yaml
services:
  postgres, redis, backend, worker, frontend
```

## Environment variables

See `.env.example`. Every third-party integration is optional; the application
remains fully functional with none configured.

| Variable | Purpose |
| --- | --- |
| `JWT_SECRET` | Signing key for JWT access tokens |
| `DATABASE_URL` | If present, PostgreSQL is used |
| `MONGO_URL` / `DB_NAME` | MongoDB connection when Postgres is not set |
| `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_MODEL` / `LLM_BASE_URL` | AI adapter |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `MAIL_FROM` | Email adapter (also carries calendar `.ics` invites) |

### LLM setup

- **Anthropic Claude**: `LLM_PROVIDER=anthropic`, `LLM_API_KEY=sk-ant-…`, `LLM_MODEL=claude-haiku-4-5`
- **OpenAI-compatible**: `LLM_PROVIDER=openai`, `LLM_API_KEY=…`, `LLM_MODEL=gpt-4o-mini` (optional `LLM_BASE_URL`)
- **Emergent Universal Key**: `LLM_PROVIDER=emergent`, `LLM_API_KEY=$EMERGENT_LLM_KEY`, `LLM_MODEL=claude-haiku-4-5`
- **No key**: All AI features gracefully return `UNAVAILABLE`; appointments remain valid.

### Email setup (Mailtrap)

1. Create a Mailtrap sandbox inbox.
2. Copy SMTP credentials into `.env` (`SMTP_HOST=sandbox.smtp.mailtrap.io`, `SMTP_PORT=587`, `SMTP_USER=…`, `SMTP_PASS=…`).
3. Notifications are queued during appointment transactions and dispatched by the background worker.

### Calendar invites (.ics) — not live Google Calendar sync

Calendar integration was originally built as live Google Calendar OAuth sync
(create/update/delete events via the Calendar API on the user's own
calendar). We hit a **Google OAuth verification blocker during setup**:
shipping a Calendar API app in production mode requires Google's OAuth app
verification, which in turn requires business/billing verification on the
Google Cloud project. That verification wasn't available in this project's
setup, and the "test user" allowance for unverified apps caps out at 100
users and doesn't cover the real deployment target — so live OAuth sync
wasn't a viable path here.

Instead, SmartCare generates a standard **`.ics` calendar file (RFC 5545)**
locally — no external API, no OAuth, no account connection required — and
attaches it to the booking confirmation, reschedule, and cancellation
emails. Opening the attachment (or most mail clients auto-detecting it) adds
the event to Google Calendar, Outlook, Apple Calendar, or any other RFC
5545-compliant calendar app. A reschedule reuses the original event's UID
with an incremented `SEQUENCE` so calendar clients update the existing
event rather than creating a duplicate; cancellation sends a `METHOD:CANCEL`
variant that removes it.

This trades "your calendar always reflects the live appointment state
automatically" for "you get a real, working calendar invite with zero
external dependencies or Google approval process to unblock." No setup
or environment variables are needed for this feature — it works as soon
as SMTP is configured (see above).

## Seed data

`app/seed.py` runs at startup. Test credentials (dev only):

| Role | Email | Password |
| --- | --- | --- |
| Admin | `admin@smartcare.example.com` | `SmartCare123!` |
| Doctor | `maya@smartcare.example.com` (General Physician) | `SmartCare123!` |
| Doctor | `elias@smartcare.example.com` (Dermatologist) | `SmartCare123!` |
| Doctor | `priya@smartcare.example.com` (Cardiologist) | `SmartCare123!` |
| Patient | `alex@smartcare.example.com` | `SmartCare123!` |
| Patient | `bea@smartcare.example.com` | `SmartCare123!` |
| Patient | `chen@smartcare.example.com` | `SmartCare123!` |

## Running tests

```bash
cd backend
pytest -q
```

## API documentation

FastAPI auto-generates Swagger at `${BACKEND_URL}/docs` and ReDoc at `${BACKEND_URL}/redoc`.
See `docs/api.md` for a curated list of endpoints.

## Deployment

- **Frontend**: Vercel (root: `frontend`, build `yarn build`, output `build/`)
- **Backend**: Render / Railway (Python service, start command `uvicorn server:app --host 0.0.0.0 --port $PORT`)
- **Database**: managed PostgreSQL (set `DATABASE_URL`)
- **Redis / Celery workers**: managed Redis + worker service running `celery -A app.celery_app worker`
- Configure `FRONTEND_URL`, `BACKEND_URL`, and CORS accordingly.

## Troubleshooting

- **Index conflicts on Mongo**: drop legacy indexes with `db.<collection>.dropIndex(<name>)` — new startup will recreate them.
- **`Slot is no longer available`**: expected when a concurrent booking has already taken the slot. The UI refreshes availability automatically.
- **AI summaries stuck at `PENDING`**: LLM credentials missing/invalid — status will move to `UNAVAILABLE` / `FAILED`.
- **No `.ics` attachment arrived**: SMTP isn't configured (`SMTP_HOST`/`SMTP_USER`/`SMTP_PASS`) — the notification row will show `status=UNAVAILABLE`. The `.ics` is still generated correctly; it just has nothing to ride along on until SMTP is set.

## Known limitations

- APScheduler runs inside the FastAPI process for the preview. In production run the Celery worker service from `docker-compose.yml` (`app/celery_app.py` reuses the same job logic).
- Public patient registration is enabled; role assignment for doctors/admins is admin-only.
- Post-visit AI summary is regenerated only on demand — retries are not automatic.
