import asyncio
import json
from collections import deque
from datetime import datetime, timezone

from fastapi import APIRouter, Query
from loguru import logger
from sse_starlette.sse import EventSourceResponse

router = APIRouter(tags=["logs"])

# In-memory log buffer for recent logs + broadcast to SSE clients
LOG_BUFFER: deque[dict] = deque(maxlen=500)
SSE_SUBSCRIBERS: list[asyncio.Queue] = []


def _log_to_dict(message) -> dict:
    record = message.record
    return {
        "timestamp": record["time"].isoformat(),
        "level": record["level"].name,
        "module": record["module"],
        "function": record["function"],
        "message": record["message"],
        "extra": {k: str(v) for k, v in record["extra"].items()},
    }


def _loguru_sink(message):
    """Loguru sink that buffers logs and broadcasts to SSE subscribers."""
    log_entry = _log_to_dict(message)
    LOG_BUFFER.append(log_entry)

    for queue in SSE_SUBSCRIBERS:
        try:
            queue.put_nowait(log_entry)
        except asyncio.QueueFull:
            pass


def setup_log_streaming():
    """Call once at startup to add the SSE sink to loguru."""
    logger.add(
        _loguru_sink,
        format="{message}",
        level="DEBUG",
        serialize=False,
    )


@router.get("/logs/stream")
async def stream_logs(
    level: str = Query("INFO", description="Minimum log level"),
):
    """SSE endpoint — streams logs in real-time."""
    valid_levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
    min_level = valid_levels.get(level.upper(), 20)

    queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    SSE_SUBSCRIBERS.append(queue)

    async def event_generator():
        try:
            while True:
                log_entry = await queue.get()
                entry_level = valid_levels.get(log_entry["level"], 20)
                if entry_level >= min_level:
                    yield {
                        "event": "log",
                        "data": json.dumps(log_entry),
                    }
        except asyncio.CancelledError:
            pass
        finally:
            SSE_SUBSCRIBERS.remove(queue)

    return EventSourceResponse(event_generator())


@router.get("/logs/recent")
async def recent_logs(
    level: str = Query("INFO", description="Minimum log level"),
    limit: int = Query(100, ge=1, le=500),
):
    """Return recent buffered logs."""
    valid_levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}
    min_level = valid_levels.get(level.upper(), 20)

    filtered = [entry for entry in LOG_BUFFER if valid_levels.get(entry["level"], 20) >= min_level]
    return filtered[-limit:]


@router.get("/logs/system")
async def system_info():
    """Return current system/agent configuration."""
    return {
        "agent": {
            "name": "carecaller",
            "persona": "Jessica from TrimRX",
        },
        "llm": {
            "provider": "groq",
            "model": "meta-llama/llama-4-scout-17b-16e-instruct",
            "speed": "750 tok/s",
        },
        "stt": {
            "provider": "deepgram",
            "model": "nova-3",
        },
        "tts": {
            "provider": "deepgram",
            "model": "aura",
        },
        "vad": {
            "provider": "silero",
        },
        "transport": {
            "provider": "livekit",
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
