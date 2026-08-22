"""APScheduler background jobs — cleanup expired holds, retry emails, dispatch reminders."""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .db import repo
from . import services

log = logging.getLogger("jobs")


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")

    @scheduler.scheduled_job("interval", seconds=30, id="expire_holds", max_instances=1)
    async def expire_holds():
        try:
            n = await repo().expire_holds()
            if n:
                log.info("Expired %d holds", n)
        except Exception as e:  # pragma: no cover
            log.warning("expire_holds failed: %s", e)

    @scheduler.scheduled_job("interval", seconds=45, id="process_emails", max_instances=1)
    async def process_emails():
        try:
            await services.process_pending_emails()
        except Exception as e:  # pragma: no cover
            log.warning("process_emails failed: %s", e)

    @scheduler.scheduled_job("interval", seconds=60, id="process_reminders", max_instances=1)
    async def process_reminders():
        try:
            await services.process_due_reminders()
        except Exception as e:  # pragma: no cover
            log.warning("process_reminders failed: %s", e)

    @scheduler.scheduled_job("interval", seconds=30, id="process_expired_waitlist", max_instances=1)
    async def process_expired_waitlist():
        try:
            await services.process_expired_waitlist()
        except Exception as e:  # pragma: no cover
            log.warning("process_expired_waitlist failed: %s", e)

    return scheduler
