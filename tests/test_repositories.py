"""Unit tests for CallRepository — CRUD operations on call records and responses."""

import os
import sys

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent.config import HEALTH_QUESTIONS
from db.database import Base
from db.entities import CallRecord, CallResponse  # noqa: F401
from db.repositories import CallRepository


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_sess = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_sess() as s:
        yield s

    await engine.dispose()


@pytest_asyncio.fixture
async def repo(session):
    return CallRepository(session)


# ── create_call ──


@pytest.mark.asyncio
async def test_create_call(repo):
    record = await repo.create_call(
        call_id="test-123",
        room_name="call-test",
        patient_name="Sarah Johnson",
        medication="Semaglutide",
        dosage="1.0mg weekly injection",
    )
    assert record.id == "test-123"
    assert record.room_name == "call-test"
    assert record.patient_name == "Sarah Johnson"
    assert record.outcome is None
    assert record.completed_at is None


@pytest.mark.asyncio
async def test_create_call_creates_14_responses(repo):
    await repo.create_call(
        call_id="test-123",
        room_name="call-test",
        patient_name="Sarah Johnson",
        medication="Semaglutide",
        dosage="1.0mg",
    )
    record = await repo.get_call("test-123")
    assert len(record.responses) == 14
    for i, resp in enumerate(record.responses):
        assert resp.question_index == i
        assert resp.question == HEALTH_QUESTIONS[i]
        assert resp.answer == ""


# ── get_call ──


@pytest.mark.asyncio
async def test_get_call_not_found(repo):
    result = await repo.get_call("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_get_call_returns_record(repo):
    await repo.create_call(
        call_id="test-456",
        room_name="call-test",
        patient_name="John Doe",
        medication="Tirzepatide",
        dosage="2.5mg",
    )
    record = await repo.get_call("test-456")
    assert record is not None
    assert record.patient_name == "John Doe"
    assert record.medication == "Tirzepatide"


# ── update_response ──


@pytest.mark.asyncio
async def test_update_response(repo):
    await repo.create_call(
        call_id="test-789",
        room_name="call-test",
        patient_name="Jane",
        medication="Semaglutide",
        dosage="1.0mg",
    )
    await repo.update_response("test-789", 0, "Feeling great")
    await repo.update_response("test-789", 1, "185 pounds")

    record = await repo.get_call("test-789")
    assert record.responses[0].answer == "Feeling great"
    assert record.responses[1].answer == "185 pounds"
    assert record.responses[2].answer == ""


@pytest.mark.asyncio
async def test_update_response_nonexistent_call(repo):
    # Should not raise, just silently do nothing
    await repo.update_response("nonexistent", 0, "test")


@pytest.mark.asyncio
async def test_update_response_overwrite(repo):
    await repo.create_call(
        call_id="test-overwrite",
        room_name="call-test",
        patient_name="Jane",
        medication="Semaglutide",
        dosage="1.0mg",
    )
    await repo.update_response("test-overwrite", 0, "First answer")
    await repo.update_response("test-overwrite", 0, "Corrected answer")

    record = await repo.get_call("test-overwrite")
    assert record.responses[0].answer == "Corrected answer"


# ── set_outcome ──


@pytest.mark.asyncio
async def test_set_outcome(repo):
    await repo.create_call(
        call_id="test-outcome",
        room_name="call-test",
        patient_name="Jane",
        medication="Semaglutide",
        dosage="1.0mg",
    )
    await repo.set_outcome("test-outcome", "completed")

    record = await repo.get_call("test-outcome")
    assert record.outcome == "completed"
    assert record.completed_at is not None


@pytest.mark.asyncio
async def test_set_outcome_nonexistent_call(repo):
    # Should not raise
    await repo.set_outcome("nonexistent", "completed")


# ── list_calls ──


@pytest.mark.asyncio
async def test_list_calls_empty(repo):
    calls = await repo.list_calls()
    assert calls == []


@pytest.mark.asyncio
async def test_list_calls_multiple(repo):
    await repo.create_call("id-1", "room-1", "Alice", "Med A", "1mg")
    await repo.create_call("id-2", "room-2", "Bob", "Med B", "2mg")

    calls = await repo.list_calls()
    assert len(calls) == 2
    # Most recent first
    names = [c.patient_name for c in calls]
    assert "Alice" in names
    assert "Bob" in names
