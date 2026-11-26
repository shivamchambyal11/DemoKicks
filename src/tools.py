"""Order-status tool: verified lookup in the mock orders DB + deterministic reply formatting.

An LLM never writes order facts: it could invent a tracking number or a date, so every
fact in the reply comes straight from data/orders.json.

CLI:
    python -m src.tools                       # interactive demo (keeps conversation state)
    python -m src.tools --today 2026-11-24   # pin "today" for reproducible output
"""
from __future__ import annotations

import argparse
import calendar
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache

from src.config import settings, setup_logging

logger = logging.getLogger(__name__)

SUPPORT_EMAIL = "support@demokicks.example"

# Policy constants. They mirror data/docs/returns.md and warranty.md.
# If you change the docs, change these too (the tests will tell you what broke).
RETURN_WINDOW_DAYS = 30
HOLIDAY_START = (11, 1)            # delivered Nov 1 ...
HOLIDAY_END = (12, 24)             # ... through Dec 24 gets the holiday extension
HOLIDAY_RETURN_DEADLINE = (1, 31)  # returnable until Jan 31 of the following year
WARRANTY_MONTHS = 12

ORDER_ID_RE = re.compile(r"\bDK\d{4}\b", re.IGNORECASE)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_THING = r"(?:order|package|parcel|shipment)"
# Deliberately narrow, so policy questions ("Can I cancel my order?") still go to the RAG bot.
STATUS_INTENT_RE = re.compile(
    rf"\bwhere(?:['\u2019]s|\s+is)\s+my\s+{_THING}\b"
    rf"|\btrack\s+my\s+{_THING}\b"
    rf"|\bstatus\s+of\s+my\s+{_THING}\b"
    rf"|\b{_THING}\s+status\b",
    re.IGNORECASE,
)

ASK_ORDER_ID = "Sure, I can check that. What is your order number? (format DK1234)"
ASK_EMAIL = "Thanks. To protect your privacy, please also confirm the email address used at checkout."
NOT_FOUND = "I couldn't find an order matching that order number and email. Please double-check both."
LOCKED = (
    "For your security I can't look up more orders in this chat. "
    f"Please email {SUPPORT_EMAIL} and a human agent will help you."
)


class ToolError(RuntimeError):
    """The orders DB is missing or unreadable: a deployment problem, not a customer problem."""


@dataclass(frozen=True)
class OrderFlow:
    """State of an in-progress lookup. The UI stores it and passes it back on the next message."""
    order_id: str | None = None
    email: str | None = None
    failed: int = 0  # failed verifications this session (anti-enumeration)


@dataclass(frozen=True)
class ToolReply:
    handled: bool  # False -> not an order question: send it to the RAG bot
    text: str = ""
    flow: OrderFlow = field(default_factory=OrderFlow)
    outcome: str = ""  # for logs and tests


# --------------------------------------------------------------------------- #
# Data access
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def _orders() -> dict[str, dict]:
    path = settings.orders_path
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ToolError(f"Orders file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ToolError(f"Orders file is not valid JSON ({path}): {exc}") from exc
    if not isinstance(raw, list):
        raise ToolError("Orders file must contain a JSON list of orders.")

    orders: dict[str, dict] = {}
    for rec in raw:
        if isinstance(rec, dict) and rec.get("order_id") and rec.get("email"):
            orders[str(rec["order_id"]).upper()] = rec
        else:
            logger.warning("Skipping malformed order record (needs order_id and email)")
    return orders


def lookup_order(order_id: str, email: str) -> dict | None:
    """Return the order only if the email matches. None for 'no such order' and 'wrong email' alike."""
    order = _orders().get(order_id.strip().upper())
    if order and str(order["email"]).strip().lower() == email.strip().lower():
        return order
    return None


# --------------------------------------------------------------------------- #
# Parsing and policy helpers
# --------------------------------------------------------------------------- #
def extract_order_id(text: str) -> str | None:
    match = ORDER_ID_RE.search(text)
    return match.group(0).upper() if match else None


def extract_email(text: str) -> str | None:
    match = EMAIL_RE.search(text)
    return match.group(0).lower() if match else None


def _mask(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:1]}***@{domain}"  # never log full emails


def _parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        logger.warning("Bad date in orders data: %r", value)
        return None


def _fmt_date(d: date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def _add_months(d: date, months: int) -> date:
    carry, month0 = divmod(d.month - 1 + months, 12)
    year, month = d.year + carry, month0 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def return_deadline(delivered: date) -> date:
    """Last day a delivered order can be returned (see returns.md: 30 days + holiday extension)."""
    if HOLIDAY_START <= (delivered.month, delivered.day) <= HOLIDAY_END:
        return date(delivered.year + 1, *HOLIDAY_RETURN_DEADLINE)
    return delivered + timedelta(days=RETURN_WINDOW_DAYS)


# --------------------------------------------------------------------------- #
# Reply formatting (deterministic: no LLM involved)
# --------------------------------------------------------------------------- #
def _status_lines(order: dict, today: date) -> list[str]:
    status = str(order.get("status", "")).lower()
    items = order.get("items", [])

    if status == "processing":
        return [
            "Status: Processing. We are preparing your order and it ships within 1-2 business days.",
            f"You can still cancel it or change the shipping address while it is Processing. "
            f"Email {SUPPORT_EMAIL} with your order number.",
        ]

    if status == "shipped":
        lines = ["Status: Shipped."]
        shipped = _parse_date(order.get("shipped_date"))
        if order.get("carrier") and shipped:
            lines.append(f"Shipped via {order['carrier']} on {_fmt_date(shipped)}.")
        if order.get("tracking_number"):
            lines.append(f"Tracking number: {order['tracking_number']}")
        eta = _parse_date(order.get("estimated_delivery"))
        if eta:
            lines.append(f"Estimated delivery: {_fmt_date(eta)}.")
        lines.append("It can no longer be cancelled or re-addressed. Once it arrives you can start a return if needed.")
        return lines

    if status == "delivered":
        delivered = _parse_date(order.get("delivered_date"))
        if not delivered:
            return ["Status: Delivered."]
        lines = [f"Status: Delivered on {_fmt_date(delivered)}."]
        deadline = return_deadline(delivered)
        returnable = [i.get("name", "Item") for i in items if not i.get("final_sale")]
        final_sale = [i.get("name", "Item") for i in items if i.get("final_sale")]
        if today <= deadline:
            if returnable:
                lines.append(
                    f"You can return eligible items until {_fmt_date(deadline)} (unworn, in the original shoebox)."
                )
            if final_sale:
                lines.append(
                    f"Final Sale items cannot be returned: {', '.join(final_sale)}. "
                    "A manufacturing defect is still covered by our warranty."
                )
        else:
            lines.append(f"The return window closed on {_fmt_date(deadline)}.")
            warranty_end = _add_months(delivered, WARRANTY_MONTHS)
            if today <= warranty_end:
                lines.append(
                    f"Manufacturing defects are still covered by our warranty until {_fmt_date(warranty_end)}. "
                    f"Email {SUPPORT_EMAIL} with photos of the issue."
                )
            else:
                lines.append("The 12-month warranty period has also ended.")
        return lines

    if status == "cancelled":
        lines = ["Status: Cancelled."]
        if order.get("refund_status") == "refunded":
            lines.append("Your refund was issued to your original payment method.")
        else:
            lines.append(f"If you see a charge for this order, please email {SUPPORT_EMAIL}.")
        return lines

    if status == "return_received":
        lines = ["Status: Return received. Thank you!"]
        due = _parse_date(order.get("refund_expected_by"))
        if order.get("refund_status") == "approved":
            lines.append(
                "Your refund has been approved"
                + (f" and is expected by {_fmt_date(due)}." if due else ".")
            )
        else:
            lines.append("We are inspecting your return. This takes up to 2 business days.")
        return lines

    return [f"Status: {order.get('status', 'unknown')}. Please email {SUPPORT_EMAIL} for details."]


def format_order(order: dict, today: date | None = None) -> str:
    today = today or date.today()
    names = str(order.get("customer_name", "")).split()
    first = names[0] if names else "there"

    items = [
        f"- {i.get('name', 'Item')} ({i.get('size', '?')}) x{i.get('quantity', 1)}"
        + (" [Final Sale]" if i.get("final_sale") else "")
        for i in order.get("items", [])
    ]
    header = f"Hi {first}, here is the status of order {order['order_id']}:"
    # Blank lines between paragraphs so Streamlit's markdown does not merge them into one.
    return "\n\n".join([header, "\n".join(items), *_status_lines(order, today)])


# --------------------------------------------------------------------------- #
# Conversation logic: a tiny state machine
# --------------------------------------------------------------------------- #
def handle_order_message(text: str, flow: OrderFlow | None = None, *, today: date | None = None) -> ToolReply:
    """Decide whether `text` is an order question and, if so, advance the lookup flow."""
    flow = flow or OrderFlow()
    today = today or date.today()
    order_id, email = extract_order_id(text), extract_email(text)
    in_flow = bool(flow.order_id or flow.email)

    if in_flow and not (order_id or email):
        # The customer moved on to another topic: release the flow (keep the failure count).
        return ToolReply(False, flow=OrderFlow(failed=flow.failed), outcome="flow_abandoned")
    if not in_flow and not (order_id or STATUS_INTENT_RE.search(text)):
        return ToolReply(False, flow=flow, outcome="not_order_query")

    if flow.failed >= settings.max_failed_lookups:
        return ToolReply(True, LOCKED, flow, "locked_out")

    order_id = order_id or flow.order_id
    email = email or flow.email
    if not order_id:
        return ToolReply(True, ASK_ORDER_ID, OrderFlow(email=email, failed=flow.failed), "asked_order_id")
    if not email:
        return ToolReply(True, ASK_EMAIL, OrderFlow(order_id=order_id, failed=flow.failed), "asked_email")

    order = lookup_order(order_id, email)
    if order is None:
        failed = flow.failed + 1
        left = settings.max_failed_lookups - failed
        logger.info("Order lookup failed: %s / %s (failure %d)", order_id, _mask(email), failed)
        if left <= 0:
            return ToolReply(True, LOCKED, OrderFlow(failed=failed), "locked_out")
        plural = "attempt" if left == 1 else "attempts"
        return ToolReply(True, f"{NOT_FOUND} ({left} {plural} left.)", OrderFlow(failed=failed), "verification_failed")

    logger.info("Order lookup OK: %s", order_id)
    return ToolReply(True, format_order(order, today), OrderFlow(failed=flow.failed), "found")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Try the DemoKicks order-status tool.")
    parser.add_argument("--today", type=date.fromisoformat, help="pin today's date, e.g. 2026-11-24")
    args = parser.parse_args(argv)
    setup_logging()

    flow = OrderFlow()
    print("Order tool demo. Try: where is my order   (empty line to quit)")
    try:
        while text := input("\nYou: ").strip():
            reply = handle_order_message(text, flow, today=args.today)
            flow = reply.flow
            print(f"\n[{reply.outcome}]")
            print(reply.text if reply.handled else "(not an order question: this would go to the RAG bot)")
    except (EOFError, KeyboardInterrupt):
        print()
    except ToolError as exc:
        logger.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())