# SmartCare System Design

## A. Concurrent Appointment Booking and Double-Booking Prevention

SmartCare uses **PostgreSQL as the transactional source of truth** for appointment scheduling. Availability checks at the application layer are treated as advisory; the final concurrency guarantee is enforced by the database.

The `appointments` table defines a partial unique index on `(doctor_id, start)` for active appointments:

`UNIQUE (doctor_id, start) WHERE status IN ('HELD', 'CONFIRMED')`

The booking service executes critical operations within an asynchronous database transaction. It validates the requested slot, checks for an existing active appointment or hold, and persists the booking. Row-level locking (`SELECT ... FOR UPDATE`) is used when an existing competing hold must be serialized.

If concurrent transactions attempt to reserve the same slot, PostgreSQL's unique constraint permits only one transaction to establish the active booking. A resulting `IntegrityError` is caught by the service layer and returned as `409 SLOT_UNAVAILABLE`.

This provides the following invariant:

> For a given `doctor_id` and appointment start time, at most one appointment may have an active `HELD` or `CONFIRMED` status.

Downstream operations such as notifications and AI processing are initiated only after the booking transaction has committed successfully.

---

## B. Doctor Leave and Appointment Conflict Management

Doctor leave is persisted in the `doctor_leaves` table using a unique `(doctor_id, date)` constraint, making leave registration idempotent.

When leave is created, the service:

1. Validates the doctor.
2. Retrieves affected `CONFIRMED` appointments for the specified doctor and date.
3. Persists the leave record.
4. Updates affected appointments to `CANCELLED` with the cancellation reason `DOCTOR_LEAVE`.
5. Creates `LEAVE_CONFLICT` notification records for affected patients.
6. Records the operation in `audit_logs`.

The `(doctor_id, start)` appointment index supports efficient identification of affected appointments.

Availability queries consult the `doctor_leaves` table and exclude slots falling within registered leave dates.

Notification delivery is decoupled from the leave operation. The database state is therefore committed independently of SMTP availability or notification-processing failures.

---

## C. Temporary Slot Reservation

SmartCare implements a five-minute temporary hold mechanism to prevent a selected slot from being claimed by another patient while the current patient completes the booking workflow.

The hold lifecycle is:

```text
AVAILABLE
    │
    ▼
POST /appointments/hold
    │
    ▼
HELD ───────────────► CONSUMED
 │                         │
 │                         ▼
 │                    CONFIRMED
 │
 ▼
EXPIRED
```

A hold contains `doctor_id`, `patient_id`, `start`, `end`, `expires_at`, and its current status.

The confirmation operation validates that the hold is still active and performs the `HELD → CONSUMED` transition atomically before finalizing the appointment.

If the hold has expired or is no longer valid, confirmation returns `409` and the appointment creation path is not executed.

APScheduler periodically identifies expired holds and changes their status to `EXPIRED`. Availability queries additionally evaluate `expires_at`, ensuring expired holds do not remain logically unavailable even if the scheduled cleanup task has not yet executed.

---

## D. Transaction Boundaries and External Service Isolation

SmartCare follows a **transaction-first, asynchronous-processing** model.

The appointment transaction is responsible only for durable application state, including the appointment, hold transition, and related database records. The transaction is committed before external integrations are invoked.

The resulting flow is:

```text
Validate Request
      │
      ▼
PostgreSQL Transaction
      │
      ├── Validate Slot
      ├── Validate Hold
      ├── Create/Update Appointment
      └── Commit
             │
             ▼
      Background Processing
        ├── Email
        └── AI Generation
```

This prevents failures in external services from rolling back successful appointment transactions.

---

## E. Notification Processing and Retry Strategy

SmartCare persists notifications in the `notifications` table before delivery. Notifications initially use `PENDING` status and are processed asynchronously through the configured SMTP service.

The notification worker selects records whose status is `PENDING` or `RETRY` and whose `next_retry_at` has been reached.

Transient delivery failures use exponential retry intervals:

| Attempt | Retry Delay |
| ------- | ----------: |
| 1       |    1 minute |
| 2       |   5 minutes |
| 3       |  15 minutes |

After `NOTIFICATION_MAX_RETRIES`, the notification is marked `FAILED`. If SMTP is not configured or unavailable at the configuration level, the notification is marked `UNAVAILABLE`.

Notification failure does not modify the associated appointment or other transactional records.

---

## F. AI-Assisted Processing

SmartCare integrates **OpenAI** for AI-assisted functionality using the configured model:

`openai/gpt-oss-20b`

AI processing is asynchronous and isolated from transactional appointment operations. Provider failures, authentication errors, timeouts, malformed responses, and other processing exceptions are captured in the `ai_summaries` table.

Each AI result maintains an explicit processing status such as `PENDING`, `COMPLETED`, `FAILED`, or `UNAVAILABLE`.

The system always retains the original patient-provided symptoms independently of AI processing. AI output is therefore an assistive layer and does not replace the original clinical information.

---

## G. Application Calendar

SmartCare includes a **native calendar module within the application**.

The calendar uses appointment data persisted in PostgreSQL as its source of truth. Appointment creation, confirmation, rescheduling, cancellation, and completion are reflected in the application's calendar interface.

No external calendar provider, OAuth flow, third-party calendar API, or external synchronization service is required.

This design keeps scheduling and calendar state within the SmartCare platform and eliminates an additional external dependency from the core appointment workflow.

---

## H. Reliability and Consistency Model

The system separates **transactional responsibilities** from **non-critical external processing**.

PostgreSQL provides durable and consistent storage for users, appointments, holds, doctor leaves, clinical records, notifications, AI summaries, medication reminders, waitlist entries, and audit logs. Database constraints, transactions, and row-level locking protect critical scheduling operations.

APScheduler handles time-based background operations, while asynchronous workers process notifications and AI tasks independently.

Consequently, temporary failures of SMTP, OpenAI, or background processing do not compromise the integrity of the core healthcare workflow:

**Availability → Hold → Confirmation → Consultation → Follow-up**

The architecture prioritizes **data consistency, concurrency safety, fault isolation, and continued availability of core clinical operations**.
