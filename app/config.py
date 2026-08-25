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

    # --- Rate limiting (only meaningful for the Gemini path) ---
    RATE_LIMIT_DELAY_SECONDS: float = float(os.getenv("RATE_LIMIT_DELAY_SECONDS", "0.0"))
    SIMILARITY_THRESHOLD: float = float(os.getenv("SIMILARITY_THRESHOLD", "0.75"))


settings = Settings()