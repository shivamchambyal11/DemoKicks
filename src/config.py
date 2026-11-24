"""Central configuration. Every tunable lives here and can be overridden via .env."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Anchor all paths to the project root so scripts work from any working directory.
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    # --- data / index ---
    docs_dir: Path = ROOT_DIR / "data" / "docs"
    chroma_dir: Path = Path(os.getenv("CHROMA_DIR", ROOT_DIR / "chroma_db"))
    collection_name: str = os.getenv("COLLECTION_NAME", "demokicks_kb")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    chunk_max_chars: int = int(os.getenv("CHUNK_MAX_CHARS", "900"))
    chunk_overlap_chars: int = int(os.getenv("CHUNK_OVERLAP_CHARS", "150"))
    top_k: int = int(os.getenv("TOP_K", "4"))

    # --- LLM (any OpenAI-compatible provider) ---
    llm_api_key: str = os.getenv("LLM_API_KEY") or os.getenv("GROQ_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    llm_model: str = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
    llm_temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.1"))
    # Reasoning models spend part of this budget on hidden "thinking" tokens.
    llm_max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "1500"))
    # "low" | "medium" | "high" for gpt-oss; set empty for non-reasoning models.
    llm_reasoning_effort: str = os.getenv("LLM_REASONING_EFFORT", "low")
    llm_timeout_s: float = float(os.getenv("LLM_TIMEOUT_S", "30"))
    llm_max_retries: int = int(os.getenv("LLM_MAX_RETRIES", "3"))

    log_level: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()

_NOISY_LOGGERS = ("httpx", "httpx2", "httpcore", "httpcore2", "urllib3", "sentence_transformers", "chromadb")


def setup_logging() -> None:
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)