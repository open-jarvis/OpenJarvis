"""Tests for the 5 use-case benchmark datasets and scorers.

Tests verify:
1. Each dataset can be instantiated with correct attributes
2. Each dataset loads synthetic records (no HuggingFace download)
3. Records have expected fields
4. Each scorer can be instantiated
5. Coding task scorer can score a correct answer
6. Email triage scorer handles exact match
7. CLI factory functions work for all 5 benchmarks
8. Cost calculator and savings modules work
"""

from __future__ import annotations

from unittest.mock import MagicMock  # noqa: I001

import pytest

# ---------------------------------------------------------------------------
# Dataset instantiation and loading
# ---------------------------------------------------------------------------


class TestEmailTriageDataset:
    def test_instantiation(self) -> None:
        from openjarvis.evals.datasets.email_triage import EmailTriageDataset

        ds = EmailTriageDataset()
        assert ds.dataset_id == "email_triage"
        assert ds.dataset_name == "Email Triage"

    def test_load(self) -> None:
        from openjarvis.evals.datasets.email_triage import EmailTriageDataset

        ds = EmailTriageDataset()
        ds.load(max_samples=5, seed=42)
        assert ds.size() == 5
        records = list(ds.iter_records())
        assert len(records) == 5
        r = records[0]
        assert r.record_id.startswith("email-triage-")
        assert r.category == "use-case"
        assert "urgency" in r.metadata
        assert "category" in r.metadata

    def test_load_all(self) -> None:
        from openjarvis.evals.datasets.email_triage import EmailTriageDataset

        ds = EmailTriageDataset()
        ds.load()
        assert ds.size() == 30


class TestMorningBriefDataset:
    def test_instantiation(self) -> None:
        from openjarvis.evals.datasets.morning_brief import MorningBriefDataset

        ds = MorningBriefDataset()
        assert ds.dataset_id == "morning_brief"
        assert ds.dataset_name == "Morning Brief"

    def test_load(self) -> None:
        from openjarvis.evals.datasets.morning_brief import MorningBriefDataset

        ds = MorningBriefDataset()
        ds.load(max_samples=5, seed=42)
        assert ds.size() == 5
        records = list(ds.iter_records())
        r = records[0]
        assert r.record_id.startswith("morning-brief-")
        assert r.reference  # key_priorities not empty

    def test_load_all(self) -> None:
        from openjarvis.evals.datasets.morning_brief import MorningBriefDataset

        ds = MorningBriefDataset()
        ds.load()
        assert ds.size() == 15


class TestResearchMiningDataset:
    def test_instantiation(self) -> None:
        from openjarvis.evals.datasets.research_mining import ResearchMiningDataset

        ds = ResearchMiningDataset()
        assert ds.dataset_id == "research_mining"
        assert ds.dataset_name == "Research Mining"

    def test_load(self) -> None:
        from openjarvis.evals.datasets.research_mining import ResearchMiningDataset

        ds = ResearchMiningDataset()
        ds.load(max_samples=5, seed=42)
        assert ds.size() == 5
        records = list(ds.iter_records())
        r = records[0]
        assert r.record_id.startswith("research-mining-")
        assert "domain" in r.metadata

    def test_load_all(self) -> None:
        from openjarvis.evals.datasets.research_mining import ResearchMiningDataset

        ds = ResearchMiningDataset()
        ds.load()
        assert ds.size() == 31


class TestKnowledgeBaseDataset:
    def test_instantiation(self) -> None:
        from openjarvis.evals.datasets.knowledge_base import KnowledgeBaseDataset

        ds = KnowledgeBaseDataset()
        assert ds.dataset_id == "knowledge_base"
        assert ds.dataset_name == "Knowledge Base"

    def test_load(self) -> None:
        from openjarvis.evals.datasets.knowledge_base import KnowledgeBaseDataset

        ds = KnowledgeBaseDataset()
        ds.load(max_samples=5, seed=42)
        assert ds.size() == 5
        records = list(ds.iter_records())
        r = records[0]
        assert r.record_id.startswith("knowledge-base-")
        assert r.reference  # answer not empty

    def test_load_all(self) -> None:
        from openjarvis.evals.datasets.knowledge_base import KnowledgeBaseDataset

        ds = KnowledgeBaseDataset()
        ds.load()
        assert ds.size() == 30


class TestCodingTaskDataset:
    def test_instantiation(self) -> None:
        from openjarvis.evals.datasets.coding_task import CodingTaskDataset

        ds = CodingTaskDataset()
        assert ds.dataset_id == "coding_task"
        assert ds.dataset_name == "Coding Task"

    def test_load(self) -> None:
        from openjarvis.evals.datasets.coding_task import CodingTaskDataset

        ds = CodingTaskDataset()
        ds.load(max_samples=5, seed=42)
        assert ds.size() == 5
        records = list(ds.iter_records())
        r = records[0]
        assert r.record_id.startswith("coding-task-")
        assert "test_cases" in r.metadata
        assert "signature" in r.metadata

    def test_load_all(self) -> None:
        from openjarvis.evals.datasets.coding_task import CodingTaskDataset

        ds = CodingTaskDataset()
        ds.load()
        assert ds.size() == 29


# ---------------------------------------------------------------------------
# Scorer instantiation
# ---------------------------------------------------------------------------


class TestScorerInstantiation:
    def _mock_backend(self):
        return MagicMock()

    def test_email_triage_scorer(self) -> None:
        from openjarvis.evals.scorers.email_triage import EmailTriageScorer

        scorer = EmailTriageScorer(self._mock_backend(), "gpt-5-mini")
        assert scorer.scorer_id == "email_triage"

    def test_morning_brief_scorer(self) -> None:
        from openjarvis.evals.scorers.morning_brief import MorningBriefScorer

        scorer = MorningBriefScorer(self._mock_backend(), "gpt-5-mini")
        assert scorer.scorer_id == "morning_brief"

    def test_research_mining_scorer(self) -> None:
        from openjarvis.evals.scorers.research_mining import ResearchMiningScorer

        scorer = ResearchMiningScorer(self._mock_backend(), "gpt-5-mini")
        assert scorer.scorer_id == "research_mining"

    def test_knowledge_base_scorer(self) -> None:
        from openjarvis.evals.scorers.knowledge_base import KnowledgeBaseScorer

        scorer = KnowledgeBaseScorer(self._mock_backend(), "gpt-5-mini")
        assert scorer.scorer_id == "knowledge_base"

    def test_coding_task_scorer(self) -> None:
        from openjarvis.evals.scorers.coding_task import CodingTaskScorer

        scorer = CodingTaskScorer(self._mock_backend(), "gpt-5-mini")
        assert scorer.scorer_id == "coding_task"


# ---------------------------------------------------------------------------
# Scorer functional tests
# ---------------------------------------------------------------------------


class TestCodingTaskScoring:
    """Test the coding task scorer with actual code execution."""

    def test_correct_answer(self) -> None:
        from openjarvis.evals.core.types import EvalRecord
        from openjarvis.evals.scorers.coding_task import CodingTaskScorer

        scorer = CodingTaskScorer()
        record = EvalRecord(
            record_id="test-1",
            problem="Write is_palindrome",
            reference="",
            category="use-case",
            subject="coding_task",
            metadata={
                "test_cases": (
                    'assert is_palindrome("racecar") == True\n'
                    'assert is_palindrome("hello") == False\n'
                    'assert is_palindrome("") == True'
                ),
            },
        )
        answer = "def is_palindrome(s):\n    return s == s[::-1]"
        is_correct, meta = scorer.score(record, answer)
        assert is_correct is True
        assert meta["tests_passed"] == 3
        assert meta["pass_rate"] == 1.0

    def test_incorrect_answer(self) -> None:
        from openjarvis.evals.core.types import EvalRecord
        from openjarvis.evals.scorers.coding_task import CodingTaskScorer

        scorer = CodingTaskScorer()
        record = EvalRecord(
            record_id="test-2",
            problem="Write add",
            reference="",
            category="use-case",
            metadata={
                "test_cases": ("assert add(1, 2) == 3\nassert add(0, 0) == 0"),
            },
        )
        # Wrong implementation
        answer = "def add(a, b):\n    return a * b"
        is_correct, meta = scorer.score(record, answer)
        assert is_correct is False

    def test_empty_answer(self) -> None:
        from openjarvis.evals.core.types import EvalRecord
        from openjarvis.evals.scorers.coding_task import CodingTaskScorer

        scorer = CodingTaskScorer()
        record = EvalRecord(
            record_id="test-3",
            problem="Write something",
            reference="",
            category="use-case",
            metadata={"test_cases": "assert True"},
        )
        is_correct, meta = scorer.score(record, "")
        assert is_correct is False
        assert meta["reason"] == "empty_response"


class TestEmailTriageScoring:
    """Test exact-match path of email triage scorer."""

    def test_exact_match(self) -> None:
        from openjarvis.evals.core.types import EvalRecord
        from openjarvis.evals.scorers.email_triage import EmailTriageScorer

        scorer = EmailTriageScorer(MagicMock(), "gpt-5-mini")
        record = EvalRecord(
            record_id="test-1",
            problem="...",
            reference="urgency: high\ncategory: action",
            category="use-case",
            metadata={"urgency": "high", "category": "action"},
        )
        answer = "urgency: high\ncategory: action\ndraft: I'll look into this."
        is_correct, meta = scorer.score(record, answer)
        assert is_correct is True
        assert meta["match_type"] == "exact"


# ---------------------------------------------------------------------------
# CLI factory tests
# ---------------------------------------------------------------------------


class TestCLIFactories:
    """Test that _build_dataset and _build_scorer work for new benchmarks."""

    @pytest.mark.parametrize(
        "benchmark",
        [
            "email_triage",
            "morning_brief",
            "research_mining",
            "knowledge_base",
            "coding_task",
        ],
    )
    def test_build_dataset(self, benchmark: str) -> None:
        from openjarvis.evals.cli import _build_dataset

        ds = _build_dataset(benchmark)
        assert ds.dataset_id == benchmark

    @pytest.mark.parametrize(
        "benchmark",
        [
            "email_triage",
            "morning_brief",
            "research_mining",
            "knowledge_base",
            "coding_task",
        ],
    )
    def test_build_scorer(self, benchmark: str) -> None:
        from openjarvis.evals.cli import _build_scorer

        scorer = _build_scorer(benchmark, MagicMock(), "gpt-5-mini")
        assert scorer.scorer_id == benchmark


# ---------------------------------------------------------------------------
# Cost calculator tests
# ---------------------------------------------------------------------------


class TestCostCalculator:
    """Test the cost calculator module."""

    def test_estimate_monthly_cost(self) -> None:
        from openjarvis.server.cost_calculator import estimate_monthly_cost

        est = estimate_monthly_cost(
            calls_per_month=1000,
            avg_input_tokens=500,
            avg_output_tokens=200,
            provider_key="gpt-5.3",
        )
        assert est.monthly_cost > 0
        assert est.annual_cost == est.monthly_cost * 12
        assert est.total_calls_per_month == 1000

    def test_estimate_scenario(self) -> None:
        from openjarvis.server.cost_calculator import estimate_scenario

        estimates = estimate_scenario("daily_briefing")
        assert len(estimates) == 3  # 3 cloud providers
        for est in estimates:
            assert est.monthly_cost > 0

    def test_estimate_all_scenarios(self) -> None:
        from openjarvis.server.cost_calculator import estimate_all_scenarios

        all_est = estimate_all_scenarios()
        assert len(all_est) == 5  # 5 scenarios

    def test_unknown_provider(self) -> None:
        from openjarvis.server.cost_calculator import estimate_monthly_cost

        with pytest.raises(ValueError, match="Unknown provider"):
            estimate_monthly_cost(100, 100, 100, "nonexistent")

    def test_unknown_scenario(self) -> None:
        from openjarvis.server.cost_calculator import estimate_scenario

        with pytest.raises(ValueError, match="Unknown scenario"):
            estimate_scenario("nonexistent")


# ---------------------------------------------------------------------------
# Savings module tests
# ---------------------------------------------------------------------------


class TestSavings:
    """Test the savings computation module."""

    def test_compute_savings_basic(self) -> None:
        from openjarvis.server.savings import compute_savings

        summary = compute_savings(1000, 500, total_calls=10)
        assert summary.total_calls == 10
        assert summary.total_tokens == 1500
        assert summary.local_cost == 0.0
        assert len(summary.per_provider) == 3
        for p in summary.per_provider:
            assert p.total_cost > 0

    def test_compute_savings_with_session(self) -> None:
        import time

        from openjarvis.server.savings import compute_savings

        start = time.time() - 3600  # 1 hour ago
        summary = compute_savings(
            100000,
            50000,
            total_calls=100,
            session_start=start,
        )
        assert summary.session_duration_hours > 0
        assert summary.monthly_projection  # not empty

    def test_savings_to_dict(self) -> None:
        from openjarvis.server.savings import compute_savings, savings_to_dict

        summary = compute_savings(1000, 500, total_calls=5)
        d = savings_to_dict(summary)
        assert isinstance(d, dict)
        assert "per_provider" in d
        assert "total_calls" in d

    def test_energy_scales_linearly(self) -> None:
        """Energy should scale linearly with evaluated tokens (KV-cache model)."""
        from openjarvis.server.savings import compute_savings

        s1 = compute_savings(1000, 0)
        s10 = compute_savings(10000, 0)
        # FLOPs = 2*P*T (linear), so 10x tokens => 10x FLOPs => 10x energy
        for p1, p10 in zip(s1.per_provider, s10.per_provider):
            ratio = p10.energy_wh / p1.energy_wh
            assert 9 < ratio < 11, (
                f"{p1.provider}: energy ratio {ratio:.1f}, expected ~10"
            )

    def test_energy_wh_matches_direct_formula(self) -> None:
        """Energy must equal flops * wh_per_flop for known constants."""
        from openjarvis.server.savings import CLOUD_PRICING, compute_savings

        summary = compute_savings(10000, 0)
        for p in summary.per_provider:
            pricing = CLOUD_PRICING[p.provider]
            wh_per_flop = pricing["energy_wh_per_1k_tokens"] / (
                1000 * pricing.get("flops_per_token", 3e12)
            )
            expected = p.flops * wh_per_flop
            assert abs(p.energy_wh - expected) < 1e-6, (
                f"{p.provider}: energy_wh={p.energy_wh}, expected={expected}"
            )

    def test_energy_not_zero(self) -> None:
        """Energy must be positive for non-zero token counts."""
        from openjarvis.server.savings import compute_savings

        summary = compute_savings(500, 500)
        for p in summary.per_provider:
            assert p.energy_wh > 0, f"{p.provider}: energy_wh should be > 0"
