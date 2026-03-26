import json
import re
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Query
from pydantic import BaseModel

router = APIRouter(tags=["patients"])

DATA_PATH = Path(__file__).parent.parent.parent.parent / "data" / "json"

REFILL_PATTERN = re.compile(r"getting your (.+?),\s*(.+?)\s*refill", re.IGNORECASE)


class PatientInfo(BaseModel):
    call_id: str
    patient_name: str
    medication: str
    dosage: str
    outcome: str
    patient_state: str


def _extract_medication(transcript: list[dict]) -> tuple[str, str]:
    """Extract medication and dosage from the agent's refill question."""
    for turn in transcript[:4]:
        if turn.get("role") != "agent":
            continue
        m = REFILL_PATTERN.search(turn["message"])
        if m:
            med = m.group(1).strip().rstrip(",")
            dose = m.group(2).strip().rstrip(",")
            return med, dose
    return "Unknown", "Unknown"


@lru_cache(maxsize=1)
def _load_patients() -> list[PatientInfo]:
    patients = []
    for split in ["hackathon_train.json", "hackathon_val.json"]:
        path = DATA_PATH / split
        if not path.exists():
            continue
        with open(path) as f:
            data = json.load(f)
        for call in data["calls"]:
            transcript = call.get("transcript", [])
            medication, dosage = _extract_medication(transcript)
            patients.append(
                PatientInfo(
                    call_id=call["call_id"],
                    patient_name=call["patient_name_anon"],
                    medication=medication,
                    dosage=dosage,
                    outcome=call["outcome"],
                    patient_state=call.get("patient_state", ""),
                )
            )
    return patients


@router.get("/patients", response_model=list[PatientInfo])
async def list_patients(
    outcome: str | None = Query(None, description="Filter by outcome"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    patients = _load_patients()
    if outcome:
        patients = [p for p in patients if p.outcome == outcome]
    return patients[offset : offset + limit]


@router.get("/patients/{call_id}", response_model=PatientInfo)
async def get_patient(call_id: str):
    patients = _load_patients()
    for p in patients:
        if p.call_id == call_id:
            return p
    from fastapi import HTTPException

    raise HTTPException(status_code=404, detail="Patient not found")
