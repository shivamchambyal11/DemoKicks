"""Hallucination guard: decide whether the bot may answer or must hand off to a human.

Layers, cheapest first:
  1. input check       - empty / oversized messages
  2. retrieval check   - best passage too far from the question -> skip the LLM entirely
  3. generation check  - model declined, or answered without a valid citation
  4. failure check     - LLM outage -> graceful message instead of a traceback

CLI:
    python -m src.guard "Can I cancel my order?"
    python -m src.guard --calibrate    # print retrieval distances to tune GUARD_MAX_DISTANCE
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from dataclasses import dataclass, field

from src.config import settings, setup_logging
from src.llm import LLMError
from src.rag import NO_ANSWER, Passage, RagAnswer, generate, retrieve

logger = logging.getLogger(__name__)

# Keep contact details consistent with data/docs/faq.md
FALLBACK_MESSAGE = (
    "I don't know the answer to that, so I'm connecting you to a human agent. "
    "You can also email support@demokicks.example or use live chat "
    "Monday to Friday, 9 AM to 6 PM EST."
)
ERROR_MESSAGE = (
    "Sorry, I'm having technical trouble right now. "
    "Please email support@demokicks.example and a human agent will help you."
)
EMPTY_MESSAGE = "Please type your question."
TOO_LONG_MESSAGE = "That message is a bit long. Could you shorten it to a sentence or two?"

_DECLINE = NO_ANSWER.lower()


@dataclass(frozen=True)
class Reply:
    text: str                      # what the customer sees
    sources: list[Passage]         # citations to display (empty on fallback)
    needs_human: bool              # UI can show a "contact support" button
    reason: str | None             # None = answered; otherwise why we fell back
    retrieved: list[Passage] = field(default_factory=list)  # for logs and evals
    raw_answer: str | None = None  # model output we discarded, for debugging


# --------------------------------------------------------------------------- #
# Individual checks (pure functions: easy to unit-test)
# --------------------------------------------------------------------------- #
def _normalize(text: str) -> str:
    text = text.lower().replace("\u2019", "'")  # curly apostrophe -> straight
    return " ".join(re.sub(r"[^a-z' ]", " ", text).split())


def is_decline(text: str, has_citations: bool) -> bool:
    """True if the model said it doesn't know. A partial answer that still cites sources is kept."""
    norm = _normalize(text)
    return norm == _DECLINE or (norm.startswith(_DECLINE) and not has_citations)


def check_retrieval(passages: list[Passage]) -> str | None:
    if not passages:
        return "no_results"
    best = min(p.distance for p in passages)
    logger.info("Guard: best distance %.3f (limit %.2f)", best, settings.guard_max_distance)
    return "low_relevance" if best > settings.guard_max_distance else None


def check_answer(result: RagAnswer) -> str | None:
    if is_decline(result.answer, bool(result.cited)):
        return "model_declined"
    if settings.guard_require_citations and not result.cited:
        return "no_citations"
    return None


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _handoff(reason: str, passages: list[Passage], raw: str | None = None) -> Reply:
    logger.info("Guard: handing off to human (reason=%s)", reason)
    return Reply(FALLBACK_MESSAGE, [], True, reason, passages, raw)


def respond(question: str) -> Reply:
    """The one function the UI calls."""
    question = (question or "").strip()
    if not question:
        return Reply(EMPTY_MESSAGE, [], False, "empty_input")
    if len(question) > settings.guard_max_question_chars:
        return Reply(TOO_LONG_MESSAGE, [], False, "input_too_long")

    passages = retrieve(question)
    reason = check_retrieval(passages)
    if reason:
        return _handoff(reason, passages)  # no LLM call: cheaper, faster, deterministic

    try:
        result = generate(question, passages)
    except LLMError as exc:
        logger.error("LLM unavailable, handing off to a human: %s", exc)
        return Reply(ERROR_MESSAGE, [], True, "llm_error", passages)

    reason = check_answer(result)
    if reason:
        return _handoff(reason, passages, raw=result.answer)

    return Reply(result.answer, result.cited, False, None, passages)


# --------------------------------------------------------------------------- #
# CLI: test the guard and calibrate the distance threshold
# --------------------------------------------------------------------------- #
CALIBRATION_SETS = {
    "in_scope (should pass)": [
        "Can I return sale shoes?",
        "How long does a refund take?",
        "Do you ship to Canada?",
        "Which size should I order in AeroRun?",
        "How do I measure my foot?",
        "The sole of my shoes came off. Is it covered by warranty?",
        "Can I cancel my order?",
        "Which payment methods do you accept?",
        "How much does express shipping cost?",
        "Do you sell gift cards?",
        "How do I reach a human agent?",
        "Do you have a physical store?",
    ],
    "off_topic (should be blocked by distance)": [
        "What's the weather in Delhi?",
        "Tell me a joke",
        "What is the capital of France?",
        "Write a Python function to reverse a string",
        "How do I bake a chocolate cake?",
        "Who will win the next election?",
    ],
    "on_domain_but_unanswerable (distance cannot catch these)": [
        "Do you sell Nike Air Max?",
        "Who is the CEO of DemoKicks?",
        "Do you offer student discounts?",
    ],
}


def calibrate() -> None:
    best_by_group: dict[str, list[float]] = {}
    for group, questions in CALIBRATION_SETS.items():
        print(f"\n== {group} ==")
        distances = []
        for q in questions:
            top = retrieve(q, k=1)[0]
            distances.append(top.distance)
            print(f"  {top.distance:.3f} | {q}  ->  {top.source} > {top.section}")
        best_by_group[group] = distances

    in_scope_max = max(best_by_group["in_scope (should pass)"])
    off_topic_min = min(best_by_group["off_topic (should be blocked by distance)"])
    print(f"\nWorst in-scope distance : {in_scope_max:.3f}")
    print(f"Closest off-topic       : {off_topic_min:.3f}")
    if in_scope_max < off_topic_min:
        print(f"Clean gap. Suggested GUARD_MAX_DISTANCE ~ {(in_scope_max + off_topic_min) / 2:.2f}")
    else:
        print("Distributions overlap: distance alone cannot separate them. "
              "Pick a value below the closest off-topic distance and let the LLM check handle the rest.")
    print("Current setting         :", settings.guard_max_distance)


def _print_reply(reply: Reply, debug: bool) -> None:
    print(f"\nBot: {reply.text}")
    if reply.sources:
        print("\nSources:")
        for p in reply.sources:
            print(f"  [{p.n}] {p.source} > {p.section}")
    print(f"\n[needs_human={reply.needs_human} reason={reply.reason}]")
    if debug:
        if reply.raw_answer:
            print(f"\nDiscarded model answer: {reply.raw_answer}")
        print("\nRetrieved:")
        for p in reply.retrieved:
            print(f"   [{p.n}] dist={p.distance:.3f} | {p.source} > {p.section}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Test the DemoKicks hallucination guard.")
    parser.add_argument("question", nargs="*", help="question text (omit for interactive mode)")
    parser.add_argument("--debug", action="store_true", help="show retrieved passages and discarded answers")
    parser.add_argument("--calibrate", action="store_true", help="print distances to tune the threshold")
    args = parser.parse_args(argv)
    setup_logging()

    try:
        if args.calibrate:
            calibrate()
        elif args.question:
            _print_reply(respond(" ".join(args.question)), args.debug)
        else:
            print("DemoKicks guarded bot. Empty line to quit.")
            while question := input("\nYou: ").strip():
                _print_reply(respond(question), args.debug)
    except (EOFError, KeyboardInterrupt):
        print()
    except RuntimeError as exc:  # e.g. empty index: a deployment problem, not a customer problem
        logger.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())