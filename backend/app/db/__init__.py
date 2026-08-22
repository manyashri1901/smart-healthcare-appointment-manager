"""Repository selector. Uses PostgreSQL if DATABASE_URL is configured, else MongoDB.

Both implementations expose the same async interface so business logic and API
routes remain identical regardless of the backing store.
"""
from .. import config

_repo = None


def repo():
    global _repo
    if _repo is not None:
        return _repo
    if config.use_postgres():
        from .postgres_repo import PostgresRepo
        _repo = PostgresRepo(config.DATABASE_URL)
    else:
        from .mongo_repo import MongoRepo
        _repo = MongoRepo(config.MONGO_URL, config.DB_NAME)
    return _repo


async def init_repo():
    await repo().init()


async def close_repo():
    if _repo is not None:
        await _repo.close()
