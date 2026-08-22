"""End-to-end backend smoke tests.

Runs against the live FastAPI server; the CI script starts uvicorn before
executing.
"""
import os
import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest


API = os.environ.get("PULSECARE_API", "http://localhost:8001/api")
PATIENT = ("alex@pulsecare.example.com", "PulseCare123!")
PATIENT_B = ("bea@pulsecare.example.com", "PulseCare123!")
DOCTOR = ("maya@pulsecare.example.com", "PulseCare123!")
ADMIN = ("admin@pulsecare.example.com", "PulseCare123!")


def next_weekday(days_ahead=1):
    d = datetime.now(timezone.utc) + timedelta(days=days_ahead)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d.date().isoformat()


async def _login(email, password):
    async with httpx.AsyncClient(base_url=API) as c:
        r = await c.post("/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        return r.json()["token"]


@pytest.mark.asyncio
async def test_login_all_roles():
    for creds in (PATIENT, DOCTOR, ADMIN):
        await _login(*creds)


@pytest.mark.asyncio
async def test_role_authorization_enforced():
    token = await _login(*PATIENT)
    async with httpx.AsyncClient(base_url=API, headers={"Authorization": f"Bearer {token}"}) as c:
        r = await c.get("/admin/overview")
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_booking_and_double_booking_prevented():
    token_a = await _login(*PATIENT)
    token_b = await _login(*PATIENT_B)
    async with httpx.AsyncClient(base_url=API, headers={"Authorization": f"Bearer {token_a}"}) as c:
        doctors = (await c.get("/doctors")).json()
        assert doctors
        doctor_id = doctors[0]["id"]
        date = next_weekday(2)
        slots = (await c.get(f"/doctors/{doctor_id}/availability", params={"date": date})).json()
        assert slots, "expected free slots"
        slot = slots[0]
        # Patient A books
        hold_a = await c.post("/appointments/hold", json={"doctor_id": doctor_id, **slot})
        assert hold_a.status_code == 200
        conf_a = await c.post(
            "/appointments/confirm",
            json={
                "hold_id": hold_a.json()["id"],
                "chief_complaint": "headache",
                "symptoms": "pounding",
                "symptom_duration": "2 days",
                "severity": "Mild",
                "additional_notes": "",
            },
        )
        assert conf_a.status_code == 200

    # Patient B tries the exact same slot -> must 409
    async with httpx.AsyncClient(base_url=API, headers={"Authorization": f"Bearer {token_b}"}) as c:
        hold_b = await c.post("/appointments/hold", json={"doctor_id": doctor_id, **slot})
        assert hold_b.status_code == 409, hold_b.text


@pytest.mark.asyncio
async def test_slot_outside_working_hours_rejected():
    token = await _login(*PATIENT)
    async with httpx.AsyncClient(base_url=API, headers={"Authorization": f"Bearer {token}"}) as c:
        doctors = (await c.get("/doctors")).json()
        doctor_id = doctors[0]["id"]
        date = next_weekday(3)
        bad_start = f"{date}T02:00:00+00:00"
        bad_end = f"{date}T02:30:00+00:00"
        r = await c.post("/appointments/hold", json={"doctor_id": doctor_id, "start": bad_start, "end": bad_end})
        assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_past_slot_rejected():
    token = await _login(*PATIENT)
    async with httpx.AsyncClient(base_url=API, headers={"Authorization": f"Bearer {token}"}) as c:
        doctors = (await c.get("/doctors")).json()
        doctor_id = doctors[0]["id"]
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        past_end = (datetime.now(timezone.utc) - timedelta(days=1, minutes=-30)).isoformat()
        r = await c.post("/appointments/hold", json={"doctor_id": doctor_id, "start": past, "end": past_end})
        assert r.status_code in (400, 409)


@pytest.mark.asyncio
async def test_admin_leave_conflict_flow():
    admin_token = await _login(*ADMIN)
    async with httpx.AsyncClient(base_url=API, headers={"Authorization": f"Bearer {admin_token}"}) as c:
        doctors = (await c.get("/admin/doctors")).json()
        doctor_id = doctors[0]["id"]
        date = next_weekday(4)
        r = await c.post(f"/admin/doctors/{doctor_id}/leave", json={"date": date})
        assert r.status_code == 200
        # cleanup
        await c.delete(f"/admin/doctors/{doctor_id}/leave/{date}")


@pytest.mark.asyncio
async def test_llm_failure_does_not_block_booking():
    # LLM is intentionally unconfigured in the preview → ai_status should be
    # UNAVAILABLE but the appointment still confirms.
    token = await _login(*PATIENT)
    async with httpx.AsyncClient(base_url=API, headers={"Authorization": f"Bearer {token}"}) as c:
        doctors = (await c.get("/doctors")).json()
        doctor_id = doctors[0]["id"]
        date = next_weekday(5)
        slots = (await c.get(f"/doctors/{doctor_id}/availability", params={"date": date})).json()
        if not slots:
            pytest.skip("no free slots")
        slot = slots[0]
        hold = await c.post("/appointments/hold", json={"doctor_id": doctor_id, **slot})
        if hold.status_code == 409:
            pytest.skip("slot taken")
        confirm = await c.post(
            "/appointments/confirm",
            json={
                "hold_id": hold.json()["id"],
                "chief_complaint": "cough",
                "symptoms": "dry",
                "symptom_duration": "3 days",
                "severity": "Mild",
                "additional_notes": "",
            },
        )
        assert confirm.status_code == 200
        appt_id = confirm.json()["id"]
        await asyncio.sleep(1.5)
        detail = (await c.get(f"/appointments/{appt_id}")).json()
        assert detail["status"] == "CONFIRMED"  # unaffected by LLM/email


@pytest.mark.asyncio
async def test_waitlist_end_to_end():
    """Book → duplicate waitlist blocked → cancel → NOTIFIED → claim → BOOKED."""
    token_a = await _login(*PATIENT)
    token_b = await _login(*PATIENT_B)
    async with httpx.AsyncClient(base_url=API, headers={"Authorization": f"Bearer {token_a}"}) as ca:
        doctors = (await ca.get("/doctors")).json()
        doctor_id = doctors[0]["id"]
        date = next_weekday(7)
        slots = (await ca.get(f"/doctors/{doctor_id}/availability", params={"date": date})).json()
        if not slots:
            pytest.skip("no free slots")
        # pick a slot that isn't already booked
        slot = slots[-1]
        hold = await ca.post("/appointments/hold", json={"doctor_id": doctor_id, **slot})
        if hold.status_code != 200:
            pytest.skip("hold conflict")
        confirm = await ca.post(
            "/appointments/confirm",
            json={
                "hold_id": hold.json()["id"],
                "chief_complaint": "flu",
                "symptoms": "fever",
                "symptom_duration": "1 day",
                "severity": "Mild",
                "additional_notes": "",
            },
        )
        assert confirm.status_code == 200
        appt_id = confirm.json()["id"]

    async with httpx.AsyncClient(base_url=API, headers={"Authorization": f"Bearer {token_b}"}) as cb:
        # B joins waitlist
        wl = await cb.post("/waitlist", json={"doctor_id": doctor_id, **slot})
        assert wl.status_code == 200, wl.text
        wl_id = wl.json()["id"]
        # Duplicate blocked
        dup = await cb.post("/waitlist", json={"doctor_id": doctor_id, **slot})
        assert dup.status_code == 409

    # A cancels — triggers promotion
    async with httpx.AsyncClient(base_url=API, headers={"Authorization": f"Bearer {token_a}"}) as ca:
        await ca.patch(f"/appointments/{appt_id}/cancel")

    await asyncio.sleep(1.5)

    async with httpx.AsyncClient(base_url=API, headers={"Authorization": f"Bearer {token_b}"}) as cb:
        mine = (await cb.get("/waitlist/mine")).json()
        target = next((x for x in mine if x["id"] == wl_id), None)
        assert target and target["status"] == "NOTIFIED", target
        # Claim it
        claim = await cb.post(
            f"/waitlist/{wl_id}/claim",
            json={
                "chief_complaint": "flu",
                "symptoms": "fever",
                "symptom_duration": "1 day",
                "severity": "Mild",
                "additional_notes": "",
            },
        )
        assert claim.status_code == 200, claim.text
        assert claim.json()["status"] == "CONFIRMED"
        # Waitlist entry now BOOKED
        mine2 = (await cb.get("/waitlist/mine")).json()
        assert next(x for x in mine2 if x["id"] == wl_id)["status"] == "BOOKED"
