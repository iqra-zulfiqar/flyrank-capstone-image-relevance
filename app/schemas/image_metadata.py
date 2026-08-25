from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator


class ImageMetadata(BaseModel):
    """
    The shape every Gemini vision response must conform to.
    If a response doesn't validate against this, it is NEVER trusted —
    it gets retried, then flagged. It is never silently accepted.
    """
    subject: str = Field(..., min_length=1, max_length=100)
    category: Literal["animal", "landscape", "object", "person", "food", "other"]
    attributes: list[str] = Field(default_factory=list, max_length=10)
    caption: str = Field(..., min_length=5, max_length=300)
    confidence: float = Field(..., ge=0.0, le=1.0)

    @field_validator("attributes")
    @classmethod
    def clean_attributes(cls, v: list[str]) -> list[str]:
        return [a.strip() for a in v if a and a.strip()]

    @field_validator("subject", "caption")
    @classmethod
    def strip_text(cls, v: str) -> str:
        return v.strip()


class ClassificationResult(BaseModel):
    """
    What the vision service returns for a single image, after validation
    (successful or not) and cost accounting.
    """
    model_config = {"protected_namespaces": ()}

    image_id: str
    metadata: Optional[ImageMetadata] = None  # None if validation failed after retries
    is_flagged: bool
    flag_reason: Optional[str] = None
    raw_response: str
    cost_usd: float
    model_used: str
    attempts: int


class ImageCreate(BaseModel):
    filename: str
    url_or_path: str


class ImageOut(BaseModel):
    id: str
    filename: str
    url_or_path: str
    subject: Optional[str] = None
    category: Optional[str] = None
    attributes: Optional[list[str]] = None
    caption: Optional[str] = None
    confidence: Optional[float] = None
    is_flagged: Optional[bool] = None
    flag_reason: Optional[str] = None

    class Config:
        from_attributes = True


class BatchJobOut(BaseModel):
    id: str
    job_type: str
    status: str
    total_items: int
    completed: int
    failed: int
    retries: int
    total_cost_usd: float

    class Config:
        from_attributes = True