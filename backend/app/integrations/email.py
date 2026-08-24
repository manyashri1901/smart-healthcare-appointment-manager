"""SMTP email adapter (Mailtrap-compatible).

If SMTP credentials are missing, the adapter returns ``UNAVAILABLE`` and the
notification worker records the state. Appointment workflow is unaffected.
"""
from __future__ import annotations
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from .. import config

log = logging.getLogger("email")


def configured() -> bool:
    return bool(config.SMTP_HOST and config.SMTP_USER and config.SMTP_PASS)


async def send_email(
    to: str,
    subject: str,
    body: str,
    attachment_filename: str | None = None,
    attachment_content: str | None = None,
    ics_method: str = "REQUEST",
) -> tuple[bool, str]:
    """Return (ok, error_message). Never raises.

    If attachment_filename/attachment_content are provided, the email is sent
    as a multipart message with a text/calendar (.ics) part — standard enough
    that Gmail, Outlook, and Apple Mail all offer to add it automatically.
    """
    if not configured():
        return False, "SMTP not configured"
    if not to:
        return False, "Missing recipient"

    if attachment_filename and attachment_content:
        msg = MIMEMultipart("mixed")
        msg.attach(MIMEText(body, "html", "utf-8"))
        ics_part = MIMEText(attachment_content, "calendar", "utf-8")
        ics_part.set_param("method", ics_method.upper())
        ics_part.set_param("name", attachment_filename)
        ics_part.add_header("Content-Disposition", "attachment", filename=attachment_filename)
        msg.attach(ics_part)
    else:
        msg = MIMEText(body, "html", "utf-8")

    msg["From"] = config.MAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    try:
        await aiosmtplib.send(
            msg,
            hostname=config.SMTP_HOST,
            port=config.SMTP_PORT,
            username=config.SMTP_USER,
            password=config.SMTP_PASS,
            start_tls=config.SMTP_PORT != 465,
            use_tls=config.SMTP_PORT == 465,
            timeout=15,
        )
        return True, ""
    except Exception as e:  # pragma: no cover — external service
        log.warning("SMTP send failed: %s", e)
        return False, str(e)[:400]
