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
# Origins allowed to call the API — this is what actually controls CORS
# (see server.py's CORSMiddleware). Comma-separated, e.g.
# "http://localhost:3000,https://app.example.com".
CORS_ORIGINS = (env("CORS_ORIGINS", "*") or "*").split(",")
BACKEND_URL = env("BACKEND_URL", "http://localhost:8001")

# PostgreSQL connection string — required, no fallback.
DATABASE_URL = env("DATABASE_URL")

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
MAIL_FROM = env("MAIL_FROM", "no-reply@smartcare.example.com")

# Slot hold TTL
SLOT_HOLD_MINUTES = int(env("SLOT_HOLD_MINUTES", "5") or 5)

# Waitlist claim window — how long a notified patient has to claim a freed slot.
WAITLIST_CLAIM_MINUTES = int(env("WAITLIST_CLAIM_MINUTES", "10") or 10)

# Notification retry
NOTIFICATION_MAX_RETRIES = int(env("NOTIFICATION_MAX_RETRIES", "3") or 3)
