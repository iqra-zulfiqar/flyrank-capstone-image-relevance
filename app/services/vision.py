"""
Vision service: sends an image to a vision model, forces structured JSON
output matching our schema, and validates the response before anything
downstream is allowed to trust it.

Golden rule: an invalid or malformed response is NEVER passed through.
It is retried (config.MAX_VISION_RETRIES times) and if it still fails,
the image is flagged with a clear reason instead of guessed at.

Two providers are supported (settings.VISION_PROVIDER):
  - "ollama" (default): fully local, no API key, no rate limits. Requires
    Ollama running locally with a vision model pulled (e.g. `ollama pull llava`).
  - "gemini": cloud, free tier — but as of Dec 2025 the free-tier quota
    was cut sharply (as low as ~20-25 requests/day for some Flash models),
    which isn't enough for a 50-image batch with retries. Kept available
    for anyone with a paid/higher-quota key.
"""
import base64
import json
import time
import mimetypes
from pathlib import Path

import requests
from pydantic import ValidationError

from app.config import settings
from app.schemas.image_metadata import ImageMetadata, ClassificationResult

PROMPT = """You are an image classification system. Look at this image and
respond with ONLY a JSON object (no markdown, no prose, no code fences)
matching exactly this shape:

{
  "subject": "<short specific noun phrase, e.g. 'red fox'>",
  "category": "<one of: animal, landscape, object, person, food, other>",
  "attributes": ["<up to 10 short descriptive tags>"],
  "caption": "<one sentence describing the image, 5-300 chars>",
  "confidence": <float 0.0-1.0, your genuine confidence in this classification>
}

Be specific with "subject" (e.g. "red fox" not just "animal"). If you are
unsure whether it's e.g. a fox or a wolf, say so honestly with a lower
confidence score rather than guessing high."""

# Matches ImageMetadata — passed to the model so it constrains output at
# generation time, not just something we check after the fact.
GEMINI_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "subject": {"type": "STRING"},
        "category": {
            "type": "STRING",
            "enum": ["animal", "landscape", "object", "person", "food", "other"],
        },
        "attributes": {"type": "ARRAY", "items": {"type": "STRING"}},
        "caption": {"type": "STRING"},
        "confidence": {"type": "NUMBER"},
    },
    "required": ["subject", "category", "attributes", "caption", "confidence"],
}

# Ollama accepts a plain JSON Schema (draft-7 style) for its "format" field.
OLLAMA_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "category": {
            "type": "string",
            "enum": ["animal", "landscape", "object", "person", "food", "other"],
        },
        "attributes": {"type": "array", "items": {"type": "string"}},
        "caption": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["subject", "category", "attributes", "caption", "confidence"],
}


def list_available_models() -> dict:
    """
    Diagnostic helper. For Ollama: lists locally pulled models. For
    Gemini: calls ListModels to show which cloud models this key can use.
    """
    if settings.VISION_PROVIDER == "ollama":
        url = f"{settings.OLLAMA_BASE_URL}/api/tags"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()

    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set — check your .env")
    url = f"{settings.GEMINI_API_BASE.rsplit('/models', 1)[0]}/models"
    headers = {"X-goog-api-key": settings.GEMINI_API_KEY}
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _encode_image(path: str) -> tuple[str, str]:
    """Returns (base64_data, mime_type)."""
    mime_type, _ = mimetypes.guess_type(path)
    if mime_type is None:
        mime_type = "image/jpeg"
    data = Path(path).read_bytes()
    return base64.b64encode(data).decode("utf-8"), mime_type


def _call_ollama(image_path: str) -> str:
    """
    Calls a local Ollama vision model. Returns the raw JSON text response.
    Raises requests.RequestException on failure (e.g. Ollama not running,
    or the model isn't pulled) — caller handles retry.
    """
    b64_data, _mime_type = _encode_image(image_path)

    url = f"{settings.OLLAMA_BASE_URL}/api/generate"
    payload = {
        "model": settings.OLLAMA_VISION_MODEL,
        "prompt": PROMPT,
        "images": [b64_data],
        "format": OLLAMA_RESPONSE_SCHEMA,
        "stream": False,
        "options": {"temperature": 0.1},
    }

    resp = requests.post(url, json=payload, timeout=120)  # local inference can be slow on CPU
    resp.raise_for_status()
    body = resp.json()
    return body.get("response", "")


def _call_gemini(image_path: str) -> str:
    """
    Calls Gemini's cloud API. Returns the raw JSON text response.
    Raises requests.RequestException on network/HTTP failure — caller
    handles retry.
    """
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set — check your .env")

    b64_data, mime_type = _encode_image(image_path)

    url = f"{settings.GEMINI_API_BASE}/{settings.GEMINI_VISION_MODEL}:generateContent"
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": settings.GEMINI_API_KEY,
    }
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": PROMPT},
                    {"inline_data": {"mime_type": mime_type, "data": b64_data}},
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": GEMINI_RESPONSE_SCHEMA,
            "temperature": 0.1,
        },
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    body = resp.json()

    try:
        return body["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        return json.dumps(body)  # keep something for debugging


def _call_vision_model(image_path: str) -> str:
    """Dispatches to whichever provider is configured."""
    if settings.VISION_PROVIDER == "ollama":
        return _call_ollama(image_path)
    return _call_gemini(image_path)


def _current_model_name() -> str:
    if settings.VISION_PROVIDER == "ollama":
        return f"ollama/{settings.OLLAMA_VISION_MODEL}"
    return settings.GEMINI_VISION_MODEL


def classify_image(image_id: str, image_path: str) -> ClassificationResult:
    """
    Classifies one image with retry-on-validation-failure.

    Never raises on a bad model response — always returns a
    ClassificationResult, either with valid metadata or flagged.
    """
    last_raw = ""
    total_cost = 0.0
    attempts = 0
    model_name = _current_model_name()

    for attempt in range(1, settings.MAX_VISION_RETRIES + 2):  # +1 initial try
        attempts = attempt
        try:
            raw_text = _call_vision_model(image_path)
            last_raw = raw_text
            total_cost += settings.COST_PER_IMAGE_CALL_USD

            parsed = json.loads(raw_text)
            metadata = ImageMetadata.model_validate(parsed)

            # Schema-valid. Now apply the confidence floor.
            if metadata.confidence < settings.LOW_CONFIDENCE_THRESHOLD:
                return ClassificationResult(
                    image_id=image_id,
                    metadata=metadata,
                    is_flagged=True,
                    flag_reason=(
                        f"Low confidence ({metadata.confidence:.2f} < "
                        f"{settings.LOW_CONFIDENCE_THRESHOLD}) — flagged for human review"
                    ),
                    raw_response=raw_text,
                    cost_usd=total_cost,
                    model_used=model_name,
                    attempts=attempts,
                )

            # Schema-valid AND confident — trusted.
            return ClassificationResult(
                image_id=image_id,
                metadata=metadata,
                is_flagged=False,
                flag_reason=None,
                raw_response=raw_text,
                cost_usd=total_cost,
                model_used=model_name,
                attempts=attempts,
            )

        except (json.JSONDecodeError, ValidationError) as e:
            # Bad shape — worth retrying, the model may just have wobbled.
            if attempt <= settings.MAX_VISION_RETRIES:
                time.sleep(settings.VISION_RETRY_BACKOFF_SECONDS * attempt)
                continue
            return ClassificationResult(
                image_id=image_id,
                metadata=None,
                is_flagged=True,
                flag_reason=f"Schema validation failed after {attempts} attempts: {e}",
                raw_response=last_raw,
                cost_usd=total_cost,
                model_used=model_name,
                attempts=attempts,
            )

        except requests.RequestException as e:
            # Network/HTTP failure — retry with backoff. 429 (cloud rate
            # limit) needs a much longer pause than a transient blip.
            is_rate_limited = (
                getattr(e, "response", None) is not None and e.response.status_code == 429
            )
            if attempt <= settings.MAX_VISION_RETRIES:
                if is_rate_limited:
                    time.sleep(20 * attempt)
                else:
                    time.sleep(settings.VISION_RETRY_BACKOFF_SECONDS * attempt)
                continue
            return ClassificationResult(
                image_id=image_id,
                metadata=None,
                is_flagged=True,
                flag_reason=f"API request failed after {attempts} attempts: {e}",
                raw_response=last_raw,
                cost_usd=total_cost,
                model_used=model_name,
                attempts=attempts,
            )

    # Unreachable in practice, but keeps type-checkers happy.
    return ClassificationResult(
        image_id=image_id, metadata=None, is_flagged=True,
        flag_reason="Unknown failure", raw_response=last_raw,
        cost_usd=total_cost, model_used=model_name,
        attempts=attempts,
    )