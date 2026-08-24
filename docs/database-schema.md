# SmartCare Database Schema

## Overview

SmartCare uses **PostgreSQL as its sole persistence backend**. The database is implemented using **SQLAlchemy 2.0** with asynchronous access through `asyncpg`, while **Alembic** is used to manage database schema migrations.

The application follows a repository-based persistence architecture. API routes and service-layer components interact with the database through the PostgreSQL repository rather than accessing SQLAlchemy directly.

The primary database implementation is provided by:

```text
backend/app/db/postgres_repo.py
backend/app/db/postgres_models.py
```

The current deployment uses a **Neon-hosted PostgreSQL database**, configured through the `DATABASE_URL` environment variable.

---

## Database Architecture

```text
                    FastAPI Routes
                          │
                          ▼
                    Service Layer
                          │
                          ▼
                PostgreSQL Repository
                (postgres_repo.py)
                          │
                          ▼
                    SQLAlchemy 2.0
                          │
                          ▼
                       asyncpg
                          │
                          ▼
                     PostgreSQL
                          │
                          ▼
                   Neon PostgreSQL
```

Database schema changes are managed using **Alembic migrations**.

This architecture keeps database-specific operations inside the repository layer while allowing routes and services to remain independent of the underlying database access implementation.

---

## Database Tables

### 1. `users`

Stores authentication information and user profiles for patients, doctors, and administrators.

| Column           | Type        | Notes                                                |
| ---------------- | ----------- | ----------------------------------------------------- |
| `id`             | text PK     | UUID                                                 |
| `name`           | text        | User's full name                                     |
| `email`          | text UNIQUE | Stored in lowercase                                  |
| `password`       | text        | bcrypt password hash; never returned through the API |
| `role`           | text        | `PATIENT`, `DOCTOR`, or `ADMIN`                      |
| `status`         | text        | `ACTIVE` or `INACTIVE`                               |
| `specialization` | text        | Doctor-specific                                      |
| `qualification`  | text        | Doctor-specific                                      |
| `experience`     | text        | Doctor-specific                                      |
| `phone`          | text        | Contact number                                       |
| `work_start`     | text        | Working hours in `HH:MM` format                      |
| `work_end`       | text        | Working hours in `HH:MM` format                      |
| `slot_duration`  | integer     | Appointment duration in minutes; default is 30       |
| `created_at`     | timestamptz | Record creation time                                 |
| `updated_at`     | timestamptz | Last update time                                     |

**Constraints and indexes**

* Primary key: `id`
* Unique constraint: `email`

---

### 2. `doctor_leaves`

Stores dates on which doctors are unavailable.

| Column      | Type       | Notes                   |
| ----------- | ---------- | ------------------------ |
| `id`        | integer PK | Unique leave identifier |
| `doctor_id` | text FK    | References `users(id)`  |
| `date`      | text       | ISO date                |

**Constraints**

* Foreign key: `doctor_id → users(id)`
* Unique constraint: `(doctor_id, date)`

This prevents duplicate leave records for the same doctor and date.

---

### 3. `appointments`

Stores patient-doctor appointment records and their lifecycle state.

| Column                | Type        | Notes                                                                      |
| ---------------------- | ----------- | --------------------------------------------------------------------------- |
| `id`                  | text PK     | UUID                                                                       |
| `doctor_id`           | text FK     | References `users(id)`                                                     |
| `patient_id`          | text FK     | References `users(id)`                                                     |
| `start`               | text        | ISO-8601 UTC datetime                                                      |
| `end`                 | text        | ISO-8601 UTC datetime                                                      |
| `status`              | text        | `HELD`, `CONFIRMED`, `CANCELLED`, `RESCHEDULED`, `COMPLETED`, or `NO_SHOW` |
| `symptoms`            | jsonb       | Structured symptoms submitted during booking                               |
| `ai_status`           | text        | `PENDING`, `COMPLETED`, `FAILED`, or `UNAVAILABLE`                         |
| `notification_status` | text        | Notification processing state                                              |
| `created_at`          | timestamptz | Record creation time                                                       |

**Foreign keys**

* `doctor_id → users(id)`
* `patient_id → users(id)`

### Appointment Concurrency Constraint

SmartCare uses a PostgreSQL partial unique index to prevent two active bookings from occupying the same doctor's slot:

```sql
UNIQUE (doctor_id, start)
WHERE status IN ('HELD', 'CONFIRMED')
```

This allows cancelled, rescheduled, completed, and no-show appointments to remain in the database without preventing the slot from being reused.

---

### 4. `slot_holds`

Temporarily reserves an appointment slot while a patient completes the booking process.

| Column       | Type        | Notes                            |
| ------------ | ----------- | ---------------------------------- |
| `id`         | text PK     | UUID                             |
| `doctor_id`  | text        | Doctor associated with the slot  |
| `patient_id` | text        | Patient holding the slot         |
| `start`      | text        | ISO-8601 UTC datetime            |
| `end`        | text        | ISO-8601 UTC datetime            |
| `expires_at` | text        | Time at which the hold expires   |
| `status`     | text        | `HELD`, `CONSUMED`, or `EXPIRED` |
| `created_at` | timestamptz | Creation time                    |
| `updated_at` | timestamptz | Last update time                 |

**Indexes**

* `(doctor_id, start)`
* `expires_at`

These indexes support efficient slot availability checks and expiration processing.

---

### 5. `clinical_notes`

Stores clinical information recorded by doctors after an appointment.

| Column                   | Type        | Notes                                |
| ------------------------- | ----------- | -------------------------------------- |
| `appointment_id`         | text PK     | Associated appointment               |
| `doctor_id`              | text        | Doctor who created the notes         |
| `clinical_notes`         | text        | Clinical observations                |
| `diagnosis`              | text        | Diagnosis information                |
| `medications`            | jsonb       | List of medication objects           |
| `follow_up_instructions` | text        | Instructions provided to the patient |
| `follow_up_date`         | text        | Recommended follow-up date           |
| `created_at`             | timestamptz | Creation time                        |

### Medication Object

Each medication stored in the `medications` JSONB field follows the application schema:

```json
{
  "medicine_name": "string",
  "dosage": "string",
  "frequency": "string",
  "duration": "string",
  "instructions": "string"
}
```

---

### 6. `ai_summaries`

Stores AI-generated pre-visit and post-visit summaries.

| Column           | Type        | Notes                                   |
| ---------------- | ----------- | ------------------------------------------ |
| `appointment_id` | text        | Associated appointment                  |
| `kind`           | text        | `PRE_VISIT` or `POST_VISIT`             |
| `status`         | text        | Processing status                       |
| `payload`        | jsonb       | Generated summary data                  |
| `error`          | text        | Error information when generation fails |
| `model`          | text        | Model used for generation               |
| `updated_at`     | timestamptz | Last update time                        |

**Primary key**

```text
(appointment_id, kind)
```

This allows one pre-visit and one post-visit AI summary for each appointment.

AI functionality is non-blocking. If an AI provider is unavailable, appointment booking can continue and the summary status is recorded accordingly.

---

### 7. `notifications`

Stores email notifications and their delivery status.

| Column                | Type    | Notes                                                  |
| ---------------------- | ------- | -------------------------------------------------------- |
| `id`                  | text PK | Unique notification identifier                         |
| `kind`                | text    | Notification type                                      |
| `to_email`            | text    | Recipient email                                        |
| `subject`             | text    | Email subject                                          |
| `body`                | text    | Email body                                             |
| `status`              | text    | `PENDING`, `RETRY`, `SENT`, `FAILED`, or `UNAVAILABLE` |
| `retry_count`         | integer | Number of delivery attempts                            |
| `last_error`          | text    | Most recent delivery error                             |
| `next_retry_at`       | text    | Next scheduled retry                                   |
| `created_at`          | text    | Notification creation time                              |
| `sent_at`             | text    | Successful delivery time                                |
| `attachment_filename` | text    | Optional `.ics` attachment filename                    |
| `attachment_content`  | text    | Optional raw `.ics` content                             |
| `ics_method`          | text    | `REQUEST` or `CANCEL`                                  |

**Index**

```text
(status, next_retry_at)
```

The notification queue allows email delivery to be processed asynchronously and retried after temporary failures.

---

### 8. `medication_reminders`

Stores scheduled medication reminders.

| Column           | Type    | Notes                          |
| ---------------- | ------- | --------------------------------- |
| `id`             | text PK | Unique reminder identifier     |
| `patient_id`     | text    | Patient receiving the reminder |
| `appointment_id` | text    | Associated appointment         |
| `medicine_name`  | text    | Medicine name                  |
| `dosage`         | text    | Dosage information             |
| `instructions`   | text    | Medication instructions        |
| `scheduled_at`   | text    | Scheduled reminder time        |
| `status`         | text    | `PENDING`, `SENT`, or `FAILED` |
| `retry_count`    | integer | Number of retry attempts       |
| `sent_at`        | text    | Successful delivery time       |

**Index**

```text
(status, scheduled_at)
```

This supports efficient retrieval of reminders that are ready for processing.

---

### 9. `audit_logs`

Records important security and business events for traceability.

| Column      | Type       | Notes                             |
| ----------- | ---------- | ------------------------------------ |
| `id`        | integer PK | Unique audit record               |
| `user_id`   | text       | User responsible for the action   |
| `action`    | text       | Action performed                  |
| `entity_id` | text       | Related entity identifier         |
| `metadata`  | jsonb      | Additional structured information |
| `timestamp` | text       | Event timestamp                   |

Common actions include:

```text
USER_REGISTERED
APPOINTMENT_CREATED
APPOINTMENT_CANCELLED
APPOINTMENT_RESCHEDULED
SLOT_HOLD_CREATED
DOCTOR_LEAVE_CREATED
VISIT_COMPLETED
WAITLIST_JOINED
WAITLIST_NOTIFIED
WAITLIST_CLAIMED
WAITLIST_CLAIM_EXPIRED
WAITLIST_CANCELLED
```

The audit log provides an application-level history of important operations.

---

### 10. `waitlist`

Stores patients waiting for an appointment slot that is currently unavailable.

| Column             | Type        | Notes                                                      |
| ------------------- | ----------- | ------------------------------------------------------------ |
| `id`               | text PK     | UUID                                                       |
| `patient_id`       | text        | Patient requesting the slot                                |
| `doctor_id`        | text        | Requested doctor                                           |
| `requested_start`  | text        | Requested start time in ISO-8601 UTC                       |
| `requested_end`    | text        | Requested end time in ISO-8601 UTC                         |
| `status`           | text        | `WAITING`, `NOTIFIED`, `BOOKED`, `CANCELLED`, or `EXPIRED` |
| `claim_expires_at` | text        | Claim expiration time while status is `NOTIFIED`           |
| `appointment_id`   | text        | Associated appointment when booked                         |
| `created_at`       | timestamptz | Creation time                                              |
| `updated_at`       | text        | Last update time                                            |

### Waitlist Constraints

A PostgreSQL partial unique index prevents a patient from joining the same doctor's slot multiple times while the request is active:

```sql
UNIQUE (patient_id, doctor_id, requested_start)
WHERE status IN ('WAITING', 'NOTIFIED')
```

**Index**

```text
(doctor_id, requested_start, status)
```

This supports efficient lookup and promotion of eligible waitlist entries when an appointment slot becomes available.

---

## Database Integrity and Concurrency

PostgreSQL constraints and indexes are used to maintain consistency during concurrent appointment operations.

### Appointment Slot Protection

Active appointments are protected by a partial unique index on:

```text
doctor_id + start
```

for appointments with the following statuses:

```text
HELD
CONFIRMED
```

This prevents duplicate active bookings for the same doctor and appointment time.

### Temporary Slot Holds

The `slot_holds` table provides temporary reservation state while a patient completes the booking process.

Expired holds are processed by the application's **APScheduler-based background scheduler**.

### Waitlist Deduplication

The waitlist partial unique index prevents multiple active waitlist entries for the same patient, doctor, and requested start time.

### Auditability

Important operations are recorded in `audit_logs`, providing an application-level trail for:

* User registration
* Appointment creation
* Appointment cancellation
* Appointment rescheduling
* Doctor leave creation
* Visit completion
* Waitlist operations

---

## JSONB Usage

SmartCare uses PostgreSQL `JSONB` for fields containing structured data whose internal structure may evolve independently of the relational schema.

The primary JSONB fields are:

| Table            | Field         | Purpose                      |
| ----------------- | ------------- | ------------------------------- |
| `appointments`   | `symptoms`    | Structured patient symptoms  |
| `clinical_notes` | `medications` | Medication objects           |
| `ai_summaries`   | `payload`     | AI-generated summary data    |
| `audit_logs`     | `metadata`    | Additional event information |

This approach combines PostgreSQL's relational integrity for core entities with flexible structured storage for variable application data.

---

## API and Database Integration

SmartCare exposes its backend functionality through a RESTful **FastAPI** interface. API routes interact with PostgreSQL through the repository layer rather than accessing the database directly.

The API provides endpoints for:

* Authentication and user management
* Doctor management
* Doctor availability
* Doctor leave management
* Appointment booking and management
* Waitlist operations
* Administrative operations
* Health and database connectivity checks

### API Documentation

SmartCare provides an automatically generated OpenAPI/Swagger interface through FastAPI. The Swagger interface provides an interactive view of the available API endpoints and their request/response schemas.

For database-specific verification, the `/api/health/db` endpoint can be used to verify that the application can successfully communicate with the PostgreSQL database.

---

## Database Migrations

Schema changes are managed using **Alembic**.

The migration configuration is located at:

```text
backend/alembic.ini
```

Migration scripts are maintained under:

```text
backend/alembic/
```

The database connection is provided through the `DATABASE_URL` environment variable rather than being hard-coded into `alembic.ini`.

This ensures that the migration environment and the running application use the same PostgreSQL connection configuration.

---

## Security Considerations

Database credentials and application secrets are provided through environment variables and must not be committed to source control.

The following sensitive information must remain outside Git:

* PostgreSQL credentials
* JWT signing secret
* LLM API keys
* SMTP credentials

The password stored in the `users` table is a **bcrypt hash** and must never be returned through API responses.

The application's `.env` file must remain excluded through `.gitignore`.

A sanitized `.env.example` should be provided if environment configuration needs to be documented for other developers.

---

## Database Technology Summary

| Component                 | Technology                          |
| --------------------------- | -------------------------------------- |
| Database                  | PostgreSQL                          |
| Current hosting           | Neon PostgreSQL                     |
| ORM / Database Toolkit    | SQLAlchemy 2.0                      |
| Async Driver              | asyncpg                             |
| Migration Tool            | Alembic                             |
| Repository Implementation | `postgres_repo.py`                  |
| Data Models               | `postgres_models.py`                |
| Structured Data           | PostgreSQL JSONB                    |
| Database Configuration    | `DATABASE_URL` environment variable |

SmartCare uses a **single PostgreSQL persistence layer** throughout the application. Database access is centralized through the PostgreSQL repository, while SQLAlchemy and `asyncpg` provide asynchronous database connectivity and Alembic manages schema migrations.