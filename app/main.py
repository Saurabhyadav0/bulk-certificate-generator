import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.docs import API_DESCRIPTION, TAGS_METADATA
from app.api.jobs import router as jobs_router
from app.database import init_db
from app.services.processor import recover_unfinished_jobs, shutdown_executor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    recover_unfinished_jobs()
    yield
    shutdown_executor()


app = FastAPI(
    title="Bulk Certificate Generator",
    description=API_DESCRIPTION,
    openapi_tags=TAGS_METADATA,
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(jobs_router)


@app.get("/health", tags=["Health"])
def health() -> dict:
    return {"status": "ok"}
