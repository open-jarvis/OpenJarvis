"""Tests for WildChat scorer (verdict parsing and dual comparison)."""

from __future__ import annotations

from friday_ai.evals.core.types import EvalRecord
from friday_ai.evals.scorers.wildchat_judge import WildChatScorer
from friday_ai.evals.tests.conftest import MockBackend


class TestVerdictParsing:
    def test_verdict_to_bool_generated_is_a(self):
        assert WildChatScorer._verdict_to_bool("A>>B", generated_is_a=True) is True
        assert WildChatScorer._verdict_to_bool("A>B", generated_is_a=True) is True
        assert WildChatScorer._verdict_to_bool("A=B", generated_is_a=True) is True
        assert WildChatScorer._verdict_to_bool("B>A", generated_is_a=True) is False
        assert WildChatScorer._verdict_to_bool("B>>A", generated_is_a=True) is False

    def test_verdict_to_bool_generated_is_b(self):
        assert WildChatScorer._verdict_to_bool("A>>B", generated_is_a=False) is False
        assert WildChatScorer._verdict_to_bool("A>B", generated_is_a=False) is False
        assert WildChatScorer._verdict_to_bool("A=B", generated_is_a=False) is True
        assert WildChatScorer._verdict_to_bool("B>A", generated_is_a=False) is True
        assert WildChatScorer._verdict_to_bool("B>>A", generated_is_a=False) is True

    def test_verdict_none(self):
        assert WildChatScorer._verdict_to_bool(None, generated_is_a=True) is None
        assert WildChatScorer._verdict_to_bool("", generated_is_a=True) is None

    def test_unknown_verdict(self):
        assert WildChatScorer._verdict_to_bool("X>Y", generated_is_a=True) is None


class TestWildChatScorer:
    def _make_record(self, reference="I'm fine, thanks!"):
        return EvalRecord(
            record_id="wc-1",
            problem="How are you?",
            reference=reference,
            category="chat",
            subject="conversation",
        )

    def test_model_wins(self):
        backend = MockBackend()
        # First call: model as A, verdict A>>B (model better)
        # Second call: reference as A, verdict A>>B (reference better → model loses)
        # But since it's OR logic, model wins if either comparison says it's good
        call_count = 0

        def mock_generate(prompt, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return '```json\n{"verdict": "[[A>>B]]"}\n```'
            else:
                return '```json\n{"verdict": "[[A>>B]]"}\n```'

        backend.generate = mock_generate
        scorer = WildChatScorer(backend, "gpt-4o")

        record = self._make_record()
        is_correct, meta = scorer.score(record, "I'm doing great!")

        assert is_correct is True

    def test_model_loses(self):
        backend = MockBackend()
        call_count = 0

        def mock_generate(prompt, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # model as A, reference as B → B wins
                return '```json\n{"verdict": "[[B>>A]]"}\n```'
            else:
                # reference as A, model as B → A wins (reference better)
                return '```json\n{"verdict": "[[A>>B]]"}\n```'

        backend.generate = mock_generate
        scorer = WildChatScorer(backend, "gpt-4o")

        record = self._make_record()
        is_correct, meta = scorer.score(record, "Bad response")

        assert is_correct is False

    def test_tie(self):
        backend = MockBackend()
        backend._default_response = '{"verdict": "[[A=B]]"}'
        scorer = WildChatScorer(backend, "gpt-4o")

        record = self._make_record()
        is_correct, meta = scorer.score(record, "I'm fine, thanks!")

        assert is_correct is True  # Tie counts as correct

    def test_empty_reference(self):
        backend = MockBackend()
        scorer = WildChatScorer(backend, "gpt-4o")

        record = self._make_record("")
        is_correct, meta = scorer.score(record, "Hello")

        assert is_correct is None
        assert meta["reason"] == "empty_reference"

    def test_missing_verdict(self):
        backend = MockBackend()
        backend._default_response = "I cannot decide between them."
        scorer = WildChatScorer(backend, "gpt-4o")

        record = self._make_record()
        is_correct, meta = scorer.score(record, "Hello")

        assert is_correct is None
        assert "missing_verdicts" in str(meta.get("reason", ""))
