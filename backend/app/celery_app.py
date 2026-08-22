"""Celery worker entry point — reuses the same service layer as APScheduler.

Enable in production by starting a worker alongside FastAPI:

    celery -A app.celery_app worker --loglevel=info --beat

The beat schedule triggers the same coroutines used by APScheduler in the
preview so job logic is defined exactly once.
"""
import asyncio
import os

from celery import Celery
from celery.schedules import crontab

from .db import init_repo, repo
from . import services

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery = Celery("pulsecare", broker=REDIS_URL, backend=REDIS_URL)
celery.conf.beat_schedule = {
    "expire-holds": {"task": "app.celery_app.expire_holds", "schedule": 30.0},
    "process-emails": {"task": "app.celery_app.process_emails", "schedule": 45.0},
    "process-reminders": {"task": "app.celery_app.process_reminders", "schedule": 60.0},
}


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(init_repo())
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery.task
def expire_holds():
    return _run(repo().expire_holds())


@celery.task
def process_emails():
    return _run(services.process_pending_emails())


@celery.task
def process_reminders():
    return _run(services.process_due_reminders())
