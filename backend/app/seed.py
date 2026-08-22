"""Idempotent seed data for development."""
import uuid
from .db import repo
from .security import hash_password, now


SEED_PASSWORD = "PulseCare123!"

USERS = [
    ("Admin User",  "admin@pulsecare.example.com",  "ADMIN",  None,             None,  None),
    ("Dr. Maya Chen",    "maya@pulsecare.example.com",   "DOCTOR", "General Physician", "MD FRACGP", "8 years"),
    ("Dr. Elias Morgan", "elias@pulsecare.example.com",  "DOCTOR", "Dermatologist",     "MD",       "12 years"),
    ("Dr. Priya Shah",   "priya@pulsecare.example.com",  "DOCTOR", "Cardiologist",      "MD DM",    "15 years"),
    ("Alex Rivera",   "alex@pulsecare.example.com",   "PATIENT", None, None, None),
    ("Bea Iyer",      "bea@pulsecare.example.com",    "PATIENT", None, None, None),
    ("Chen Wu",       "chen@pulsecare.example.com",   "PATIENT", None, None, None),
    ("Diana Fields",  "diana@pulsecare.example.com",  "PATIENT", None, None, None),
    ("Emeka Osei",    "emeka@pulsecare.example.com",  "PATIENT", None, None, None),
]


async def seed():
    r = repo()
    for name, email, role, spec, qual, exp in USERS:
        if await r.get_user_by_email(email):
            continue
        user = {
            "id": str(uuid.uuid4()),
            "name": name,
            "email": email,
            "password": hash_password(SEED_PASSWORD),
            "role": role,
            "status": "ACTIVE",
            "specialization": spec,
            "qualification": qual,
            "experience": exp,
            "phone": "",
            "work_start": "09:00",
            "work_end": "17:00",
            "slot_duration": 30,
            "created_at": now(),
        }
        await r.create_user(user)
