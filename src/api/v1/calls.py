import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from livekit import api
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_session
from api.schemas import (
    CallSummary,
    ResponseItem,
    StartCallRequest,
    StartCallResponse,
    TokenRequest,
    TokenResponse,
)
from db.repositories import CallRepository

router = APIRouter(tags=["calls"])


async def get_repo(session: AsyncSession = Depends(get_session)):
    return CallRepository(session)


def _record_to_summary(record) -> CallSummary:
    return CallSummary(
        call_id=record.id,
        room_name=record.room_name,
        patient_name=record.patient_name,
        medication=record.medication,
        dosage=record.dosage,
        outcome=record.outcome,
        responses=[ResponseItem(question=r.question, answer=r.answer) for r in record.responses],
        created_at=record.created_at,
        completed_at=record.completed_at,
    )


@router.post("/calls", response_model=StartCallResponse)
async def start_call(
    request: StartCallRequest,
    repo: CallRepository = Depends(get_repo),
):
    call_id = str(uuid.uuid4())
    room_name = f"call-{call_id}"

    await repo.create_call(
        call_id=call_id,
        room_name=room_name,
        patient_name=request.patient_name,
        medication=request.medication,
        dosage=request.dosage,
    )

    room_metadata = json.dumps(
        {
            "call_id": call_id,
            "patient_name": request.patient_name,
            "medication": request.medication,
            "dosage": request.dosage,
        }
    )

    # Create room with metadata, then dispatch agent explicitly
    lk_api = api.LiveKitAPI()
    await lk_api.room.create_room(
        api.CreateRoomRequest(
            name=room_name,
            metadata=room_metadata,
            max_participants=2,
        )
    )
    await lk_api.agent_dispatch.create_dispatch(
        api.CreateAgentDispatchRequest(
            room=room_name,
            agent_name="carecaller",
            metadata=room_metadata,
        )
    )
    await lk_api.aclose()

    # Generate token for user to join
    token = (
        api.AccessToken()
        .with_identity(f"user-{call_id}")
        .with_name(request.patient_name)
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room_name,
            )
        )
        .to_jwt()
    )

    logger.info(
        "Call created | call_id={call_id} room={room}",
        call_id=call_id,
        room=room_name,
    )

    return StartCallResponse(
        call_id=call_id,
        room_name=room_name,
        token=token,
    )


@router.get("/calls/{call_id}", response_model=CallSummary)
async def get_call(
    call_id: str,
    repo: CallRepository = Depends(get_repo),
):
    record = await repo.get_call(call_id)
    if not record:
        raise HTTPException(status_code=404, detail="Call not found")
    return _record_to_summary(record)


@router.get("/calls", response_model=list[CallSummary])
async def list_calls(
    repo: CallRepository = Depends(get_repo),
):
    records = await repo.list_calls()
    return [_record_to_summary(r) for r in records]


@router.post("/token", response_model=TokenResponse)
async def generate_token(request: TokenRequest):
    identity = request.identity or f"user-{uuid.uuid4().hex[:8]}"

    token = (
        api.AccessToken()
        .with_identity(identity)
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=request.room_name,
            )
        )
        .to_jwt()
    )

    return TokenResponse(token=token)
