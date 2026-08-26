from fastapi import FastAPI

from app.db.database import Base, engine
from app.api import images, jobs, costs, posts, suggestions

# Dev convenience: create tables if they don't exist. In a real setup
# this is superseded by Alembic migrations (see db_init/ for the raw
# SQL equivalent used by capstone.yaml's seed step).
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="AI Image Understanding & Content Matching Engine",
    description="Phase 3: semantic matching engine + mismatch guard.",
    version="0.3.0",
)

app.include_router(images.router)
app.include_router(jobs.router)
app.include_router(costs.router)
app.include_router(posts.router)
app.include_router(suggestions.router)


@app.get("/")
def root():
    return {"status": "ok", "phase": "3 - matching engine + mismatch guard"}


@app.get("/health")
def health():
    return {"status": "healthy"}