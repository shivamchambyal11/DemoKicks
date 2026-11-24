"""Thin LLM wrapper. The rest of the app only ever calls chat(messages).

Works with any OpenAI-compatible provider (Groq by default): change LLM_BASE_URL,
LLM_API_KEY and LLM_MODEL in .env, no code changes needed.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from contextlib import contextmanager
from functools import lru_cache

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from src.config import settings, setup_logging

logger = logging.getLogger(__name__)

_STATUS_HINTS = {
    401: "API key rejected. Check GROQ_API_KEY in .env.",
    404: "Model not found. Run `python -m src.llm --models` to see what your key can use.",
    429: "Rate limit reached. Try again shortly.",
}


class LLMError(RuntimeError):
    """Any LLM failure. Callers catch this instead of SDK-specific exceptions."""


@contextmanager
def _translate_errors():
    try:
        yield
    except APITimeoutError as exc:  # must come before APIConnectionError (it is a subclass)
        raise LLMError("The language model timed out.") from exc
    except APIConnectionError as exc:
        raise LLMError("Could not reach the language model service.") from exc
    except APIStatusError as exc:
        logger.error("LLM API error %s: %s", exc.status_code, exc.message)
        raise LLMError(_STATUS_HINTS.get(exc.status_code, f"Language model error (HTTP {exc.status_code}).")) from exc


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    if not settings.llm_api_key:
        raise LLMError("No API key found. Set GROQ_API_KEY in your .env file.")
    return OpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout_s,
        max_retries=settings.llm_max_retries,  # SDK retries 429 / 5xx / connection errors with backoff
    )


def chat(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Send chat messages and return the assistant's text."""
    model = model or settings.llm_model
    extra: dict = {}
    if settings.llm_reasoning_effort:
        extra["extra_body"] = {"reasoning_effort": settings.llm_reasoning_effort}

    start = time.perf_counter()
    with _translate_errors():
        resp = _client().chat.completions.create(
            model=model,
            messages=messages,
            temperature=settings.llm_temperature if temperature is None else temperature,
            max_completion_tokens=max_tokens or settings.llm_max_tokens,
            **extra,
        )

    choice = resp.choices[0]
    text = (choice.message.content or "").strip()
    usage = resp.usage
    # Never log message contents: they can contain customer data.
    logger.info(
        "LLM %s | %.2fs | tokens in/out = %s/%s | finish=%s",
        model,
        time.perf_counter() - start,
        usage.prompt_tokens if usage else "?",
        usage.completion_tokens if usage else "?",
        choice.finish_reason,
    )
    if choice.finish_reason == "length":
        logger.warning("Response hit the token limit. Consider raising LLM_MAX_TOKENS.")
    if not text:
        raise LLMError(
            f"The language model returned an empty response (finish_reason={choice.finish_reason}). "
            "With reasoning models, try a higher LLM_MAX_TOKENS or LLM_REASONING_EFFORT=low."
        )
    return text


def list_models() -> list[str]:
    """Model ids available to the configured API key."""
    with _translate_errors():
        return sorted(m.id for m in _client().models.list().data)


def _main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the LLM connection.")
    parser.add_argument("--models", action="store_true", help="list models your key can use")
    args = parser.parse_args()
    setup_logging()
    try:
        if args.models:
            print("\n".join(list_models()))
        else:
            print(chat([{"role": "user", "content": "Reply with exactly: DemoKicks LLM OK"}]))
    except LLMError as exc:
        logger.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main())