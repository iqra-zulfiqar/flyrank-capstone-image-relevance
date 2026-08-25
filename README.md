# Phase 2 — Vision Understanding Pipeline

Implements: structured vision output + schema validation, low-confidence
flagging, background batch processing with retries, and per-call cost
tracking. Maps directly to the Phase 2 checklist in the capstone brief.

## Setup

```bash
# 1. Start Postgres
docker compose up -d

# 2. Install deps
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# fill in GEMINI_API_KEY (Google AI Studio, free tier, no card)
# DATABASE_URL default already matches docker-compose.yml

# 4. Make sure Phase 1's image corpus exists
python seed_images.py   # if you haven't already

# 5. Run the API
uvicorn app.main:app --reload
```

API docs: http://localhost:8000/docs

## Walkthrough (Phase 2 gate: "all images tagged by the batch job, costs visible")

```bash
# Register the ~50 images from data/images/manifest.json into the DB
curl -X POST http://localhost:8000/images/register-from-manifest

# Kick off the vision classification batch job (returns immediately)
curl -X POST http://localhost:8000/jobs/classify
# -> {"id": "...", "status": "pending", "total_items": 50, ...}

# Poll job status/progress
curl http://localhost:8000/jobs/<job_id>
# -> {"status": "running", "completed": 12, "failed": 0, ...}
# ... poll again until status == "done"

# Inspect results
curl http://localhost:8000/images
curl http://localhost:8000/images?flagged_only=true   # low-confidence / failed items

# Check cost tracking (per-call, rolled up per job)
curl http://localhost:8000/costs
```

## What satisfies each Definition-of-Done box (§6 of the brief)

| Box | Where |
|---|---|
| Vision output validated against schema; invalid never trusted | `app/schemas/image_metadata.py` (`ImageMetadata`) + `app/services/vision.py` (`classify_image` — retries then flags on `ValidationError`/`JSONDecodeError`) |
| Low-confidence flagged, not accepted | `classify_image` — `confidence < LOW_CONFIDENCE_THRESHOLD` → `is_flagged=True` |
| Batch background job with retries | `app/jobs/batch_runner.py` + `BackgroundTasks` in `app/api/jobs.py`; per-attempt retry inside `classify_image` |
| Vision costs tracked per call | `ImageMetadata.cost_usd` per row, rolled up in `BatchJob.total_cost_usd`, exposed via `GET /costs` |

## Notes / honesty for BUILDLOG.md

- `gemini-2.0-flash` is being retired by Google — this pipeline defaults to
  `gemini-2.5-flash` via `GEMINI_VISION_MODEL` in `.env`. Check
  https://ai.google.dev/gemini-api/docs/models if it 404s for you and swap
  the env var — no code change needed.
- Cost figures (`COST_PER_IMAGE_CALL_USD`) are rough placeholders since
  free-tier calls are actually $0 — the point of Phase 2 is the *habit* of
  attributing cost per call, not the exact number. Update against
  https://ai.google.dev/pricing if you want it accurate.
- The batch job is idempotent: re-running `/jobs/classify` skips images
  that already have metadata, so a partial failure is safe to resume.
