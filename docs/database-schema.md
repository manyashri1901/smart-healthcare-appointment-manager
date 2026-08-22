# PulseCare Database Schema

Two backends are supported. The logical schema below is identical in both;
column names use the PostgreSQL definitions from
`backend/app/db/postgres_models.py`. In MongoDB each entity is stored in the
corresponding collection with the same field names (plus `_id`).

## users
| column | type | notes |
| --- | --- | --- |
| id | text PK | uuid |
| name | text | |
| email | text UNIQUE | lowercased |
| password | text | bcrypt hash — never returned by API |
| role | text | `PATIENT` / `DOCTOR` / `ADMIN` |
| status | text | `ACTIVE` / `INACTIVE` |
| specialization, qualification, experience, phone | text | doctors only |
| work_start, work_end | text | `HH:MM` (UTC) |
| slot_duration | int | minutes, default 30 |
| created_at / updated_at | timestamptz | |

Indexes: `email` unique, primary key.

## doctor_leaves
| column | type | notes |
| --- | --- | --- |
| id | int PK | |
| doctor_id | text FK users(id) | |
| date | text | ISO date |
Unique: `(doctor_id, date)`.

## appointments
| column | type | notes |
| --- | --- | --- |
| id | text PK | uuid |
| doctor_id, patient_id | text FK users(id) | |
| start, end | text | ISO-8601 UTC |
| status | text | `HELD` / `CONFIRMED` / `CANCELLED` / `RESCHEDULED` / `COMPLETED` / `NO_SHOW` |
| symptoms | jsonb | see Symptoms form |
| ai_status | text | `PENDING` / `COMPLETED` / `FAILED` / `UNAVAILABLE` |
| notification_status | text | |
| calendar_status | text | |
| patient_event_id, doctor_event_id | text | Google Calendar event IDs |
| created_at | timestamptz | |

**Critical constraint**: partial unique index
`UNIQUE(doctor_id, start) WHERE status IN ('HELD','CONFIRMED')`.

## slot_holds
| column | type | notes |
| --- | --- | --- |
| id | text PK | uuid |
| doctor_id, patient_id | text | |
| start, end, expires_at | text | ISO-8601 UTC |
| status | text | `HELD` / `CONSUMED` / `EXPIRED` |
| created_at / updated_at | timestamptz | |
Indexes: `(doctor_id, start)`, `expires_at`.

## clinical_notes
| column | type |
| --- | --- |
| appointment_id | text PK |
| doctor_id | text |
| clinical_notes, diagnosis | text |
| medications | jsonb — list of Medication objects |
| follow_up_instructions | text |
| follow_up_date | text |
| created_at | timestamptz |

Medication object: `{medicine_name, dosage, frequency, duration, instructions}`.

## ai_summaries
| column | type |
| --- | --- |
| appointment_id | text |
| kind | text | `PRE_VISIT` / `POST_VISIT` |
| status | text |
| payload | jsonb |
| error, model | text |
| updated_at | timestamptz |
Composite PK: `(appointment_id, kind)`.

## notifications
| column | type |
| --- | --- |
| id | text PK |
| kind | text | e.g. `BOOKING_CONFIRMED`, `LEAVE_CONFLICT`, `MEDICATION_REMINDER` |
| to_email, subject, body | text |
| status | text | `PENDING` / `RETRY` / `SENT` / `FAILED` / `UNAVAILABLE` |
| retry_count, last_error | int / text |
| next_retry_at, created_at, sent_at | text |
Index: `(status, next_retry_at)`.

## medication_reminders
| column | type |
| --- | --- |
| id | text PK |
| patient_id, appointment_id | text |
| medicine_name, dosage, instructions | text |
| scheduled_at | text |
| status | text | `PENDING` / `SENT` / `FAILED` |
| retry_count | int |
| sent_at | text |
Index: `(status, scheduled_at)`.

## calendar_connections
| column | type |
| --- | --- |
| user_id | text PK |
| access_token, refresh_token, scope | text |
| token_expiry | text |
| updated_at | text |

Tokens are stored server-side only. No API route exposes them to clients.

## audit_logs
| column | type |
| --- | --- |
| id | int PK |
| user_id | text |
| action | text |
| entity_id | text |
| metadata | jsonb |
| timestamp | text |

Common actions: `USER_REGISTERED`, `APPOINTMENT_CREATED`,
`APPOINTMENT_CANCELLED`, `APPOINTMENT_RESCHEDULED`, `SLOT_HOLD_CREATED`,
`DOCTOR_LEAVE_CREATED`, `CALENDAR_CONNECTED`, `VISIT_COMPLETED`,
`WAITLIST_JOINED`, `WAITLIST_NOTIFIED`, `WAITLIST_CLAIMED`,
`WAITLIST_CLAIM_EXPIRED`, `WAITLIST_CANCELLED`.

## waitlist
| column | type |
| --- | --- |
| id | text PK | uuid |
| patient_id | text | |
| doctor_id | text | |
| requested_start, requested_end | text | ISO-8601 UTC |
| status | text | `WAITING` / `NOTIFIED` / `BOOKED` / `CANCELLED` / `EXPIRED` |
| claim_expires_at | text | ISO-8601 UTC (only while `NOTIFIED`) |
| appointment_id | text | set when the entry is `BOOKED` |
| created_at | timestamptz | |
| updated_at | text | |

Partial unique index:
`UNIQUE(patient_id, doctor_id, requested_start) WHERE status IN ('WAITING','NOTIFIED')`
guarantees a patient cannot join the same slot's waitlist twice.

Index: `(doctor_id, requested_start, status)` for fast promotion lookups.
