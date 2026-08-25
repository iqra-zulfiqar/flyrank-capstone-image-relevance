import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Image, ImageMetadata as ImageMetadataModel
from app.schemas.image_metadata import ImageOut

router = APIRouter(prefix="/images", tags=["images"])

MANIFEST_PATH = Path("data/images/manifest.json")


@router.post("/register-from-manifest")
def register_from_manifest(db: Session = Depends(get_db)):
    """
    Reads data/images/manifest.json (produced by seed_images.py in
    Phase 1) and registers any images not already in the DB.
    Idempotent: safe to call again after adding more images.
    """
    if not MANIFEST_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail=f"{MANIFEST_PATH} not found — run seed_images.py first (Phase 1).",
        )

    manifest = json.loads(MANIFEST_PATH.read_text())
    existing_paths = {row[0] for row in db.query(Image.url_or_path).all()}

    registered = 0
    for entry in manifest:
        if entry["path"] in existing_paths:
            continue
        img = Image(id=uuid.uuid4(), filename=entry["filename"], url_or_path=entry["path"])
        db.add(img)
        registered += 1

    db.commit()
    return {"registered": registered, "skipped_existing": len(manifest) - registered}


@router.get("", response_model=list[ImageOut])
def list_images(flagged_only: bool = False, db: Session = Depends(get_db)):
    query = (
        db.query(Image, ImageMetadataModel)
        .outerjoin(ImageMetadataModel, Image.id == ImageMetadataModel.image_id)
    )
    if flagged_only:
        query = query.filter(ImageMetadataModel.is_flagged.is_(True))

    results = []
    for image, meta in query.all():
        results.append(ImageOut(
            id=str(image.id),
            filename=image.filename,
            url_or_path=image.url_or_path,
            subject=meta.subject if meta else None,
            category=meta.category if meta else None,
            attributes=meta.attributes if meta else None,
            caption=meta.caption if meta else None,
            confidence=meta.confidence if meta else None,
            is_flagged=meta.is_flagged if meta else None,
            flag_reason=meta.flag_reason if meta else None,
        ))
    return results


@router.get("/{image_id}", response_model=ImageOut)
def get_image(image_id: str, db: Session = Depends(get_db)):
    image = db.query(Image).filter(Image.id == image_id).first()
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found")
    meta = db.query(ImageMetadataModel).filter(ImageMetadataModel.image_id == image_id).first()

    return ImageOut(
        id=str(image.id),
        filename=image.filename,
        url_or_path=image.url_or_path,
        subject=meta.subject if meta else None,
        category=meta.category if meta else None,
        attributes=meta.attributes if meta else None,
        caption=meta.caption if meta else None,
        confidence=meta.confidence if meta else None,
        is_flagged=meta.is_flagged if meta else None,
        flag_reason=meta.flag_reason if meta else None,
    )