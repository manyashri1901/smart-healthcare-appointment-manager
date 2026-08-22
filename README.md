# PulseCare — Healthcare Appointment & Follow-up Manager

Production-style appointment platform with three portals (Patient, Doctor,
Admin), safe concurrent booking, provider-agnostic AI summaries, medication
reminders, transactional email, and Google Calendar sync.

## Architecture

```
React (CRA + Tailwind) ─┐
                        ├── /api ──► FastAPI (Uvicorn)
Vercel / static host    │            ├── Repository interface
                        │            │    ├── MongoRepo (default)
                        │            │    └── PostgresRepo (DATABASE_URL)
                        │            ├── LLM adapter (Anthropic / OpenAI / Emergent)
                        │            ├── SMTP email adapter (Mailtrap-compatible)
                        │            ├── Google Calendar OAuth
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
- Google Calendar OAuth (per user), event create/update/delete
- Doctor leave management with cancellation of affected appointments
- Admin metrics, notification log, audit trail
- Provider-agnostic integrations — the app is fully usable with no third-party keys, gracefully degrading (AI status becomes `UNAVAILABLE`, calendar sync is skipped, emails are marked `UNAVAILABLE`)

## Technology stack

Frontend: React 19 (CRA), Tailwind CSS, shadcn/ui, lucide-react, axios
Backend: FastAPI, Pydantic 2, SQLAlchemy 2 async, Motor, asyncpg
Auth: bcrypt + JWT (HS256)
Jobs: APScheduler (preview) / Celery + Redis (production, see `docker-compose.yml`)
LLM: httpx-based provider-agnostic adapter (Anthropic, OpenAI-compatible, Emergent)
Calendar: Google OAuth 2.0

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
│   │       ├── admin.py
│   │       └── calendar.py
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
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `MAIL_FROM` | Email adapter |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` | Google Calendar OAuth |

### LLM setup

- **Anthropic Claude**: `LLM_PROVIDER=anthropic`, `LLM_API_KEY=sk-ant-…`, `LLM_MODEL=claude-haiku-4-5`
- **OpenAI-compatible**: `LLM_PROVIDER=openai`, `LLM_API_KEY=…`, `LLM_MODEL=gpt-4o-mini` (optional `LLM_BASE_URL`)
- **Emergent Universal Key**: `LLM_PROVIDER=emergent`, `LLM_API_KEY=$EMERGENT_LLM_KEY`, `LLM_MODEL=claude-haiku-4-5`
- **No key**: All AI features gracefully return `UNAVAILABLE`; appointments remain valid.

### Email setup (Mailtrap)

1. Create a Mailtrap sandbox inbox.
2. Copy SMTP credentials into `.env` (`SMTP_HOST=sandbox.smtp.mailtrap.io`, `SMTP_PORT=587`, `SMTP_USER=…`, `SMTP_PASS=…`).
3. Notifications are queued during appointment transactions and dispatched by the background worker.

### Google Calendar setup

1. In [Google Cloud Console](https://console.cloud.google.com) create a project.
2. Enable **Google Calendar API**.
3. Configure the **OAuth consent screen** (external, test users).
4. Create an **OAuth 2.0 Client ID** of type Web Application.
5. Add redirect URI `${BACKEND_URL}/api/calendar/google/callback`.
6. Copy Client ID / Secret into `.env`.
7. Patients & doctors click *Connect Google Calendar* from Settings; PulseCare stores tokens server-side only.

## Seed data

`app/seed.py` runs at startup. Test credentials (dev only):

| Role | Email | Password |
| --- | --- | --- |
| Admin | `admin@pulsecare.example.com` | `PulseCare123!` |
| Doctor | `maya@pulsecare.example.com` (General Physician) | `PulseCare123!` |
| Doctor | `elias@pulsecare.example.com` (Dermatologist) | `PulseCare123!` |
| Doctor | `priya@pulsecare.example.com` (Cardiologist) | `PulseCare123!` |
| Patient | `alex@pulsecare.example.com` | `PulseCare123!` |
| Patient | `bea@pulsecare.example.com` | `PulseCare123!` |
| Patient | `chen@pulsecare.example.com` | `PulseCare123!` |

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
- Configure `FRONTEND_URL`, `BACKEND_URL`, `GOOGLE_REDIRECT_URI` and CORS accordingly.

## Troubleshooting

- **Index conflicts on Mongo**: drop legacy indexes with `db.<collection>.dropIndex(<name>)` — new startup will recreate them.
- **`Slot is no longer available`**: expected when a concurrent booking has already taken the slot. The UI refreshes availability automatically.
- **AI summaries stuck at `PENDING`**: LLM credentials missing/invalid — status will move to `UNAVAILABLE` / `FAILED`.
- **Google `redirect_uri_mismatch`**: ensure `GOOGLE_REDIRECT_URI` exactly matches the Cloud Console configuration.

## Known limitations

- APScheduler runs inside the FastAPI process for the preview. In production run the Celery worker service from `docker-compose.yml` (`app/celery_app.py` reuses the same job logic).
- Public patient registration is enabled; role assignment for doctors/admins is admin-only.
- Post-visit AI summary is regenerated only on demand — retries are not automatic.
