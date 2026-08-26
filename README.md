# Phase 3 — Matching Engine + Mismatch Guard

Implements: embeddings for images + posts, similarity ranking, and the
mismatch guard with human-readable rejection reasons. This is the
production-critical part of the whole capstone — see DESIGN.md §3.

## Setup

```bash
# Additional local model needed (vision model from Phase 2 already pulled)
ollama pull all-minilm

# Make sure Phase 2 is done first — images must be classified
# (POST /jobs/classify) before they can be embedded/matched.

# Restart the API if it isn't already running
uvicorn app.main:app --reload
```

## Walkthrough

### 1. Embed the image corpus

```bash
curl -X POST http://localhost:8000/jobs/embed
# -> {"id": "...", "status": "pending", "total_items": 50, ...}

curl http://localhost:8000/jobs/<job_id>
# poll until status == "done"
```

### 2. Create some posts (test seed — mirrors §7 "Realistic scope")

```bash
curl -X POST http://localhost:8000/posts \
  -H "Content-Type: application/json" \
  -d '{"title": "The behavior of red foxes", "body": "Red foxes are highly adaptable animals found across many habitats, from forests to urban edges. Vulpes vulpes is known for its cunning and varied diet."}'

curl -X POST http://localhost:8000/posts \
  -H "Content-Type: application/json" \
  -d '{"title": "Living with wolves in the wild", "body": "Gray wolves are apex predators that live and hunt in coordinated packs."}'

curl -X POST http://localhost:8000/posts \
  -H "Content-Type: application/json" \
  -d '{"title": "A guide to houseplants", "body": "This post has nothing to do with any animal in the corpus, to test the no-confident-match path."}'
```

Each `POST /posts` response includes `has_embedding: true` once embedded
inline. Copy the `id` from the fox post — call it `FOX_POST_ID` below.

### 3. Probe 2 — fox post ranks the fox image first

```bash
curl http://localhost:8000/posts/FOX_POST_ID/images
```
Expected: `matched: true`, `suggested_image_id` pointing at a fox photo,
and the `candidates` list shows fox images ranked above wolf/dog/bear/deer.

### 4. Probe 3 — force the wolf as a candidate for the fox post

```bash
curl -X POST http://localhost:8000/posts/FOX_POST_ID/force-match/WOLF_IMAGE_ID
```
Expected:
```json
{
  "guard_passed": false,
  "guard_reason": "Category mismatch: expected 'fox', detected 'wolf'"
}
```
(Get a `WOLF_IMAGE_ID` from `GET /images` — find one where `subject`
contains "wolf".)

### 5. Probe 4 — no confident match

```bash
curl http://localhost:8000/posts/<houseplants_post_id>/images
```
Expected: `matched: false`, with a `reason` explaining why (similarity
below threshold, or no known subject overlap).

### 6. Review workflow

```bash
curl -X POST http://localhost:8000/suggestions/<suggestion_id>/approve
curl -X POST http://localhost:8000/suggestions/<suggestion_id>/reject
curl http://localhost:8000/suggestions/<suggestion_id>
```
Note: approving a suggestion the guard rejected (`guard_passed: false`)
is blocked with a 400 — the guard's verdict can't be silently overridden
through the review API.

### 7. Eval — top-1 precision (Phase 4 will formalize this into a script)

For now, manually run `GET /posts/{id}/images` against each of the 5
categories' test posts and check whether the top-ranked, guard-passed
suggestion matches the intended category. That ratio is your top-1
precision number for the README.

## How this satisfies the Phase 3 checklist (§8)

| Requirement | Where |
|---|---|
| Embeddings for images + posts | `app/services/embeddings.py`, `app/jobs/embed_runner.py` |
| Similarity search + ranking | `app/services/matching.py` (`rank_candidates`) |
| Semantic matching across wording | Embedding-based, not keyword — "red fox" and "Vulpes vulpes" land close in vector space |
| Mismatch guard rejects wrong candidates | `app/services/guard.py` (`evaluate_guard`) — confidence floor → similarity floor → subject/category match, in order |
| Rejections include human-readable explanation | Every guard failure returns a specific `reason` string, never a bare boolean |
| "No confident match" + reasons | `GET /posts/{id}/images` returns `matched: false` with the top candidate's rejection reason when nothing passes |
