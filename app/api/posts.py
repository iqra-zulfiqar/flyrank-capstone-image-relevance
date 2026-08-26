import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Post, PostVector, Image, ImageMetadata, ImageVector, Suggestion
from app.schemas.matching import (
    PostCreate, PostOut, MatchResultOut, CandidateOut, SuggestionOut,
)
from app.services.embeddings import get_embedding
from app.services.matching import rank_candidates
from app.services.guard import evaluate_guard

router = APIRouter(prefix="/posts", tags=["posts"])


@router.post("", response_model=PostOut)
def create_post(payload: PostCreate, db: Session = Depends(get_db)):
    """
    Creates a post and immediately embeds it (a single embedding call,
    fast enough to do inline rather than as a background batch job —
    unlike the bulk image classification/embedding in Phase 2).
    """
    post = Post(id=uuid.uuid4(), title=payload.title, body=payload.body)
    db.add(post)
    db.commit()
    db.refresh(post)

    try:
        embedding, model_used, _cost = get_embedding(f"{post.title}\n{post.body}")
        db.add(PostVector(post_id=post.id, embedding=embedding, model_used=model_used))
        db.commit()
        has_embedding = True
    except Exception:
        # Embedding failed (e.g. Ollama not running) — post still exists,
        # just can't be matched yet. GET /posts/{id}/images will explain.
        has_embedding = False

    return PostOut(id=str(post.id), title=post.title, body=post.body, has_embedding=has_embedding)


@router.get("", response_model=list[PostOut])
def list_posts(db: Session = Depends(get_db)):
    posts = db.query(Post).all()
    embedded_ids = {row[0] for row in db.query(PostVector.post_id).all()}
    return [
        PostOut(id=str(p.id), title=p.title, body=p.body, has_embedding=p.id in embedded_ids)
        for p in posts
    ]


def _get_candidate_rows(db: Session) -> list[dict]:
    """All images that have both metadata and an embedding — the pool
    of things that can possibly be suggested."""
    rows = (
        db.query(Image, ImageMetadata, ImageVector)
        .join(ImageMetadata, Image.id == ImageMetadata.image_id)
        .join(ImageVector, Image.id == ImageVector.image_id)
        .all()
    )
    return [
        {
            "image_id": str(img.id),
            "filename": img.filename,
            "subject": meta.subject,
            "attributes": meta.attributes,
            "confidence": meta.confidence,
            "is_flagged": meta.is_flagged,
            "embedding": vec.embedding,
        }
        for img, meta, vec in rows
    ]


@router.get("/{post_id}/images", response_model=MatchResultOut)
def get_ranked_images(post_id: str, db: Session = Depends(get_db)):
    """
    The core matching endpoint. Ranks every image by similarity to this
    post, runs the mismatch guard on candidates top-down, and returns
    either a confident suggestion or a "no confident match" verdict with
    reasons. Records a Suggestion row either way so the review workflow
    has something to approve/reject/inspect.
    """
    post = db.query(Post).filter(Post.id == post_id).first()
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")

    post_vector = db.query(PostVector).filter(PostVector.post_id == post_id).first()
    if post_vector is None:
        raise HTTPException(
            status_code=400,
            detail="Post has no embedding yet. Try POST /posts again, or check Ollama is running.",
        )

    candidate_rows = _get_candidate_rows(db)
    if not candidate_rows:
        raise HTTPException(
            status_code=400,
            detail="No embedded images available. Run POST /jobs/embed first.",
        )

    ranked = rank_candidates(post_vector.embedding, candidate_rows)

    candidates_out = []
    chosen = None
    chosen_reason = None

    for candidate in ranked:
        passed, reason = evaluate_guard(
            post_title=post.title,
            post_body=post.body,
            image_subject=candidate.subject,
            image_attributes=candidate.attributes,
            image_confidence=candidate.confidence,
            image_is_flagged=candidate.is_flagged,
            similarity=candidate.similarity,
        )
        candidates_out.append(CandidateOut(
            image_id=candidate.image_id,
            filename=candidate.filename,
            subject=candidate.subject,
            similarity=round(candidate.similarity, 4),
            confidence=candidate.confidence,
            is_flagged=candidate.is_flagged,
            guard_passed=passed,
            guard_reason=reason,
        ))
        if passed and chosen is None:
            chosen = candidate
        if chosen is None and reason is not None and chosen_reason is None:
            chosen_reason = reason  # reason from the best (top-ranked) candidate

    if chosen is not None:
        suggestion = Suggestion(
            id=uuid.uuid4(),
            post_id=post.id,
            image_id=uuid.UUID(chosen.image_id),
            similarity=chosen.similarity,
            guard_passed=True,
            guard_reason=None,
            status="pending",
        )
        db.add(suggestion)
        db.commit()
        db.refresh(suggestion)

        return MatchResultOut(
            post_id=str(post.id),
            suggestion_id=str(suggestion.id),
            matched=True,
            suggested_image_id=chosen.image_id,
            similarity=round(chosen.similarity, 4),
            reason=None,
            candidates=candidates_out,
        )

    # No candidate passed the guard — "no confident match".
    top_reason = chosen_reason or "No candidate images available."
    suggestion = Suggestion(
        id=uuid.uuid4(),
        post_id=post.id,
        image_id=None,
        similarity=ranked[0].similarity if ranked else None,
        guard_passed=False,
        guard_reason=top_reason,
        status="pending",
    )
    db.add(suggestion)
    db.commit()
    db.refresh(suggestion)

    return MatchResultOut(
        post_id=str(post.id),
        suggestion_id=str(suggestion.id),
        matched=False,
        suggested_image_id=None,
        similarity=None,
        reason=top_reason,
        candidates=candidates_out,
    )


@router.post("/{post_id}/force-match/{image_id}", response_model=CandidateOut)
def force_match(post_id: str, image_id: str, db: Session = Depends(get_db)):
    """
    Demo/testing endpoint: forces a SPECIFIC image as a candidate for a
    post, regardless of ranking, and runs the guard against it directly.
    This is how you reproduce the brief's core demo moment — "force the
    wolf as a candidate for the fox post, watch the guard refuse it" —
    without depending on the wolf actually ranking high enough to be
    the top candidate naturally.
    """
    post = db.query(Post).filter(Post.id == post_id).first()
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")

    row = (
        db.query(Image, ImageMetadata, ImageVector)
        .join(ImageMetadata, Image.id == ImageMetadata.image_id)
        .join(ImageVector, Image.id == ImageVector.image_id)
        .filter(Image.id == image_id)
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Image not found, or missing metadata/embedding.",
        )
    img, meta, vec = row

    post_vector = db.query(PostVector).filter(PostVector.post_id == post_id).first()
    if post_vector is None:
        raise HTTPException(status_code=400, detail="Post has no embedding yet.")

    from app.services.embeddings import cosine_similarity
    similarity = cosine_similarity(post_vector.embedding, vec.embedding)

    passed, reason = evaluate_guard(
        post_title=post.title,
        post_body=post.body,
        image_subject=meta.subject,
        image_attributes=meta.attributes,
        image_confidence=meta.confidence,
        image_is_flagged=meta.is_flagged,
        similarity=similarity,
    )

    return CandidateOut(
        image_id=str(img.id),
        filename=img.filename,
        subject=meta.subject,
        similarity=round(similarity, 4),
        confidence=meta.confidence,
        is_flagged=meta.is_flagged,
        guard_passed=passed,
        guard_reason=reason,
    )