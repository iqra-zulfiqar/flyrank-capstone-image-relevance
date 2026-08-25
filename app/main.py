from fastapi import FastAPI

from app.db.database import Base, engine
from app.api import images, jobs, costs

# Dev convenience: create tables if they don't exist. In a real setup
# this is superseded by Alembic migrations (see db_init/ for the raw
# SQL equivalent used by capstone.yaml's seed step).
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="AI Image Understanding & Content Matching Engine",
    description="Phase 2: vision classification pipeline (structured output, batch jobs, cost tracking).",
    version="0.2.0",
)

app.include_router(images.router)
app.include_router(jobs.router)
app.include_router(costs.router)


@app.get("/")
def root():
    return {"status": "ok", "phase": "2 - vision pipeline"}


@app.get("/health")
def health():
    return {"status": "healthy"}