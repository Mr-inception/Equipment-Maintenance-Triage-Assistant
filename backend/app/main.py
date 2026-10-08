import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect

from . import llm
from .config import settings
from .database import engine, init_db
from .logging_setup import setup_logging
from .retrieval import RetrievalError, get_knowledge_base
from .routers import kb, reports, workflow

setup_logging()
logger = logging.getLogger("triage")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    logger.info("Database initialised: %s", settings.database_url)
    if settings.seed_demo_on_start:
        from .demo import seed_demo_data

        logger.info("Demo seed: %d report(s) created", len(seed_demo_data()))
    try:
        get_knowledge_base()
    except RetrievalError as exc:
        logger.error("Knowledge base unavailable at startup: %s", exc)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(kb.router)
app.include_router(reports.router)
app.include_router(workflow.router)


@app.get("/api/health")
def health():
    try:
        kb_types = get_knowledge_base().equipment_types()
        kb_status = "ok"
    except RetrievalError:
        kb_types, kb_status = [], "unavailable"
    return {
        "status": "ok",
        "app": settings.app_name,
        "llm_configured": llm.is_configured(),
        "tables": sorted(inspect(engine).get_table_names()),
        "knowledge_base": {"status": kb_status, "equipment_types": kb_types},
    }
