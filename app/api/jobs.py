from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Image, BatchJob
from app.jobs.batch_runner import create_batch_job, run_vision_batch_job
from app.jobs.embed_runner import run_embed_batch_job, count_pending_embeddings
from app.schemas.image_metadata import BatchJobOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _to_job_out(job: BatchJob) -> BatchJobOut:
    """
    Explicit conversion, not response_model auto-validation:
    job.id is a UUID object and job.total_cost_usd is a Decimal —
    neither is auto-coerced to str/float by Pydantic, which was
    causing a 500 (ResponseValidationError) on every /jobs endpoint.
    """
    return BatchJobOut(
        id=str(job.id),
        job_type=job.job_type,
        status=job.status,
        total_items=job.total_items,
        completed=job.completed,
        failed=job.failed,
        retries=job.retries,
        total_cost_usd=float(job.total_cost_usd or 0),
    )


@router.post("/classify", response_model=BatchJobOut)
def trigger_classification_job(
    background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    """
    Kicks off vision classification over every registered image as a
    background job. Returns immediately with a job_id you can poll —
    the request is never blocked on slow, bulk vision calls.
    """
    total_images = db.query(Image).count()
    if total_images == 0:
        raise HTTPException(
            status_code=400,
            detail="No images registered. Call POST /images/register-from-manifest first.",
        )

    job = create_batch_job(db, job_type="vision_classify", total_items=total_images)
    background_tasks.add_task(run_vision_batch_job, str(job.id))
    return _to_job_out(job)


@router.post("/embed", response_model=BatchJobOut)
def trigger_embed_job(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Embeds every unflagged image caption and every post that doesn't
    have a vector yet. Run this after vision classification (Phase 2)
    and after creating posts, before requesting ranked matches.
    """
    total_pending = count_pending_embeddings(db)
    if total_pending == 0:
        raise HTTPException(
            status_code=400,
            detail="Nothing to embed. Make sure images are classified "
                   "(POST /jobs/classify) and posts exist (POST /posts).",
        )

    job = create_batch_job(db, job_type="embed", total_items=total_pending)
    background_tasks.add_task(run_embed_batch_job, str(job.id))
    return _to_job_out(job)


@router.get("/{job_id}", response_model=BatchJobOut)
def get_job_status(job_id: str, db: Session = Depends(get_db)):
    job = db.query(BatchJob).filter(BatchJob.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_job_out(job)


@router.get("", response_model=list[BatchJobOut])
def list_jobs(db: Session = Depends(get_db)):
    jobs = db.query(BatchJob).order_by(BatchJob.created_at.desc()).all()
    return [_to_job_out(j) for j in jobs]