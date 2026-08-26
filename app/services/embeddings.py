"""
Embedding service: turns text (image captions, post content) into
vectors in a shared semantic space, so "red fox", "Vulpes vulpes", and
"wild fox species" land close together despite different wording.

Defaults to local Ollama (all-minilm) — same reasoning as the vision
service in Phase 2: avoids any repeat of Gemini's free-tier rate limits.
"""
import math
import requests

from app.config import settings


def _embed_ollama(text: str) -> list[float]:
    url = f"{settings.OLLAMA_BASE_URL}/api/embeddings"
    payload = {"model": settings.OLLAMA_EMBEDDING_MODEL, "prompt": text}
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    embedding = body.get("embedding")
    if not embedding:
        raise RuntimeError(f"Ollama returned no embedding for text: {text[:50]!r}")
    return embedding


def _embed_gemini(text: str) -> list[float]:
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set — check your .env")

    url = f"{settings.GEMINI_API_BASE}/{settings.GEMINI_EMBEDDING_MODEL}:embedContent"
    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": settings.GEMINI_API_KEY,
    }
    payload = {
        "content": {"parts": [{"text": text}]},
        "taskType": "SEMANTIC_SIMILARITY",
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    return body["embedding"]["values"]


def get_embedding(text: str) -> tuple[list[float], str, float]:
    """
    Returns (embedding, model_used, cost_usd).
    Raises requests.RequestException / RuntimeError on failure — callers
    decide how to handle (retry, flag, etc.), same pattern as vision.py.
    """
    if settings.EMBEDDING_PROVIDER == "ollama":
        embedding = _embed_ollama(text)
        model_used = f"ollama/{settings.OLLAMA_EMBEDDING_MODEL}"
        cost = 0.0
    else:
        embedding = _embed_gemini(text)
        model_used = settings.GEMINI_EMBEDDING_MODEL
        cost = settings.COST_PER_EMBEDDING_CALL_USD

    return embedding, model_used, cost


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Standard cosine similarity, pure Python — no numpy needed at this scale."""
    if len(a) != len(b):
        raise ValueError(f"Embedding dimension mismatch: {len(a)} vs {len(b)}")

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)