import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Text, Float, Boolean, Integer, Numeric,
    DateTime, ForeignKey, ARRAY
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.database import Base


def now_utc():
    return datetime.now(timezone.utc)


class Image(Base):
    __tablename__ = "images"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(Text, nullable=False)
    url_or_path = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now_utc)

    metadata_ = relationship("ImageMetadata", back_populates="image", uselist=False, cascade="all, delete-orphan")


class ImageMetadata(Base):
    __tablename__ = "image_metadata"

    image_id = Column(UUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), primary_key=True)
    subject = Column(Text, nullable=False)
    category = Column(Text, nullable=False, index=True)
    attributes = Column(ARRAY(Text), default=list)
    caption = Column(Text, nullable=False)
    confidence = Column(Float, nullable=False)
    is_flagged = Column(Boolean, nullable=False, default=False, index=True)
    flag_reason = Column(Text, nullable=True)
    model_used = Column(Text, nullable=False)
    cost_usd = Column(Numeric(10, 6), nullable=False, default=0)
    raw_response = Column(Text, nullable=True)
    processed_at = Column(DateTime(timezone=True), default=now_utc)

    image = relationship("Image", back_populates="metadata_")


class BatchJob(Base):
    __tablename__ = "batch_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_type = Column(Text, nullable=False)  # 'vision_classify' / 'embed_images' / 'embed_posts'
    status = Column(Text, nullable=False, default="pending")  # pending/running/done/failed
    total_items = Column(Integer, nullable=False)
    completed = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    retries = Column(Integer, nullable=False, default=0)
    total_cost_usd = Column(Numeric(10, 6), nullable=False, default=0)
    error_log = Column(Text, nullable=True)  # newline-separated per-item errors
    created_at = Column(DateTime(timezone=True), default=now_utc)
    finished_at = Column(DateTime(timezone=True), nullable=True)