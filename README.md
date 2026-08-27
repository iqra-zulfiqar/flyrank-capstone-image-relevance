# AI Image Understanding & Content Matching Engine

Understands an image library, tags it automatically, and matches the
right image to the right blog post based on meaning — a red-fox post
gets a red-fox photo, never a wolf. Refuses to guess when nothing is a
confident enough match.

**Stack:** Python + FastAPI · PostgreSQL (Docker) · Pydantic · Ollama
(`llava` for vision, `all-minilm` for embeddings — fully local, $0, no
API keys, no rate limits)

## Architecture

```
Images ─(batch job)─► Ollama (llava) ─► {tags, caption, confidence} ─► image_metadata
 └─► embed(caption) via Ollama (all-minilm) ──────────► image_vectors

Posts ──────────────► embed(post text) via Ollama ───────────────────► post_vectors

GET /posts/:id/images
 └─► Similarity Ranking (cosine: image_vectors × post_vector)
 └─► Mismatch Guard
      1. Confidence floor  (reject low-confidence/flagged images)
      2. Category match    (reject "fox post, wolf image" even if similar)
      3. Similarity floor  (reject genuinely unrelated content)
 ├─► Suggested image (ranked, explained)
 └─► "No confident match" + explanation
 └─► Review API: approve / reject / inspect
```

Layers: `app/api/` (thin HTTP routers) → `app/services/` (business
logic: vision, embeddings, matching, guard) → `app/db/` (SQLAlchemy
models) → `app/jobs/` (background batch runners). Routers never contain
business logic; services never import FastAPI.

## Setup

```bash
# 1. Start Postgres
docker compose up -d

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install and start Ollama (https://ollama.com/download), then pull models
ollama pull llava
ollama pull all-minilm

# 4. Configure environment
cp .env.example .env
# defaults already point at local Ollama — no API keys required

# 5. Seed the image corpus (~50 images, 5 categories)
python seed_images.py

# 6. Run the API
uvicorn app.main:app --reload
```

API docs: http://localhost:8000/docs

## Seed + demo walkthrough

```bash
curl -X POST http://localhost:8000/images/register-from-manifest
curl -X POST http://localhost:8000/jobs/classify   # poll GET /jobs/{id} until done
curl -X POST http://localhost:8000/jobs/embed       # poll until done

curl -X POST http://localhost:8000/posts -H "Content-Type: application/json" \
  -d '{"title": "The behavior of red foxes", "body": "Vulpes vulpes is a cunning animal."}'

curl http://localhost:8000/posts/<post_id>/images
# -> matched: true, a fox image, guard_passed: true

curl -X POST http://localhost:8000/posts/<post_id>/force-match/<a_wolf_image_id>
# -> guard_passed: false, "Category mismatch: expected 'fox', detected 'wolf'"
```

Full walkthrough with all 6 probes: see [`PHASE3_README.md`](./PHASE3_README.md).

## Troubleshooting

**Port 8000 already in use / server reachable at `127.0.0.1` but not
`localhost` (or vice versa):** on some Windows setups, Docker Desktop's
backend (`com.docker.backend`) silently binds port 8000, intercepting
requests meant for uvicorn. Symptom: Swagger loads fine but API calls
404 as if an older/different version of the app is running. Fix — run
on a different port and use it consistently everywhere:
```bash
uvicorn app.main:app --reload --port 8001
# then use http://127.0.0.1:8001 in Swagger, curl, and:
python eval/run_eval.py --base-url http://127.0.0.1:8001
```

## Running tests and the eval

```bash
pytest tests/ -v          # 28 deterministic unit tests — schema, guard, matching math
python eval/run_eval.py   # requires the API running + corpus classified/embedded
```

## Evaluation result

Top-1 precision on the labeled set (`eval/labeled_set.json`, 6 posts —
one per animal category plus one deliberate no-match case), measured
against a live run:

**Top-1 precision: 66.67% (4/6)**

```
[PASS] The behavior of red foxes    -> matched 'red fox' (similarity 0.64)
[PASS] Living with wolves in the wild -> matched 'wolf pack' (similarity 0.68)
[FAIL] Why dogs make great companions -> similarity 0.34, below 0.50 threshold
[PASS] The diet of North American bears -> matched 'bears' (similarity 0.51)
[FAIL] Deer migration patterns in autumn -> similarity 0.49, below 0.50 threshold
[PASS] A guide to houseplants (no match expected) -> correctly found no match
```

Both failures are the guard correctly **refusing to guess** rather than
false positives — the dog and deer posts scored just below the
similarity threshold (0.34 and 0.49 respectively) with `all-minilm`.
The deer case in particular sits right at the boundary (0.49 vs. 0.50),
suggesting the threshold could be lowered slightly to trade a bit of
guard strictness for higher recall — a real tuning decision, not
something to paper over. Kept at 0.5 for this submission since a
stricter guard erring toward "no confident match" over a wrong
suggestion matches the brief's own stated priority (§1: "The most
important production feature is not finding a match — it is avoiding a
wrong match").

Run it yourself: `python eval/run_eval.py` (requires the API running
with the corpus classified and embedded).

## Limitations (honest)

- **Category detection is keyword-based**, not a second model call — it
  looks for one of five known animal names (with basic plural handling)
  as a substring in post text and image tags. This is fast and fully
  explainable, but won't generalize past this five-category demo corpus
  without extending `GUARD_KNOWN_SUBJECTS` and `SUBJECT_VARIANTS` in
  `app/services/guard.py`.
- **Similarity threshold (0.5) is tuned to this specific corpus and
  `all-minilm`** — a different embedding model or a larger/more varied
  corpus would need its own recalibration, not a reused constant.
- **No pgvector** — embeddings are stored as plain Postgres arrays and
  compared in Python. Fine at ~50 images; would need a real vector index
  at meaningfully larger scale.
- **Ollama vision (`llava`) occasionally returns malformed JSON on the
  first attempt** (~1 in 10-15 calls) — caught and retried by schema
  validation, not silently accepted. See `BUILDLOG.md` for the full
  Gemini→Ollama migration story and why local inference was chosen over
  the brief's cloud option.
- **No authentication** on any endpoint — fine for a local capstone demo,
  not something to expose publicly as-is.

## Required submission files

- [`DESIGN.md`](./DESIGN.md) — Phase 1 design doc
- [`EVIDENCE.md`](./EVIDENCE.md) — one proof per Definition-of-Done checkbox
- [`BUILDLOG.md`](./BUILDLOG.md) — honest AI-usage log
- [`capstone.yaml`](./capstone.yaml) — machine-readable run/seed/test manifest
- [`.env.example`](./.env.example) — every environment variable, safe placeholders