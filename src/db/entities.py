from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base


class CallRecord(Base):
    __tablename__ = "call_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    room_name: Mapped[str] = mapped_column(String(100))
    patient_name: Mapped[str] = mapped_column(String(200))
    medication: Mapped[str] = mapped_column(String(200))
    dosage: Mapped[str] = mapped_column(String(100))
    outcome: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    responses: Mapped[list["CallResponse"]] = relationship(
        back_populates="call_record", order_by="CallResponse.question_index"
    )


class CallResponse(Base):
    __tablename__ = "call_responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[str] = mapped_column(String(36), ForeignKey("call_records.id"))
    question_index: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text, default="")

    call_record: Mapped["CallRecord"] = relationship(back_populates="responses")
