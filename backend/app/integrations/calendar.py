"""Calendar invites via standard .ics files (iCalendar, RFC 5545).

No external service, no OAuth, no API keys. The app builds a self-contained
.ics attachment locally and the caller sends it on the relevant email
(booking confirmation, reschedule, cancellation). Any RFC 5545-compliant
calendar client — Google Calendar, Outlook, Apple Calendar — recognizes a
``text/calendar`` attachment and offers to add/update/remove the event; no
account connection is required on either side.
"""
from __future__ import annotations
from datetime import datetime, timezone


def _dt(iso: str) -> str:
    """Format an ISO datetime string as an iCalendar UTC DATE-TIME (YYYYMMDDTHHMMSSZ)."""
    d = datetime.fromisoformat(iso)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _escape(text: str) -> str:
    """Escape text per RFC 5545 §3.3.11 (backslash, semicolon, comma, newline)."""
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def build_ics(
    *,
    uid: str,
    start_iso: str,
    end_iso: str,
    summary: str,
    description: str = "",
    location: str = "",
    organizer_email: str = "",
    attendee_emails: list[str] | None = None,
    method: str = "REQUEST",
    sequence: int = 0,
) -> str:
    """Build a single-event .ics file. method is REQUEST (create/update) or CANCEL."""
    method = method.upper()
    status = "CANCELLED" if method == "CANCEL" else "CONFIRMED"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//SmartCare//Appointment Scheduler//EN",
        "CALSCALE:GREGORIAN",
        f"METHOD:{method}",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_dt(datetime.now(timezone.utc).isoformat())}",
        f"DTSTART:{_dt(start_iso)}",
        f"DTEND:{_dt(end_iso)}",
        f"SEQUENCE:{sequence}",
        f"STATUS:{status}",
        f"SUMMARY:{_escape(summary)}",
    ]
    if description:
        lines.append(f"DESCRIPTION:{_escape(description)}")
    if location:
        lines.append(f"LOCATION:{_escape(location)}")
    if organizer_email:
        lines.append(f"ORGANIZER:mailto:{organizer_email}")
    for email in attendee_emails or []:
        if email:
            lines.append(f"ATTENDEE;ROLE=REQ-PARTICIPANT;RSVP=TRUE:mailto:{email}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    # RFC 5545 requires CRLF line endings.
    return "\r\n".join(lines) + "\r\n"
