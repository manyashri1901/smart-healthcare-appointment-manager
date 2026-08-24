# SmartCare API

Full Swagger UI is available at `${BACKEND_URL}/docs`.

Every route below is prefixed with `/api`. Auth-protected routes require the
`Authorization: Bearer <jwt>` header.

## Health
| Method | Path | Notes |
| --- | --- | --- |
| GET | `/health` | Service liveness |
| GET | `/health/db` | Database connectivity — returns `db=mongo` or `db=postgres` |

## Auth
| Method | Path | Body | Role |
| --- | --- | --- | --- |
| POST | `/auth/register` | `{name, email, password}` | Public |
| POST | `/auth/login` | `{email, password}` | Public |
| GET  | `/auth/me` | – | Any authenticated |

## Doctors (directory)
| Method | Path | Query | Role |
| --- | --- | --- | --- |
| GET | `/doctors` | `?specialization=` | Any authenticated |
| GET | `/doctors/{id}` | | Any authenticated |
| GET | `/doctors/{id}/availability` | `?date=YYYY-MM-DD` | Any authenticated |

## Appointments
| Method | Path | Body | Role | Notes |
| --- | --- | --- | --- | --- |
| POST  | `/appointments/hold` | `{doctor_id, start, end}` | Patient | Returns 409 on conflict |
| POST  | `/appointments/confirm` | `{hold_id, chief_complaint, symptoms, symptom_duration, severity, additional_notes}` | Patient | |
| GET   | `/appointments` | | Any auth | Filtered by role |
| GET   | `/appointments/{id}` | | Party of appointment | Includes clinical + AI summaries |
| GET   | `/appointments/{id}/medications` | | Party of appointment | |
| PATCH | `/appointments/{id}/cancel` | | Any party | |
| PATCH | `/appointments/{id}/reschedule` | `{start, end}` | Patient | Returns 409 on conflict |
| POST  | `/appointments/{id}/clinical-notes` | `{clinical_notes, diagnosis, medications[], follow_up_instructions, follow_up_date}` | Doctor | Completes visit |

### 409 response
```json
{"detail": "This slot is no longer available"}
```

## Calendar invites

There is no calendar API — no routes, no OAuth, no per-user connection.
`POST /appointments/confirm`, `PATCH /appointments/{id}/reschedule`, and
`PATCH /appointments/{id}/cancel` each generate a standard `.ics` file
(RFC 5545) locally and attach it to the email that route already sends
(`BOOKING_CONFIRMED`, `APPOINTMENT_RESCHEDULED`, `APPOINTMENT_CANCELLED`).
See `docs/system-design.md` for why this replaced live Google Calendar sync.

## Admin
| Method | Path | Body | Role |
| --- | --- | --- | --- |
| GET   | `/admin/overview` | | Admin |
| GET   | `/admin/users` | `?role=` | Admin |
| GET   | `/admin/doctors` | | Admin |
| POST  | `/admin/doctors` | Doctor payload | Admin |
| PATCH | `/admin/doctors/{id}` | Partial doctor payload | Admin |
| GET   | `/admin/doctors/{id}/leaves` | | Admin |
| POST  | `/admin/doctors/{id}/leave` | `{date}` | Admin |
| DELETE | `/admin/doctors/{id}/leave/{date}` | | Admin |
| GET   | `/admin/appointments` | | Admin |
| GET   | `/admin/notifications` | | Admin |
| GET   | `/admin/audit` | | Admin |
| GET   | `/admin/waitlist` | | Admin |
| GET   | `/admin/insights` | `?days=7` (1-30) | Admin | Cancellations, waitlist conversions, avg wait, rebooked patients, per-day cancellation series |

## Waitlist
| Method | Path | Body | Role | Notes |
| --- | --- | --- | --- | --- |
| POST   | `/waitlist` | `{doctor_id, start, end}` | Patient | 409 if duplicate active entry |
| GET    | `/waitlist/mine` | | Patient | Includes `doctor_name`, `status`, `claim_expires_at` |
| DELETE | `/waitlist/{id}` | | Patient | Allowed for `WAITING` or `NOTIFIED` entries |
| POST   | `/waitlist/{id}/claim` | `{chief_complaint, symptoms, symptom_duration, severity, additional_notes}` | Patient | Must be `NOTIFIED`; consumes the promotion window |

## Auth & error format

All errors respond with FastAPI's default `{"detail": "..."}` and standard
HTTP codes: 400 (bad request), 401 (unauthenticated), 403 (forbidden), 404
(not found), 409 (conflict / slot unavailable), 422 (validation), 500
(unexpected server error — see the booking endpoints' error handling).
