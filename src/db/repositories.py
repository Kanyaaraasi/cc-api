from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agent.config import HEALTH_QUESTIONS
from db.entities import CallRecord, CallResponse


class CallRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_call(
        self,
        call_id: str,
        room_name: str,
        patient_name: str,
        medication: str,
        dosage: str,
    ) -> CallRecord:
        record = CallRecord(
            id=call_id,
            room_name=room_name,
            patient_name=patient_name,
            medication=medication,
            dosage=dosage,
        )
        self.session.add(record)

        for i, question in enumerate(HEALTH_QUESTIONS):
            response = CallResponse(
                call_id=call_id,
                question_index=i,
                question=question,
                answer="",
            )
            self.session.add(response)

        await self.session.commit()
        return record

    async def get_call(self, call_id: str) -> CallRecord | None:
        stmt = (
            select(CallRecord)
            .where(CallRecord.id == call_id)
            .options(selectinload(CallRecord.responses))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_response(self, call_id: str, question_index: int, answer: str) -> None:
        stmt = select(CallResponse).where(
            CallResponse.call_id == call_id,
            CallResponse.question_index == question_index,
        )
        result = await self.session.execute(stmt)
        response = result.scalar_one_or_none()
        if response:
            response.answer = answer
            await self.session.commit()

    async def set_outcome(self, call_id: str, outcome: str) -> None:
        stmt = select(CallRecord).where(CallRecord.id == call_id)
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        if record:
            record.outcome = outcome
            record.completed_at = datetime.now(timezone.utc)
            await self.session.commit()

    async def list_calls(self) -> list[CallRecord]:
        stmt = (
            select(CallRecord)
            .options(selectinload(CallRecord.responses))
            .order_by(CallRecord.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
