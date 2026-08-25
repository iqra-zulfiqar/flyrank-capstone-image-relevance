"""
Runs vision classification over a batch of images as a background job.
Designed to be invoked via FastAPI BackgroundTasks (see api/jobs.py) so
it never blocks the HTTP request — slow, bulk AI work runs off the
request path, with progress and cost visible via GET /jobs/{id}.
"""
import time
import uuid
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.config import settings
from app.db.database import SessionLocal
from app.db.models import Image, ImageMetadata as ImageMetadataModel, BatchJob
from app.services.vision import classify_image


def run_vision_batch_job(job_id: str) -> None:
    """
    Entry point run in the background. Opens its own DB session (the
    request's session is long gone by the time this executes).
    """
    db: Session = SessionLocal()
    try:
        job = db.query(BatchJob).filter(BatchJob.id == job_id).first()
        if job is None:
            return

        job.status = "running"
        db.commit()

        # Only classify images that don't already have metadata —
        # makes the job safely re-runnable (idempotent) if it's kicked
        # off again after a partial failure.
        already_done_ids = {
            row[0] for row in db.query(ImageMetadataModel.image_id).all()
        }
        images = db.query(Image).all()
        pending = [img for img in images if img.id not in already_done_ids]

        total_cost = 0.0
        total_retries = 0
        errors: list[str] = []

        for image in pending:
            result = classify_image(str(image.id), image.url_or_path)
            total_cost += result.cost_usd
            total_retries += max(0, result.attempts - 1)

            if result.metadata is not None:
                row = ImageMetadataModel(
                    image_id=image.id,
                    subject=result.metadata.subject,
                    category=result.metadata.category,
                    attributes=result.metadata.attributes,
                    caption=result.metadata.caption,
                    confidence=result.metadata.confidence,
                    is_flagged=result.is_flagged,
                    flag_reason=result.flag_reason,
                    model_used=result.model_used,
                    cost_usd=result.cost_usd,
                    raw_response=result.raw_response,
                )
                db.add(row)
                job.completed += 1
            else:
                # Validation failed even after retries — still record a
                # flagged row so the image shows up for human review
                # rather than silently vanishing.
                row = ImageMetadataModel(
                    image_id=image.id,
                    subject="UNKNOWN",
                    category="other",
                    attributes=[],
                    caption="Classification failed — needs manual review",
                    confidence=0.0,
                    is_flagged=True,
                    flag_reason=result.flag_reason,
                    model_used=result.model_used,
                    cost_usd=result.cost_usd,
                    raw_response=result.raw_response,
                )
                db.add(row)
                job.failed += 1
                errors.append(f"{image.filename}: {result.flag_reason}")

            job.total_cost_usd = float(job.total_cost_usd or 0) + result.cost_usd
            db.commit()  # commit per-item so progress is visible mid-run

            # Respect free-tier requests-per-minute limits — without this,
            # a 50-image batch fires all calls back-to-back and gets 429'd.
            time.sleep(settings.RATE_LIMIT_DELAY_SECONDS)

        job.retries = total_retries
        job.status = "done"
        job.error_log = "\n".join(errors) if errors else None
        from datetime import datetime, timezone
        job.finished_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as e:
        job = db.query(BatchJob).filter(BatchJob.id == job_id).first()
        if job:
            job.status = "failed"
            job.error_log = (job.error_log or "") + f"\nJob-level failure: {e}"
            db.commit()
        raise
    finally:
        db.close()


def create_batch_job(db: Session, job_type: str, total_items: int) -> BatchJob:
    job = BatchJob(
        id=uuid.uuid4(),
        job_type=job_type,
        status="pending",
        total_items=total_items,
        completed=0,
        failed=0,
        retries=0,
        total_cost_usd=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job