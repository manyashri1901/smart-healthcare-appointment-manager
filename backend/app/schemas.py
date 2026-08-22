"""Pydantic request/response schemas."""
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field


class Register(BaseModel):
    name: str = Field(min_length=2)
    email: EmailStr
    password: str = Field(min_length=6)


class Login(BaseModel):
    email: EmailStr
    password: str


class HoldRequest(BaseModel):
    doctor_id: str
    start: datetime
    end: datetime


class SymptomForm(BaseModel):
    chief_complaint: str
    symptoms: str
    symptom_duration: str
    severity: str
    additional_notes: str = ""


class ConfirmRequest(SymptomForm):
    hold_id: str


class Medication(BaseModel):
    medicine_name: str
    dosage: str
    frequency: str
    duration: str
    instructions: str = ""


class ClinicalRequest(BaseModel):
    clinical_notes: str
    diagnosis: str
    medications: List[Medication] = []
    follow_up_instructions: str = ""
    follow_up_date: Optional[str] = None


class DoctorCreate(BaseModel):
    name: str
    email: EmailStr
    specialization: str
    qualification: str
    experience: str
    phone: str = ""
    work_start: str = "09:00"
    work_end: str = "17:00"
    slot_duration: int = 30


class DoctorUpdate(BaseModel):
    specialization: Optional[str] = None
    qualification: Optional[str] = None
    experience: Optional[str] = None
    phone: Optional[str] = None
    work_start: Optional[str] = None
    work_end: Optional[str] = None
    slot_duration: Optional[int] = None
    status: Optional[str] = None


class RescheduleRequest(BaseModel):
    start: datetime
    end: datetime


class LeaveRequest(BaseModel):
    date: str
