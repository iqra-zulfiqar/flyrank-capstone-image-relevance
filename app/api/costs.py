from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.database import get_db
from app.db.models import ImageMetadata as ImageMetadataModel, BatchJob
from app.services.vision import list_available_models

router = APIRouter(prefix="/costs", tags=["costs"])


@router.get("/debug/models")
def debug_list_models():
    """
    Diagnostic only — shows which Gemini models your API key can actually
    call. Useful when generateContent 404s and it's unclear whether it's
    a bad model name or a key/quota/region issue.
    """
    return list_available_models()


@router.get("")
def cost_summary(db: Session = Depends(get_db)):
    """
    Per-call cost is stored on every image_metadata row (and rolled up
    per batch job) so nothing is untracked, even at $0 free-tier cost.
    """
    total_vision_cost = db.query(func.coalesce(func.sum(ImageMetadataModel.cost_usd), 0)).scalar()
    call_count = db.query(func.count(ImageMetadataModel.image_id)).scalar()

    jobs = db.query(BatchJob).order_by(BatchJob.created_at.desc()).all()
    jobs_breakdown = [
        {
            "job_id": str(j.id),
            "job_type": j.job_type,
            "status": j.status,
            "items": j.total_items,
            "completed": j.completed,
            "failed": j.failed,
            "retries": j.retries,
            "cost_usd": float(j.total_cost_usd or 0),
        }
        for j in jobs
    ]

    return {
        "total_vision_calls": call_count,
        "total_vision_cost_usd": float(total_vision_cost),
        "jobs": jobs_breakdown,
    }