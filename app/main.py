import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import router
from app.config import settings
from app.db import create_tables
from app.jobs import resume_unfinished_jobs

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    resume_unfinished_jobs()
    yield


app = FastAPI(
    title="Bulk Certificate Generator",
    version="1.0.0",
    description="Submit a list of recipients, generate PDF certificates in the background, "
    "track progress and download the results.",
    lifespan=lifespan,
)
app.include_router(router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
