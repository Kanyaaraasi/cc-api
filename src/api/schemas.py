from datetime import datetime

from pydantic import BaseModel


class StartCallRequest(BaseModel):
    patient_name: str
    medication: str
    dosage: str


class StartCallResponse(BaseModel):
    call_id: str
    room_name: str
    token: str


class TokenRequest(BaseModel):
    room_name: str
    identity: str | None = None


class TokenResponse(BaseModel):
    token: str


class ResponseItem(BaseModel):
    question: str
    answer: str


class CallSummary(BaseModel):
    call_id: str
    room_name: str
    patient_name: str
    medication: str
    dosage: str
    outcome: str | None
    responses: list[ResponseItem]
    created_at: datetime
    completed_at: datetime | None
