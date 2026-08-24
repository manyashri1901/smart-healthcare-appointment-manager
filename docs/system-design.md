# SmartCare System Design

Word count target: ≤ 800.

## A. Double-Booking Prevention

Two patients can click the same 30-minute slot at the same millisecond.
Because network latency between the browsers is unequal, both requests can
reach the API in parallel and pass any client-side availability check.
SmartCare enforces uniqueness in the storage layer so exactly one of the two
requests can succeed.

**PostgreSQL adapter.** The `appointments` table declares a partial unique
index: `UNIQUE(doctor_id, start) WHERE status IN ('HELD','CONFIRMED')`. The
booking flow runs inside an async transaction that (1) locks any competing
`HELD` hold row with `SELECT … FOR UPDATE`, (2) checks for a pre-existing
active appointment, then (3) inserts the appointment. A concurrent second
transaction either finds the locked row or triggers a unique-constraint
`IntegrityError`; in both cases the API responds `409 SLOT_UNAVAILABLE`. Only
after commit does the API dispatch downstream work (email, AI, calendar).

**MongoDB adapter.** A partial unique index on `holds` and `appointments`
covers the same `(doctor_id, start)` tuple restricted to active statuses.
`create_hold` performs an atomic `insert_one`; a duplicate-key exception is
translated to a `409`. The service layer additionally consults `busy_starts`
before creating the hold, ensuring the pre-check and insert are effectively
serialized. `find_one_and_update` is used to atomically flip the hold from
`HELD` to `CONSUMED` at confirmation time.

The single guarantee is: **there is never more than one active
(HELD or CONFIRMED) row for a given (doctor_id, appointment_start).**

## B. Doctor Leave Conflict Handling

When an admin registers a leave date:

1. Validate the doctor exists.
2. Find all `CONFIRMED` appointments whose `start` prefix matches the leave
   date. This is a cheap indexed lookup on `(doctor_id, start)`.
3. Persist the leave record (idempotent upsert on the composite key).
4. For each affected appointment: mark it `CANCELLED` with reason
   `DOCTOR_LEAVE` and enqueue a `LEAVE_CONFLICT` email to the patient.
5. Write an `audit_logs` row capturing the affected count.
6. New availability queries automatically exclude the leave date via the
   `leaves` collection/table.

Because the leave upsert and appointment cancellation happen sequentially in
the request handler while the notification email is only *enqueued* (sent
later by the background worker), an SMTP outage does not block the leave
being recorded.

## C. Slot Hold Mechanism

Holds implement a lightweight optimistic reservation so that a patient can
walk through the symptom form without racing another patient for the same
slot.

```
AVAILABLE ─► POST /appointments/hold ─► HELD (expires_at = now + 5 min)
HELD      ─► POST /appointments/confirm ─► CONSUMED + CONFIRMED appointment
HELD      ─► APScheduler ─► EXPIRED (after expires_at)
```

Confirmation atomically flips the hold from `HELD` to `CONSUMED` and inserts
the appointment. If the hold has already expired the transition fails and the
API returns `409` — the appointment insert is never attempted.

An APScheduler job runs every 30 seconds to sweep `HELD` holds whose
`expires_at` has passed and marks them `EXPIRED`. Even without this job the
system is correct because availability queries always ignore holds whose
`expires_at <= now()`. The sweep exists so admins see clean state and holds
never occupy a partial unique index slot forever.

## D. Notification Failure Handling

Emails and AI generation are strictly **post-transactional**. The
appointment commit is durable *before* either runs:

```
tx commit ─► build .ics invite (local, synchronous, cannot fail on I/O)
          ─► enqueue email row (status=PENDING, next_retry_at=now, .ics attached)
          ─► BackgroundTasks: LLM pre-visit generation
```

The `process_pending_emails` job picks up rows where `status IN
{PENDING,RETRY}` and `next_retry_at <= now()`. If SMTP is unconfigured the
row is marked `UNAVAILABLE`. If sending fails the row is rescheduled with an
exponential backoff — attempt 1 waits 1 minute, attempt 2 five minutes,
attempt 3 fifteen minutes. After `NOTIFICATION_MAX_RETRIES` the row is
`FAILED`; the appointment itself is untouched.

The LLM adapter is provider-agnostic: `LLM_PROVIDER ∈ {anthropic, openai,
emergent}`. Any exception (missing key, invalid JSON, HTTP error, timeout)
is caught and the AI summary row records `status=FAILED` with a truncated
error string. Doctors always see the *original* patient symptoms; the AI
result is presented alongside as an aid, never a replacement.

### Calendar integration: .ics invites, not live Google Calendar sync

This was originally built as live Google Calendar OAuth sync (per-user
token storage, `create`/`update`/`delete` against the Calendar API). That's
gone. **Why:** shipping a Calendar API integration in production mode
requires Google's OAuth app verification, which requires business/billing
verification on the Cloud project — unavailable in this setup, and the
"unverified app, 100 test users" cap doesn't cover a real deployment. An
external approval blocker, not a code problem.

**Replacement:** `app/integrations/calendar.py` builds a standard `.ics`
file (RFC 5545) locally — pure string formatting, no network call, so it
can't fail the way an API call can — attached to the same email the
booking/reschedule/cancellation flow already sends. `Notification` carries
`attachment_filename`/`attachment_content`/`ics_method` alongside its
existing retry/backoff machinery, so there's no separate delivery path. A
reschedule reuses the original appointment's id as the calendar UID with
an incremented `SEQUENCE`, so a compliant client updates the existing
event instead of duplicating it; cancellation sends `METHOD:CANCEL` on
the same UID.

**Trade-off:** one-way, point-in-time — the patient's calendar reflects
the appointment as of when they opened the invite, not pushed live
afterward. Traded for zero external dependencies and no approval process.

Together these patterns ensure that **the primary healthcare workflow —
book, hold, confirm, visit, follow-up — is always available even when every
external system is degraded.**
