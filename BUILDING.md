# BUILDLOG.md

Honest log of where AI (Claude) helped, where it was wrong, and what I
changed. Updated as I go through each phase, not written after the fact.

---

## Phase 1 — Design

**AI helped with:**
- Drafting the initial `DESIGN.md` — the `ImageMetadata` Pydantic schema,
  the Postgres table design, and the mismatch guard rule table (category
  match / subject overlap / similarity floor / confidence floor).
- Writing `seed_images.py` to pull images from the Unsplash and Pexels
  free APIs and generate a reproducible `manifest.json` instead of
  committing raw image binaries.

**What I changed / caught myself:**
- Had to get my own Unsplash Access Key and Pexels API key manually —
  AI can't do this part, correctly told me where to sign up (both free,
  no card).
- Confirmed manually that the Unsplash **Secret Key** wasn't needed
  (only the Access Key) — worth double-checking against the docs rather
  than assuming, since it's easy to grab the wrong key.

---

## Phase 2 — Vision Understanding Pipeline

This phase had the most real debugging. Logging it honestly because most
of it wasn't a first-try success.

### Environment setup issues (not AI's fault, just Windows/Python friction)
- `psycopg2-binary` failed to build from source on Python 3.13 (no
  precompiled wheel yet, and no local `pg_config`/C toolchain). AI
  correctly diagnosed this from the pip error output and switched the
  project to `psycopg[binary]` (psycopg 3), which does ship Windows
  3.13 wheels. Required updating the SQLAlchemy connection string prefix
  from `postgresql://` to `postgresql+psycopg://`.
- Hit a `ModuleNotFoundError: sqlalchemy` even after a "successful"
  pip install — turned out the first install attempt aborted entirely
  because one package (psycopg2-binary) failed to build, so nothing else
  installed either. Not obvious from the pip output at a glance.
- Docker port conflicts (`5432` already in use, then `5433` also in use)
  — resolved by just picking an open host port (`5434`) and updating
  `docker-compose.yml` + `DATABASE_URL` to match.

### A real bug I should flag: UUID/Decimal serialization
- `POST /jobs/classify` was returning a bare 500 with no useful detail
  in Swagger. Root cause (found after actually reading the terminal
  traceback, not just the Swagger error): the `BatchJobOut` Pydantic
  response model expected `id: str`, but the SQLAlchemy `BatchJob.id`
  is a `UUID` object and `total_cost_usd` is a `Decimal` — neither is
  auto-coerced by Pydantic on response validation, so FastAPI silently
  raised and returned a generic 500. AI wrote this bug into the first
  version of `api/jobs.py` and only caught it once I pushed for the
  actual terminal traceback instead of accepting "try restarting" as an
  answer. Fixed with an explicit `_to_job_out()` conversion helper.
- **Lesson for me:** Swagger's error panel alone is not enough to debug
  a 500 — the real traceback lives in the terminal running uvicorn, and
  I needed to actually go find it rather than just re-describing the
  browser screen.

### The Gemini model/auth saga (the big one)
1. First attempt used `gemini-2.5-flash` — got a 404. AI's first guess
   (assumed it might already be deprecated) was wrong; the model was
   still valid.
2. Diagnosed properly via a `/costs/debug/models` endpoint (calls
   Gemini's own `ListModels`) — confirmed the key worked and the model
   existed, so the 404 was something else.
3. Found the actual issue by comparing against Google's own working
   curl example: the API key needs to be passed as an `X-goog-api-key`
   **header**, not a `?key=` query parameter, and the model should be
   the rolling alias `gemini-flash-latest` rather than a dated version
   string. Fixed both.
4. Once auth was fixed, hit `429 Too Many Requests` — Google cut Gemini
   free-tier quotas heavily in December 2025, down to as low as
   ~20-25 requests/day for some Flash models. A 50-image batch with
   schema-validation retries (up to 3 attempts per image) easily
   exceeds that in a single run.
5. Tried increasing the delay between calls (4.5s, then 13s) to stay
   under the per-minute limit — didn't fully fix it, because the
   blocking constraint was the **daily** quota, not the per-minute one.
   No amount of pacing fixes an exhausted daily quota.
6. **Decision:** switched the vision provider to **Ollama**, running
   `llava` locally — this is explicitly listed as a valid $0 option in
   the brief's own stack table (§10), not a workaround outside the
   assignment's scope. Added a `VISION_PROVIDER` config switch so both
   Gemini and Ollama code paths still exist; Ollama is now the default.
   This eliminated the rate-limit problem entirely (no external API,
   no quota) and completed a clean 50/50 run with `retries: 54`
   (automatic recovery from occasional malformed JSON on `llava`'s
   first attempt — proof the retry logic works for real, not just in
   theory).

---

## Phase 3 — Matching Engine + Mismatch Guard

**AI helped with:**
- Designing the embedding pipeline (defaulted to local Ollama `all-minilm`
  from the start this time, learning from Phase 2's Gemini quota pain —
  didn't wait to hit the same wall twice).
- Writing the mismatch guard (`guard.py`) with a simple, deterministic
  keyword-based subject extraction rather than a second LLM call — kept
  it fast and explainable rather than sophisticated.
- Adding a `force-match` endpoint specifically so the brief's "watch it
  refuse the wolf" demo moment is reproducible on command, rather than
  hoping a wolf image ranks high enough naturally to reach the guard.

**Real issues I hit and how they got fixed:**

1. **Similarity threshold was wrong on the first try.** Set to 0.75
   (a value that seemed reasonable from general embedding-similarity
   conventions), but the fox post's actual best match only scored 0.63
   — correctly ranked, but rejected by an unrealistic threshold. Fixed
   by actually looking at real similarity scores from my own corpus
   (0.60-0.65 for genuine matches, ~0.28 for genuinely unrelated
   content) and setting the threshold to 0.5, in between. This is
   exactly the kind of threshold tuning the brief describes (§2:
   "you'll pick thresholds using your own labeled eval set — and defend
   the fox/wolf boundary at the demo with a precision number, not a
   feeling") — I initially skipped the "using real data" part and had
   to go back and do it properly.

2. **The guard's check order hid its best feature.** When I forced a
   wolf image onto the fox post, the guard correctly rejected it — but
   the reason given was "similarity too low," not "category mismatch."
   Both are true, but the similarity check ran first and short-circuited
   before the category check ever ran. Since the brief's whole demo
   moment is specifically about *category* mismatch (fox vs. wolf, not
   just "unrelated"), I reordered the checks so subject/category runs
   before similarity. This was a genuine design bug, not a display
   issue — a system that only ever says "too dissimilar" isn't
   demonstrating the specific safety property the guard is meant to
   have.

3. **Approving a rejected suggestion needed an explicit block.** Wrote
   the `/suggestions/{id}/approve` endpoint to check `guard_passed`
   before allowing approval — otherwise the review workflow would let a
   human silently override the guard's safety verdict through a
   different API path, defeating the whole point of having a guard.
   Verified this with the houseplants "no confident match" suggestion:
   attempting to approve it correctly returns a 400 with the guard's
   original rejection reason.

**What I'd do differently next time:** get real similarity-score data
from the actual corpus *before* picking a threshold, rather than
guessing a plausible-sounding number first and discovering it's wrong
via a failed demo test. Also worth deciding guard check order up front
based on "what does this check specifically prove" rather than
whatever order felt natural to write first.

---

