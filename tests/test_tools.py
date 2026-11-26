"""Tests for src/tools.py. Run from the project root:  python -m pytest -q"""
from datetime import date

import pytest

from src import tools

TODAY = date(2026, 11, 24)  # pinned: results never depend on the real clock


def ask(text, flow=None):
    return tools.handle_order_message(text, flow, today=TODAY)


def test_extractors():
    assert tools.extract_order_id("my order dk1002 pls") == "DK1002"
    assert tools.extract_email("it is Ava.Thompson@Example.com.") == "ava.thompson@example.com"
    assert tools.extract_order_id("no id here") is None


def test_return_deadline_follows_policy():
    assert tools.return_deadline(date(2026, 10, 8)) == date(2026, 11, 7)    # 30 days
    assert tools.return_deadline(date(2026, 11, 13)) == date(2027, 1, 31)   # holiday extension
    assert tools.return_deadline(date(2026, 12, 25)) == date(2027, 1, 24)   # just after the holiday window


@pytest.mark.parametrize(
    "order_id, email, expected",
    [
        ("DK1001", "ava.thompson@example.com", "Delivered"),
        ("DK1002", "rahul.mehta@example.com", "Shipped"),
        ("DK1003", "sofia.alvarez@example.com", "Processing"),
        ("DK1004", "liam.oconnor@example.com", "Delivered"),
        ("DK1005", "priya.nair@example.com", "Cancelled"),
        ("DK1006", "noah.williams@example.com", "Return received"),
    ],
)
def test_every_demo_order_is_found(order_id, email, expected):
    reply = ask(f"{order_id} {email}")
    assert reply.outcome == "found" and expected in reply.text


def test_delivered_inside_window_mentions_final_sale():
    text = ask("DK1001 ava.thompson@example.com").text
    assert "Jan 31, 2027" in text and "Final Sale items cannot be returned" in text


def test_delivered_outside_window_points_to_warranty():
    text = ask("DK1004 liam.oconnor@example.com").text
    assert "closed on Nov 7, 2026" in text and "Oct 8, 2027" in text


def test_shipped_shows_tracking_and_eta():
    text = ask("DK1002 rahul.mehta@example.com").text
    assert "DKT100200200" in text and "Nov 25, 2026" in text


def test_wrong_email_and_unknown_order_look_identical():
    wrong_email = ask("DK1001 wrong@example.com")
    unknown_order = ask("DK9999 wrong@example.com")
    assert wrong_email.text == unknown_order.text
    assert "couldn't find" in wrong_email.text


def test_two_step_flow():
    first = ask("where is my order DK1002")
    assert first.outcome == "asked_email" and first.flow.order_id == "DK1002"
    second = ask("rahul.mehta@example.com", first.flow)
    assert second.outcome == "found" and "DKT100200200" in second.text


def test_status_intent_without_id_asks_for_it():
    assert ask("Where's my order?").outcome == "asked_order_id"


def test_lockout_after_repeated_failures():
    flow = tools.OrderFlow()
    for _ in range(3):
        flow = ask("DK1001 wrong@example.com", flow).flow
    assert flow.failed == 3
    assert ask("DK1001 ava.thompson@example.com", flow).outcome == "locked_out"  # even correct creds


def test_topic_change_releases_flow():
    first = ask("track my order DK1003")
    reply = ask("what is your return policy?", first.flow)
    assert not reply.handled and reply.flow.order_id is None


@pytest.mark.parametrize("question", ["Can I cancel my order?", "How long does a refund take?", "Do you ship to Canada?"])
def test_policy_questions_are_not_hijacked(question):
    assert not ask(question).handled