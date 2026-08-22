"""Environment-driven configuration."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def env(key: str, default: str | None = None) -> str | None:
    v = os.environ.get(key)
    return v if v not in (None, "") else default


# Core
JWT_SECRET = env("JWT_SECRET", "pulsecare-development-secret")
CORS_ORIGINS = (env("CORS_ORIGINS", "*") or "*").split(",")
FRONTEND_URL = env("FRONTEND_URL", "http://localhost:3000")
BACKEND_URL = env("BACKEND_URL", "http://localhost:8001")

# Database selection: PostgreSQL if DATABASE_URL is set, else MongoDB.
DATABASE_URL = env("DATABASE_URL")
MONGO_URL = env("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = env("DB_NAME", "pulsecare")

# LLM (provider-agnostic)
LLM_PROVIDER = env("LLM_PROVIDER")            # anthropic | openai | emergent | ""
LLM_API_KEY = env("LLM_API_KEY")
LLM_MODEL = env("LLM_MODEL", "claude-haiku-4-5")
LLM_BASE_URL = env("LLM_BASE_URL")            # optional, for OpenAI-compatible endpoints

# Email (Mailtrap SMTP or any SMTP)
SMTP_HOST = env("SMTP_HOST")
SMTP_PORT = int(env("SMTP_PORT", "587") or 587)
SMTP_USER = env("SMTP_USER")
SMTP_PASS = env("SMTP_PASS")
MAIL_FROM = env("MAIL_FROM", "no-reply@pulsecare.example.com")

# Google Calendar OAuth
GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = env("GOOGLE_REDIRECT_URI", f"{BACKEND_URL}/api/calendar/google/callback")

# Slot hold TTL
SLOT_HOLD_MINUTES = int(env("SLOT_HOLD_MINUTES", "5") or 5)

# Notification retry
NOTIFICATION_MAX_RETRIES = int(env("NOTIFICATION_MAX_RETRIES", "3") or 3)


def use_postgres() -> bool:
    return bool(DATABASE_URL)
