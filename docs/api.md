# PulseCare API

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

## Google Calendar
| Method | Path | Role | Notes |
| --- | --- | --- | --- |
| GET | `/calendar/status` | Any auth | Returns `{configured, connected}` |
| GET | `/calendar/google/connect` | Any auth | Returns `{url}` — redirect the user |
| GET | `/calendar/google/callback` | – | OAuth redirect endpoint |
| DELETE | `/calendar/google/disconnect` | Any auth | Removes tokens |

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

## Auth & error format

All errors respond with FastAPI's default `{"detail": "..."}` and standard
HTTP codes: 400 (bad request), 401 (unauthenticated), 403 (forbidden), 404
(not found), 409 (conflict / slot unavailable), 422 (validation), 503
(integration not configured).
