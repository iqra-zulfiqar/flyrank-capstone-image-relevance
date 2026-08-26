"""
Batch-embeds every image caption that doesn't have a vector yet, and
every post that doesn't have a vector yet. Same idempotent pattern as
the vision batch job in Phase 2: safely re-runnable, progress tracked
via BatchJob.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models import Image, ImageMetadata, ImageVector, Post, PostVector, BatchJob
from app.services.embeddings import get_embedding
from app.jobs.batch_runner import create_batch_job


def run_embed_batch_job(job_id: str) -> None:
    db: Session = SessionLocal()
    try:
        job = db.query(BatchJob).filter(BatchJob.id == job_id).first()
        if job is None:
            return

        job.status = "running"
        db.commit()

        total_cost = 0.0
        errors: list[str] = []

        # --- Embed images lacking a vector (using their caption) ---
        already_embedded_image_ids = {row[0] for row in db.query(ImageVector.image_id).all()}
        images_with_metadata = (
            db.query(Image, ImageMetadata)
            .join(ImageMetadata, Image.id == ImageMetadata.image_id)
            .filter(ImageMetadata.is_flagged.is_(False))  # don't embed unreliable tags
            .all()
        )
        pending_images = [
            (img, meta) for img, meta in images_with_metadata
            if img.id not in already_embedded_image_ids
        ]

        for image, meta in pending_images:
            try:
                embedding, model_used, cost = get_embedding(meta.caption)
                total_cost += cost
                db.add(ImageVector(image_id=image.id, embedding=embedding, model_used=model_used))
                job.completed += 1
            except Exception as e:
                job.failed += 1
                errors.append(f"image {image.filename}: {e}")
            db.commit()

        # --- Embed posts lacking a vector ---
        already_embedded_post_ids = {row[0] for row in db.query(PostVector.post_id).all()}
        posts = db.query(Post).all()
        pending_posts = [p for p in posts if p.id not in already_embedded_post_ids]

        for post in pending_posts:
            try:
                text = f"{post.title}\n{post.body}"
                embedding, model_used, cost = get_embedding(text)
                total_cost += cost
                db.add(PostVector(post_id=post.id, embedding=embedding, model_used=model_used))
                job.completed += 1
            except Exception as e:
                job.failed += 1
                errors.append(f"post {post.title}: {e}")
            db.commit()

        job.total_cost_usd = float(job.total_cost_usd or 0) + total_cost
        job.status = "done"
        job.error_log = "\n".join(errors) if errors else None
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


def count_pending_embeddings(db: Session) -> int:
    """Used to set total_items on the BatchJob before starting."""
    already_embedded_image_ids = {row[0] for row in db.query(ImageVector.image_id).all()}
    image_count = (
        db.query(Image, ImageMetadata)
        .join(ImageMetadata, Image.id == ImageMetadata.image_id)
        .filter(ImageMetadata.is_flagged.is_(False))
        .count()
    )
    pending_images = image_count - len(
        [i for i in already_embedded_image_ids]
    )  # rough estimate, fine for progress display

    already_embedded_post_ids = {row[0] for row in db.query(PostVector.post_id).all()}
    post_count = db.query(Post).count()
    pending_posts = post_count - len(already_embedded_post_ids)

    return max(0, pending_images) + max(0, pending_posts)