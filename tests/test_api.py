"""Unit tests for FastAPI endpoints."""

import os
import sys

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from api.deps import get_session
from db.database import Base
from db.entities import CallRecord, CallResponse  # noqa: F401
from main import app

API = "/api/v1"


@pytest_asyncio.fixture
async def test_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_sess = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_session():
        async with async_sess() as s:
            yield s

    app.dependency_overrides[get_session] = override_get_session
    yield
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(test_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── POST /api/v1/calls ──


@pytest.mark.asyncio
async def test_create_call(client):
    resp = await client.post(
        f"{API}/calls",
        json={
            "patient_name": "Sarah Johnson",
            "medication": "Semaglutide",
            "dosage": "1.0mg weekly injection",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "call_id" in data
    assert "room_name" in data
    assert data["room_name"].startswith("call-")
    assert "token" in data
    assert len(data["token"]) > 0


@pytest.mark.asyncio
async def test_create_call_missing_field(client):
    resp = await client.post(
        f"{API}/calls",
        json={"patient_name": "Sarah Johnson"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_call_has_request_id(client):
    resp = await client.post(
        f"{API}/calls",
        json={
            "patient_name": "Sarah",
            "medication": "Semaglutide",
            "dosage": "1.0mg",
        },
    )
    assert "X-Request-ID" in resp.headers


@pytest.mark.asyncio
async def test_create_call_echoes_request_id(client):
    resp = await client.post(
        f"{API}/calls",
        json={
            "patient_name": "Sarah",
            "medication": "Semaglutide",
            "dosage": "1.0mg",
        },
        headers={"X-Request-ID": "my-custom-id"},
    )
    assert resp.headers["X-Request-ID"] == "my-custom-id"


# ── GET /api/v1/calls/{call_id} ──


@pytest.mark.asyncio
async def test_get_call(client):
    create_resp = await client.post(
        f"{API}/calls",
        json={
            "patient_name": "Sarah Johnson",
            "medication": "Semaglutide",
            "dosage": "1.0mg",
        },
    )
    call_id = create_resp.json()["call_id"]

    resp = await client.get(f"{API}/calls/{call_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["call_id"] == call_id
    assert data["patient_name"] == "Sarah Johnson"
    assert data["outcome"] is None
    assert len(data["responses"]) == 14
    assert all(r["answer"] == "" for r in data["responses"])


@pytest.mark.asyncio
async def test_get_call_not_found(client):
    resp = await client.get(f"{API}/calls/nonexistent-id")
    assert resp.status_code == 404


# ── GET /api/v1/calls ──


@pytest.mark.asyncio
async def test_list_calls_empty(client):
    resp = await client.get(f"{API}/calls")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_calls_multiple(client):
    await client.post(
        f"{API}/calls",
        json={
            "patient_name": "Alice",
            "medication": "Med A",
            "dosage": "1mg",
        },
    )
    await client.post(
        f"{API}/calls",
        json={
            "patient_name": "Bob",
            "medication": "Med B",
            "dosage": "2mg",
        },
    )

    resp = await client.get(f"{API}/calls")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    names = [c["patient_name"] for c in data]
    assert "Alice" in names
    assert "Bob" in names


# ── POST /api/v1/token ──


@pytest.mark.asyncio
async def test_generate_token(client):
    resp = await client.post(
        f"{API}/token",
        json={"room_name": "test-room"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert len(data["token"]) > 0


@pytest.mark.asyncio
async def test_generate_token_with_identity(client):
    resp = await client.post(
        f"{API}/token",
        json={"room_name": "test-room", "identity": "user-123"},
    )
    assert resp.status_code == 200
    assert "token" in resp.json()


@pytest.mark.asyncio
async def test_generate_token_missing_room(client):
    resp = await client.post(f"{API}/token", json={})
    assert resp.status_code == 422


# ── GET /health ──


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
