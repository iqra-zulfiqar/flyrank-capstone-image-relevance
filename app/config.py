"""
Central config. All thresholds and model names live here (env-overridable) —
never hardcoded inside services, per the design doc.
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # --- Database ---
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5434/image_matching"
    )

    # --- Vision provider switch ---
    # "ollama" = fully local, no API key, no rate limits (recommended —
    # Gemini's free tier was cut to as low as 20-25 requests/day in Dec
    # 2025, which isn't enough for a 50-image batch with retries).
    # "gemini" = cloud, free tier, but rate-limited as above.
    VISION_PROVIDER: str = os.getenv("VISION_PROVIDER", "ollama")

    # --- Ollama (local vision model) ---
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_VISION_MODEL: str = os.getenv("OLLAMA_VISION_MODEL", "llava")

    # --- Gemini (cloud, kept for optional use / Phase 3 embeddings) ---
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_VISION_MODEL: str = os.getenv("GEMINI_VISION_MODEL", "gemini-flash-latest")
    GEMINI_EMBEDDING_MODEL: str = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
    GEMINI_API_BASE: str = "https://generativelanguage.googleapis.com/v1beta/models"

    # --- Vision pipeline thresholds ---
    LOW_CONFIDENCE_THRESHOLD: float = float(os.getenv("LOW_CONFIDENCE_THRESHOLD", "0.6"))
    MAX_VISION_RETRIES: int = int(os.getenv("MAX_VISION_RETRIES", "2"))
    VISION_RETRY_BACKOFF_SECONDS: float = float(os.getenv("VISION_RETRY_BACKOFF_SECONDS", "2.0"))

    # --- Cost tracking ---
    # Ollama is $0 (local compute) — cost tracking still runs so the
    # habit/plumbing exists, it'll just log 0.0 per call under Ollama.
    COST_PER_IMAGE_CALL_USD: float = float(os.getenv("COST_PER_IMAGE_CALL_USD", "0.0"))
    COST_PER_EMBEDDING_CALL_USD: float = float(os.getenv("COST_PER_EMBEDDING_CALL_USD", "0.00002"))

    # --- Embedding provider switch (Phase 3) ---
    # Same reasoning as vision: default to local Ollama to avoid any
    # repeat of the Gemini free-tier quota problems from Phase 2.
    EMBEDDING_PROVIDER: str = os.getenv("EMBEDDING_PROVIDER", "ollama")
    OLLAMA_EMBEDDING_MODEL: str = os.getenv("OLLAMA_EMBEDDING_MODEL", "all-minilm")

    # --- Rate limiting (only meaningful for the Gemini path) ---
    RATE_LIMIT_DELAY_SECONDS: float = float(os.getenv("RATE_LIMIT_DELAY_SECONDS", "0.0"))
    SIMILARITY_THRESHOLD: float = float(os.getenv("SIMILARITY_THRESHOLD", "0.5"))

    # --- Mismatch guard (Phase 3) ---
    # The corpus was deliberately built around these five animal
    # categories (see DESIGN.md §7) specifically so the guard has a
    # real fox/wolf visual-similarity trap to defend against. Used to
    # detect a post's expected subject and compare it against a
    # candidate image's detected subject.
    GUARD_KNOWN_SUBJECTS: list[str] = os.getenv(
        "GUARD_KNOWN_SUBJECTS", "fox,wolf,dog,bear,deer"
    ).split(",")


settings = Settings()