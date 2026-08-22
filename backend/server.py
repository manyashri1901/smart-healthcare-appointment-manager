"""PulseCare API — main FastAPI application."""
from contextlib import asynccontextmanager
import logging

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.db import repo, init_repo, close_repo
from app.jobs import build_scheduler
from app.seed import seed
from app.routes import auth, doctors, appointments, admin
from app.routes import calendar as calendar_routes
from app.routes import waitlist as waitlist_routes

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pulsecare")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_repo()
    await seed()
    scheduler = build_scheduler()
    scheduler.start()
    app.state.scheduler = scheduler
    log.info("PulseCare started · db=%s", repo().kind)
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        await close_repo()


app = FastAPI(title="PulseCare API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

api = APIRouter(prefix="/api")


@api.get("/health")
async def health():
    return {"status": "ok", "service": "pulsecare", "db": repo().kind}


@api.get("/health/db")
async def health_db():
    await repo().ping()
    return {"status": "ok", "database": repo().kind}


api.include_router(auth.router)
api.include_router(doctors.router)
api.include_router(appointments.router)
api.include_router(admin.router)
api.include_router(calendar_routes.router)
api.include_router(waitlist_routes.router)

app.include_router(api)


@app.get("/health")
async def root_health():
    return {"status": "ok"}
