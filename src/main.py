from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI

from api.middleware import RequestIDMiddleware
from api.v1.calls import router as calls_router
from api.v1.logs import router as logs_router
from api.v1.logs import setup_log_streaming
from api.v1.patients import router as patients_router
from db.database import init_db

load_dotenv(".env.local")


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


@app.get("/health")
async def health():
    return {"status": "ok"}
