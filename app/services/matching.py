"""
Matching service: ranks candidate images by embedding similarity to a
post. Pure ranking — the mismatch guard (guard.py) decides afterward
whether the top-ranked candidate is actually good enough to suggest.
"""
from dataclasses import dataclass

from app.services.embeddings import cosine_similarity


@dataclass
class RankedCandidate:
    image_id: str
    filename: str
    subject: str
    attributes: list[str]
    confidence: float
    is_flagged: bool
    similarity: float


def rank_candidates(
    post_embedding: list[float],
    image_rows: list[dict],
) -> list[RankedCandidate]:
    """
    image_rows: list of dicts with keys:
      image_id, filename, subject, attributes, confidence, is_flagged, embedding

    Returns candidates sorted by similarity, descending.
    """
    candidates = []
    for row in image_rows:
        similarity = cosine_similarity(post_embedding, row["embedding"])
        candidates.append(
            RankedCandidate(
                image_id=row["image_id"],
                filename=row["filename"],
                subject=row["subject"],
                attributes=row["attributes"] or [],
                confidence=row["confidence"],
                is_flagged=row["is_flagged"],
                similarity=similarity,
            )
        )

    candidates.sort(key=lambda c: c.similarity, reverse=True)
    return candidates