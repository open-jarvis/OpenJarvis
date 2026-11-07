"""Tests for the daily_digest scorer."""

from friday_ai.evals.core.types import EvalRecord
from friday_ai.evals.scorers.daily_digest import DailyDigestScorer


def _make_record(must_mention, priority_order=None):
    return EvalRecord(
        record_id="test-dd-1",
        problem="Prepare a daily digest.",
        reference="; ".join(must_mention),
        category="agentic",
        metadata={
            "role": "Engineer",
            "company": "TestCo",
            "must_mention": must_mention,
            "priority_order": priority_order or [],
        },
    )


def test_all_items_mentioned():
    items = ["sprint planning", "PR review", "team lunch"]
    record = _make_record(items, ["sprint planning", "PR review"])
    scorer = DailyDigestScorer()

    answer = (
        "## Priority\n"
        "- **Sprint planning** at 9am — prepare stories\n"
        "- **PR review** for auth module needed\n\n"
        "## Other\n"
        "- Team lunch at noon\n\n"
        "## Action Items\n"
        "- Review sprint backlog before standup"
    )
    is_correct, meta = scorer.score(record, answer)
    assert meta["items_mentioned"] == 3
    assert meta["phrase_score"] == 1.0
    assert is_correct is True


def test_partial_mention():
    items = ["deploy review", "security audit", "team retro"]
    record = _make_record(items)
    scorer = DailyDigestScorer()

    answer = "Today: deploy review at 9am. Team retro at 3pm."
    is_correct, meta = scorer.score(record, answer)
    assert meta["items_mentioned"] == 2
    assert 0.6 <= meta["phrase_score"] <= 0.7


def test_ordering_score():
    items = ["urgent outage", "sprint planning", "lunch"]
    priority = ["urgent outage", "sprint planning"]
    record = _make_record(items, priority)
    scorer = DailyDigestScorer()

    # Priority items first, then less important
    answer = (
        "URGENT: Production outage needs immediate attention. "
        "Sprint planning at 10am to discuss fix.\n\n"
        "Later today: team lunch at noon."
    )
    is_correct, meta = scorer.score(record, answer)
    assert meta["ordering_score"] >= 0.5


def test_empty_answer():
    record = _make_record(["item1", "item2"])
    scorer = DailyDigestScorer()
    is_correct, meta = scorer.score(record, "")
    assert is_correct is False
    assert meta["reason"] == "empty_response"


def test_no_must_mention():
    record = EvalRecord(
        record_id="test-dd-2",
        problem="Prepare digest.",
        reference="",
        category="agentic",
        metadata={"must_mention": [], "priority_order": []},
    )
    scorer = DailyDigestScorer()
    is_correct, meta = scorer.score(record, "Some digest.")
    assert is_correct is None
    assert meta["reason"] == "no_must_mention_items"
