"""
The mismatch guard: the production-critical safety layer. Decides
"is this recommendation actually good enough?" by combining tag
validation, semantic similarity thresholds, and confidence scores —
and REJECTS with a human-readable explanation when it isn't, rather
than always returning the best available candidate.

This is deliberately conservative: a wrong image recommendation is
worse than no recommendation (see DESIGN.md §3).
"""
from typing import Optional

from app.config import settings

# Maps each known subject to every surface form worth matching as a
# substring. Needed because plain substring matching on the base word
# misses irregular plurals — "wolf" is NOT a substring of "wolves"
# (w-o-l-v-e-s has no "f"), so a post that only ever says "wolves"
# would silently skip the category check without this. Caught by
# tests/test_guard.py::test_finds_wolf during Phase 4 test-writing.
SUBJECT_VARIANTS = {
    "fox": ["fox", "foxes"],
    "wolf": ["wolf", "wolves"],
    "dog": ["dog", "dogs"],
    "bear": ["bear", "bears"],
    "deer": ["deer"],  # same singular/plural
}


def extract_known_subject(text: str) -> Optional[str]:
    """
    Looks for one of the corpus's known animal subjects (fox, wolf, dog,
    bear, deer) — including common plural forms — as a substring in the
    given text. Used to figure out what a blog post is actually about,
    and separately what an image's detected subject/attributes actually
    contain, so the two can be compared.

    Returns None if no known subject is mentioned — in that case the
    guard skips the subject-match check entirely rather than rejecting
    everything (a post that doesn't mention any of these five categories
    isn't something the guard can reason about at this scope).
    """
    text_lower = text.lower()
    for subject in settings.GUARD_KNOWN_SUBJECTS:
        subject = subject.strip().lower()
        variants = SUBJECT_VARIANTS.get(subject, [subject])
        if any(variant in text_lower for variant in variants):
            return subject
    return None


def evaluate_guard(
    post_title: str,
    post_body: str,
    image_subject: str,
    image_attributes: list[str],
    image_confidence: float,
    image_is_flagged: bool,
    similarity: float,
) -> tuple[bool, Optional[str]]:
    """
    Runs the guard checks in order, first failure wins:
      1. Confidence floor — never recommend a low-confidence/flagged image
      2. Subject/category match — the specific thing must match, not
         just "same general vibe" (this is the fox-vs-wolf trap). Checked
         before similarity so a category mismatch is reported as exactly
         that, rather than being masked by a low similarity score that
         would have failed anyway.
      3. Similarity floor — the embeddings must actually be close

    Returns (passed: bool, reason: Optional[str]). reason is always a
    human-readable explanation when passed=False; None when passed=True.
    """
    if image_is_flagged or image_confidence < settings.LOW_CONFIDENCE_THRESHOLD:
        return False, (
            f"Image classification is low-confidence ({image_confidence:.2f}) "
            f"or flagged — cannot recommend an uncertain classification."
        )

    post_text = f"{post_title} {post_body}"
    expected_subject = extract_known_subject(post_text)

    if expected_subject is not None:
        image_text = f"{image_subject} {' '.join(image_attributes)}"
        detected_subject = extract_known_subject(image_text)

        if detected_subject != expected_subject:
            return False, (
                f"Category mismatch: expected '{expected_subject}', "
                f"detected '{detected_subject or image_subject}'"
            )

    if similarity < settings.SIMILARITY_THRESHOLD:
        return False, (
            f"Similarity {similarity:.2f} below threshold "
            f"{settings.SIMILARITY_THRESHOLD:.2f} — image and post content "
            f"aren't semantically close enough."
        )

    return True, None