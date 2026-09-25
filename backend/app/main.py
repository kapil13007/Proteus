"""FastAPI entrypoint: `uvicorn app.main:app --reload --port 8000` from backend/."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from app.api.auth import router as auth_router
from app.api.runs import router as runs_router
from app.api.system import router as system_router
from app.config import DEV_SESSION_SECRET, settings
from app.database import create_tables
from app.warehouse import get_warehouse, reset_warehouse

log = logging.getLogger("mapflow")


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_tables()
    await run_in_threadpool(get_warehouse)  # opens (and on first start, seeds) the local warehouse
    if settings.session_secret == DEV_SESSION_SECRET:
        log.warning("SESSION_SECRET is the development default — set a random one in backend/.env")
    yield
    reset_warehouse()


app = FastAPI(title="Mapfl0w API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(system_router)
app.include_router(auth_router)
app.include_router(runs_router)
