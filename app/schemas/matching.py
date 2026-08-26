from typing import Optional
from pydantic import BaseModel, Field


class PostCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    body: str = Field(..., min_length=1)


class PostOut(BaseModel):
    id: str
    title: str
    body: str
    has_embedding: bool

    class Config:
        from_attributes = True


class CandidateOut(BaseModel):
    """One ranked candidate, with its guard verdict — shown for
    transparency even for candidates that aren't the final suggestion,
    so the review workflow can see *why* an image was or wasn't picked."""
    image_id: str
    filename: str
    subject: str
    similarity: float
    confidence: float
    is_flagged: bool
    guard_passed: bool
    guard_reason: Optional[str] = None


class MatchResultOut(BaseModel):
    post_id: str
    suggestion_id: str
    matched: bool  # True if a suggestion was made, False if "no confident match"
    suggested_image_id: Optional[str] = None
    similarity: Optional[float] = None
    reason: Optional[str] = None  # populated when matched=False
    candidates: list[CandidateOut] = Field(default_factory=list)


class SuggestionOut(BaseModel):
    id: str
    post_id: str
    image_id: Optional[str] = None
    similarity: Optional[float] = None
    guard_passed: bool
    guard_reason: Optional[str] = None
    status: str

    class Config:
        from_attributes = True