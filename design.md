# Design Doc — AI Image Understanding & Content Matching Engine

**Stack:** Python + FastAPI · Gemini Flash (free tier) · PostgreSQL (Docker) · Pydantic

---

## 1. Problem

Given a library of ~50 images and a set of blog posts, automatically:
1. Understand what each image actually depicts (vision model → structured tags).
2. Rank the most semantically relevant image(s) for each post.
3. **Refuse** a suggestion when no image is a confident enough match, with a
   human-readable reason — rather than always returning "best available."

The system optimizes for **trustworthiness over coverage**: a wrong image
recommendation is worse than no recommendation.

**Non-goal:** This is not an image search engine or a general-purpose asset
manager. No frontend, no user accounts/auth beyond a single API key, no
support for video/audio, no multi-model comparison (one vision model, one
embedding model only).

---

## 2. Image Metadata Schema (Pydantic)

Every vision-model response is validated against this schema before it's
trusted. Anything that fails validation is retried once, then flagged.

```python
from pydantic import BaseModel, Field, field_validator
from typing import Literal

class ImageMetadata(BaseModel):
    subject: str = Field(..., min_length=1, max_length=100)
    category: Literal["animal", "landscape", "object", "person", "food", "other"]
    attributes: list[str] = Field(default_factory=list, max_length=10)
    caption: str = Field(..., min_length=5, max_length=300)
    confidence: float = Field(..., ge=0.0, le=1.0)

    @field_validator("attributes")
    @classmethod
    def no_empty_attrs(cls, v):
        return [a.strip() for a in v if a.strip()]

class ClassificationResult(BaseModel):
    image_id: str
    metadata: ImageMetadata | None       # None if validation failed after retry
    is_flagged: bool                     # True if confidence < threshold or validation failed
    flag_reason: str | None = None
    raw_response: str                    # stored for debugging, never parsed downstream
    cost_usd: float
    model_used: str
```

Low-confidence threshold (starting point, tune with eval set in Phase 4):
`confidence < 0.6` → `is_flagged = True`.

---

## 3. Matching Strategy & Guard Rules (sketch)

**Embedding space:** one shared space for image captions and post text/title,
using Gemini's embedding model (`SEMANTIC_SIMILARITY` task type). Cosine
similarity is the ranking signal.

**Ranking pipeline per post:**
1. Embed the post (title + body excerpt).
2. Compute cosine similarity against all image caption embeddings.
3. Sort descending → candidate list.

**Mismatch guard (applied to the top candidate before it's ever shown):**

| Check | Rule |
|---|---|
| Category match | Post's inferred subject category must match image `category` (e.g. both "animal") |
| Subject overlap | Image `subject` / `attributes` must not directly contradict post's declared subject (fox ≠ wolf, even if visually similar) |
| Similarity floor | Cosine similarity must be ≥ threshold (tuned via eval set, starting guess: `0.75`) |
| Confidence floor | Underlying image classification `confidence` ≥ `0.6` (flagged images never auto-suggested) |

If **any** check fails → reject with a specific, human-readable reason
(e.g. `"Category mismatch: expected 'fox', detected 'wolf'"` or
`"Similarity 0.61 below threshold 0.75"`). If **all** candidates fail →
respond `"no confident match"` with the reasons for the top candidate.

Thresholds live in a config file/env vars, not hardcoded — they get tuned
against the labeled eval set in Phase 4, not guessed.

---

## 4. Database Design (PostgreSQL)

```sql
CREATE TABLE images (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename      TEXT NOT NULL,
    url_or_path   TEXT NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE image_metadata (
    image_id      UUID PRIMARY KEY REFERENCES images(id) ON DELETE CASCADE,
    subject       TEXT NOT NULL,
    category      TEXT NOT NULL,
    attributes    TEXT[] DEFAULT '{}',
    caption       TEXT NOT NULL,
    confidence    REAL NOT NULL,
    is_flagged    BOOLEAN NOT NULL DEFAULT FALSE,
    flag_reason   TEXT,
    model_used    TEXT NOT NULL,
    cost_usd      NUMERIC(10,6) NOT NULL DEFAULT 0,
    processed_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_image_metadata_category ON image_metadata(category);
CREATE INDEX idx_image_metadata_flagged ON image_metadata(is_flagged);

CREATE TABLE image_vectors (
    image_id      UUID PRIMARY KEY REFERENCES images(id) ON DELETE CASCADE,
    embedding     REAL[] NOT NULL,     -- upgrade to pgvector if needed later
    model_used    TEXT NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE posts (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title         TEXT NOT NULL,
    body          TEXT NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE post_vectors (
    post_id       UUID PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
    embedding     REAL[] NOT NULL,
    model_used    TEXT NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE suggestions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id         UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    image_id        UUID REFERENCES images(id) ON DELETE SET NULL, -- NULL if "no match"
    similarity      REAL,
    guard_passed    BOOLEAN NOT NULL,
    guard_reason    TEXT,
    status          TEXT NOT NULL DEFAULT 'pending', -- pending / approved / rejected
    created_at      TIMESTAMPTZ DEFAULT now(),
    reviewed_at     TIMESTAMPTZ
);
CREATE INDEX idx_suggestions_post ON suggestions(post_id);
CREATE INDEX idx_suggestions_status ON suggestions(status);

CREATE TABLE batch_jobs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type      TEXT NOT NULL,     -- 'vision_classify' / 'embed_images' / 'embed_posts'
    status        TEXT NOT NULL DEFAULT 'pending', -- pending/running/done/failed
    total_items   INT NOT NULL,
    completed     INT NOT NULL DEFAULT 0,
    failed        INT NOT NULL DEFAULT 0,
    retries       INT NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ DEFAULT now(),
    finished_at   TIMESTAMPTZ
);
```

---

## 5. API Surface (FastAPI)

```
POST   /images                      # register image(s), enqueue vision batch job
GET    /images/{id}                 # image + metadata + flag status
POST   /jobs/classify                # trigger batch classification job
POST   /jobs/embed                   # trigger batch embedding job
GET    /jobs/{id}                    # job progress + cost so far

POST   /posts                        # create post, enqueue post embedding
GET    /posts/{id}/images            # ranked suggestions + guard verdicts

POST   /suggestions/{id}/approve
POST   /suggestions/{id}/reject
GET    /suggestions/{id}             # inspect why an image was picked/refused

GET    /costs                        # per-call cost log summary
GET    /eval/run                     # runs eval set, returns top-1 precision
```

All request/response bodies are Pydantic models with explicit validation;
invalid input → `422` with a clear error, never a `500`.

---

## 6. Layer Sketch

```
app/
  api/            # FastAPI routers (thin — no business logic)
  services/       # vision.py, embeddings.py, matching.py, guard.py
  jobs/           # batch job runner + retry logic
  db/             # SQLAlchemy models + migrations (Alembic)
  schemas/        # Pydantic request/response + ImageMetadata
  config.py       # thresholds, model names, env vars
  main.py
tests/
eval/
  labeled_set.json
  run_eval.py
```

Business logic (`services/`) never imports FastAPI; routers only orchestrate.
DB and vision provider are swappable behind `services/` interfaces.

---

## 7. Initial Dataset Plan

~50 images, 5 categories, sourced from Unsplash/Pexels (license-checked):
`red fox`, `wolf`, `dog`, `bear`, `deer` — chosen specifically so the
fox/wolf visual-similarity trap exists to test the guard against.
5–6 draft blog posts written to match, plus 1–2 posts with **no** good image
in the corpus, to exercise the "no confident match" path.