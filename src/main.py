import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from loguru import logger
from starlette.responses import FileResponse

from api.middleware import RequestIDMiddleware
from api.v1.calls import router as calls_router
from api.v1.logs import router as logs_router
from api.v1.logs import setup_log_streaming
from api.v1.patients import router as patients_router
from db.database import init_db

load_dotenv(".env.local")

# Configure loguru with colorful output
logger.remove()
logger.add(
    sys.stderr,
    format=(
        "<green>{time:HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{module}</cyan>:<cyan>{function}</cyan> | "
        "<level>{message}</level>"
    ),
    level="DEBUG",
    colorize=True,
)

static_dir = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_log_streaming()
    await init_db()
    yield


app = FastAPI(title="CareCaller API", version="1.0.0", lifespan=lifespan)

app.add_middleware(RequestIDMiddleware)
app.include_router(calls_router, prefix="/api/v1")
app.include_router(patients_router, prefix="/api/v1")
app.include_router(logs_router, prefix="/api/v1")


@app.get("/")
async def dashboard():
    return FileResponse(static_dir / "index.html")


@app.get("/api/v1/config")
async def get_config():
    return {"livekit_url": os.getenv("LIVEKIT_URL", "")}


@app.get("/health")
async def health():
    return {"status": "ok"}


app.mount("/static", StaticFiles(directory=static_dir), name="static")
