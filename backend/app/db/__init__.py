"""Repository selector. PostgreSQL is the only backing store."""
from .. import config

_repo = None


def repo():
    global _repo
    if _repo is not None:
        return _repo
    if not config.DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set (checked backend/.env via app.config). "
            "SmartCare requires a PostgreSQL connection string to start."
        )
    from .postgres_repo import PostgresRepo
    _repo = PostgresRepo(config.DATABASE_URL)
    return _repo


async def init_repo():
    await repo().init()


async def close_repo():
    if _repo is not None:
        await _repo.close()
