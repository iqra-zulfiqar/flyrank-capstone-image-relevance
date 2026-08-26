from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Suggestion
from app.schemas.matching import SuggestionOut

router = APIRouter(prefix="/suggestions", tags=["suggestions"])


def _to_out(s: Suggestion) -> SuggestionOut:
    return SuggestionOut(
        id=str(s.id),
        post_id=str(s.post_id),
        image_id=str(s.image_id) if s.image_id else None,
        similarity=s.similarity,
        guard_passed=s.guard_passed,
        guard_reason=s.guard_reason,
        status=s.status,
    )


@router.get("/{suggestion_id}", response_model=SuggestionOut)
def get_suggestion(suggestion_id: str, db: Session = Depends(get_db)):
    """Inspect why an image was selected or refused for a post."""
    s = db.query(Suggestion).filter(Suggestion.id == suggestion_id).first()
    if s is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return _to_out(s)


@router.post("/{suggestion_id}/approve", response_model=SuggestionOut)
def approve_suggestion(suggestion_id: str, db: Session = Depends(get_db)):
    s = db.query(Suggestion).filter(Suggestion.id == suggestion_id).first()
    if s is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    if not s.guard_passed:
        raise HTTPException(
            status_code=400,
            detail="Cannot approve a suggestion the guard rejected. "
                   f"Guard reason: {s.guard_reason}",
        )
    s.status = "approved"
    s.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(s)
    return _to_out(s)


@router.post("/{suggestion_id}/reject", response_model=SuggestionOut)
def reject_suggestion(suggestion_id: str, db: Session = Depends(get_db)):
    s = db.query(Suggestion).filter(Suggestion.id == suggestion_id).first()
    if s is None:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    s.status = "rejected"
    s.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(s)
    return _to_out(s)