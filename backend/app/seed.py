"""Idempotent seed data for development."""
import uuid
from .db import repo
from .security import hash_password, now


SEED_PASSWORD = "SmartCare123!"

# work_start/work_end are stored (and interpreted by the availability
# endpoint) as UTC times. Doctor hours below are chosen so they display as
# sensible local business hours for an IST (UTC+5:30) viewer:
#   03:30-11:30 UTC -> 09:00-17:00 IST
#   04:30-13:30 UTC -> 10:00-19:00 IST
USERS = [
    ("Admin User",  "admin@smartcare.example.com",  "ADMIN",  None,             None,  None, "09:00", "17:00"),
    ("Dr. Maya Chen",    "maya@smartcare.example.com",   "DOCTOR", "General Physician", "MD FRACGP", "8 years", "03:30", "11:30"),
    ("Dr. Elias Morgan", "elias@smartcare.example.com",  "DOCTOR", "Dermatologist",     "MD",       "12 years", "04:30", "13:30"),
    ("Dr. Priya Shah",   "priya@smartcare.example.com",  "DOCTOR", "Cardiologist",      "MD DM",    "15 years", "03:30", "11:30"),
    ("Alex Rivera",   "alex@smartcare.example.com",   "PATIENT", None, None, None, "09:00", "17:00"),
    ("Bea Iyer",      "bea@smartcare.example.com",    "PATIENT", None, None, None, "09:00", "17:00"),
    ("Chen Wu",       "chen@smartcare.example.com",   "PATIENT", None, None, None, "09:00", "17:00"),
    ("Diana Fields",  "diana@smartcare.example.com",  "PATIENT", None, None, None, "09:00", "17:00"),
    ("Emeka Osei",    "emeka@smartcare.example.com",  "PATIENT", None, None, None, "09:00", "17:00"),
]


async def seed():
    r = repo()
    for name, email, role, spec, qual, exp, work_start, work_end in USERS:
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
            "work_start": work_start,
            "work_end": work_end,
            "slot_duration": 30,
            "created_at": now(),
        }
        await r.create_user(user)
