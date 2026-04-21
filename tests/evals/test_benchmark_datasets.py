"""Tests for all 15 benchmark dataset and scorer registrations.

These tests verify:
1. Each dataset class can be instantiated
2. Each dataset has correct dataset_id and dataset_name
3. Each scorer class can be constructed (with mock backend)
4. The CLI _build_dataset and _build_scorer factories work for all benchmarks
5. KNOWN_BENCHMARKS in config.py includes all 15 benchmarks
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Dataset instantiation tests
# ---------------------------------------------------------------------------


class TestDatasetInstantiation:
    """Verify each dataset class can be instantiated with correct attributes."""

    def test_supergpqa(self) -> None:
        from openjarvis.evals.datasets.supergpqa import SuperGPQADataset

        ds = SuperGPQADataset()
        assert ds.dataset_id == "supergpqa"
        assert ds.dataset_name == "SuperGPQA"

    def test_gpqa(self) -> None:
        from openjarvis.evals.datasets.gpqa import GPQADataset

        ds = GPQADataset()
        assert ds.dataset_id == "gpqa"
        assert ds.dataset_name == "GPQA"

    def test_mmlu_pro(self) -> None:
        from openjarvis.evals.datasets.mmlu_pro import MMLUProDataset

        ds = MMLUProDataset()
        assert ds.dataset_id == "mmlu-pro"
        assert ds.dataset_name == "MMLU-Pro"

    def test_math500(self) -> None:
        from openjarvis.evals.datasets.math500 import MATH500Dataset

        ds = MATH500Dataset()
        assert ds.dataset_id == "math500"
        assert ds.dataset_name == "MATH-500"

    def test_natural_reasoning(self) -> None:
        from openjarvis.evals.datasets.natural_reasoning import NaturalReasoningDataset

        ds = NaturalReasoningDataset()
        assert ds.dataset_id == "natural-reasoning"
        assert ds.dataset_name == "Natural Reasoning"

    def test_hle(self) -> None:
        from openjarvis.evals.datasets.hle import HLEDataset

        ds = HLEDataset()
        assert ds.dataset_id == "hle"
        assert ds.dataset_name == "HLE"

    def test_simpleqa(self) -> None:
        from openjarvis.evals.datasets.simpleqa import SimpleQADataset

        ds = SimpleQADataset()
        assert ds.dataset_id == "simpleqa"
        assert ds.dataset_name == "SimpleQA"

    def test_wildchat(self) -> None:
        from openjarvis.evals.datasets.wildchat import WildChatDataset

        ds = WildChatDataset()
        assert ds.dataset_id == "wildchat"
        assert ds.dataset_name == "WildChat"

    def test_ipw(self) -> None:
        from openjarvis.evals.datasets.ipw_mixed import IPWDataset

        ds = IPWDataset()
        assert ds.dataset_id == "ipw"
        assert ds.dataset_name == "IPW"

    def test_gaia(self) -> None:
        from openjarvis.evals.datasets.gaia import GAIADataset

        ds = GAIADataset()
        assert ds.dataset_id == "gaia"
        assert ds.dataset_name == "GAIA"

    def test_frames(self) -> None:
        from openjarvis.evals.datasets.frames import FRAMESDataset

        ds = FRAMESDataset()
        assert ds.dataset_id == "frames"
        assert ds.dataset_name == "FRAMES"

    def test_swebench(self) -> None:
        from openjarvis.evals.datasets.swebench import SWEBenchDataset

        ds = SWEBenchDataset()
        assert ds.dataset_id == "swebench"
        assert ds.dataset_name == "SWE-bench"

    def test_swefficiency(self) -> None:
        from openjarvis.evals.datasets.swefficiency import SWEfficiencyDataset

        ds = SWEfficiencyDataset()
        assert ds.dataset_id == "swefficiency"
        assert ds.dataset_name == "SWEfficiency"

    def test_terminalbench(self) -> None:
        from openjarvis.evals.datasets.terminalbench import TerminalBenchDataset

        ds = TerminalBenchDataset()
        assert ds.dataset_id == "terminalbench"
        assert ds.dataset_name == "TerminalBench"

    def test_terminalbench_native(self) -> None:
        from openjarvis.evals.datasets.terminalbench_native import (
            TerminalBenchNativeDataset,
        )

        ds = TerminalBenchNativeDataset()
        assert ds.dataset_id == "terminalbench-native"
        assert ds.dataset_name == "TerminalBench Native"

    def test_livecodebench(self) -> None:
        from openjarvis.evals.datasets.livecodebench import LiveCodeBenchDataset

        ds = LiveCodeBenchDataset()
        assert ds.dataset_id == "livecodebench"
        assert ds.dataset_name == "LiveCodeBench"

    def test_deepresearch(self) -> None:
        from openjarvis.evals.datasets.liveresearch import LiveResearchBenchDataset

        ds = LiveResearchBenchDataset()
        assert ds.dataset_id == "liveresearch"
        assert ds.dataset_name == "DeepResearchBench"

    def test_toolcall15(self) -> None:
        from openjarvis.evals.datasets.toolcall15 import ToolCall15Dataset

        ds = ToolCall15Dataset()
        assert ds.dataset_id == "toolcall15"
        assert ds.dataset_name == "ToolCall-15"


# ---------------------------------------------------------------------------
# Scorer instantiation tests
# ---------------------------------------------------------------------------


def _mock_backend() -> MagicMock:
    """Create a mock inference backend for scorer construction."""
    backend = MagicMock()
    backend.generate.return_value = "A"
    return backend


class TestScorerInstantiation:
    """Verify each scorer class can be constructed."""

    def test_supergpqa_scorer(self) -> None:
        from openjarvis.evals.scorers.supergpqa_mcq import SuperGPQAScorer

        s = SuperGPQAScorer(_mock_backend(), "test-model")
        assert s.scorer_id == "supergpqa"

    def test_gpqa_scorer(self) -> None:
        from openjarvis.evals.scorers.gpqa_mcq import GPQAScorer

        s = GPQAScorer(_mock_backend(), "test-model")
        assert s.scorer_id == "gpqa"

    def test_mmlu_pro_scorer(self) -> None:
        from openjarvis.evals.scorers.mmlu_pro_mcq import MMLUProScorer

        s = MMLUProScorer(_mock_backend(), "test-model")
        assert s.scorer_id == "mmlu-pro"

    def test_reasoning_judge_scorer(self) -> None:
        from openjarvis.evals.scorers.reasoning_judge import ReasoningJudgeScorer

        s = ReasoningJudgeScorer(_mock_backend(), "test-model")
        assert s.scorer_id == "reasoning_judge"

    def test_hle_scorer(self) -> None:
        from openjarvis.evals.scorers.hle_judge import HLEScorer

        s = HLEScorer(_mock_backend(), "test-model")
        assert s.scorer_id == "hle"

    def test_simpleqa_scorer(self) -> None:
        from openjarvis.evals.scorers.simpleqa_judge import SimpleQAScorer

        s = SimpleQAScorer(_mock_backend(), "test-model")
        assert s.scorer_id == "simpleqa"

    def test_wildchat_scorer(self) -> None:
        from openjarvis.evals.scorers.wildchat_judge import WildChatScorer

        s = WildChatScorer(_mock_backend(), "test-model")
        assert s.scorer_id == "wildchat"

    def test_ipw_mixed_scorer(self) -> None:
        from openjarvis.evals.scorers.ipw_mixed import IPWMixedScorer

        s = IPWMixedScorer(_mock_backend(), "test-model")
        assert s.scorer_id == "ipw"

    def test_gaia_scorer(self) -> None:
        from openjarvis.evals.scorers.gaia_exact import GAIAScorer

        s = GAIAScorer(_mock_backend(), "test-model")
        assert s.scorer_id == "gaia"

    def test_frames_scorer(self) -> None:
        from openjarvis.evals.scorers.frames_judge import FRAMESScorer

        s = FRAMESScorer(_mock_backend(), "test-model")
        assert s.scorer_id == "frames"

    def test_swebench_scorer(self) -> None:
        from openjarvis.evals.scorers.swebench_structural import SWEBenchScorer

        s = SWEBenchScorer(_mock_backend(), "test-model")
        assert s.scorer_id == "swebench"

    def test_swefficiency_scorer(self) -> None:
        from openjarvis.evals.scorers.swefficiency_structural import (
            SWEfficiencyScorer,
        )

        s = SWEfficiencyScorer(_mock_backend(), "test-model")
        assert s.scorer_id == "swefficiency"

    def test_terminalbench_scorer(self) -> None:
        from openjarvis.evals.scorers.terminalbench_judge import TerminalBenchScorer

        s = TerminalBenchScorer(_mock_backend(), "test-model")
        assert s.scorer_id == "terminalbench"

    def test_terminalbench_native_scorer(self) -> None:
        from openjarvis.evals.scorers.terminalbench_native_structural import (
            TerminalBenchNativeScorer,
        )

        s = TerminalBenchNativeScorer(_mock_backend(), "test-model")
        assert s.scorer_id == "terminalbench-native"

    def test_livecodebench_scorer(self) -> None:
        from openjarvis.evals.scorers.livecodebench import LiveCodeBenchScorer

        s = LiveCodeBenchScorer(_mock_backend(), "test-model")
        assert s.scorer_id == "livecodebench"

    def test_deepresearch_scorer(self) -> None:
        from openjarvis.evals.scorers.liveresearch import LiveResearchBenchScorer

        s = LiveResearchBenchScorer(_mock_backend(), "test-model")
        assert s.scorer_id == "liveresearch"

    def test_toolcall15_scorer(self) -> None:
        from openjarvis.evals.scorers.toolcall15 import ToolCall15Scorer

        s = ToolCall15Scorer(_mock_backend(), "test-model")
        assert s.scorer_id == "toolcall15"


# ---------------------------------------------------------------------------
# CLI factory tests
# ---------------------------------------------------------------------------


ALL_BENCHMARKS = [
    "supergpqa",
    "gpqa",
    "mmlu-pro",
    "math500",
    "natural-reasoning",
    "hle",
    "simpleqa",
    "wildchat",
    "ipw",
    "gaia",
    "frames",
    "swebench",
    "swefficiency",
    "terminalbench",
    "terminalbench-native",
    "livecodebench",
    "liveresearch",
    "toolcall15",
]


class TestCLIFactories:
    """Verify CLI _build_dataset and _build_scorer work for all benchmarks."""

    @pytest.mark.parametrize("benchmark", ALL_BENCHMARKS)
    def test_build_dataset(self, benchmark: str) -> None:
        from openjarvis.evals.cli import _build_dataset

        ds = _build_dataset(benchmark)
        assert ds is not None
        assert hasattr(ds, "load")
        assert hasattr(ds, "iter_records")
        assert hasattr(ds, "size")

    @pytest.mark.parametrize("benchmark", ALL_BENCHMARKS)
    def test_build_scorer(self, benchmark: str) -> None:
        from openjarvis.evals.cli import _build_scorer

        scorer = _build_scorer(benchmark, _mock_backend(), "test-model")
        assert scorer is not None
        assert hasattr(scorer, "score")

    def test_build_dataset_unknown(self) -> None:
        import click

        from openjarvis.evals.cli import _build_dataset

        with pytest.raises(click.ClickException, match="Unknown benchmark"):
            _build_dataset("nonexistent")

    def test_build_scorer_unknown(self) -> None:
        import click

        from openjarvis.evals.cli import _build_scorer

        with pytest.raises(click.ClickException, match="Unknown benchmark"):
            _build_scorer("nonexistent", _mock_backend(), "test-model")


# ---------------------------------------------------------------------------
# Config KNOWN_BENCHMARKS test
# ---------------------------------------------------------------------------


class TestConfigBenchmarks:
    """Verify KNOWN_BENCHMARKS includes all 15 benchmarks."""

    def test_all_benchmarks_known(self) -> None:
        from openjarvis.evals.core.config import KNOWN_BENCHMARKS

        for b in ALL_BENCHMARKS:
            assert b in KNOWN_BENCHMARKS, f"{b} missing from KNOWN_BENCHMARKS"

    def test_benchmarks_count(self) -> None:
        from openjarvis.evals.core.config import KNOWN_BENCHMARKS

        assert len(KNOWN_BENCHMARKS) == 31


# ---------------------------------------------------------------------------
# Structural scorer tests
# ---------------------------------------------------------------------------


class TestStructuralScorers:
    """Test structural scorers that don't need LLM calls."""

    def test_swebench_empty_response(self) -> None:
        from openjarvis.evals.core.types import EvalRecord
        from openjarvis.evals.scorers.swebench_structural import SWEBenchScorer

        scorer = SWEBenchScorer(_mock_backend(), "test-model")
        record = EvalRecord(
            record_id="swe-1",
            problem="Fix bug",
            reference="patch",
            category="agentic",
        )
        is_correct, meta = scorer.score(record, "")
        assert is_correct is False
        assert meta["reason"] == "empty_response"

    def test_swebench_with_diff(self) -> None:
        from openjarvis.evals.core.types import EvalRecord
        from openjarvis.evals.scorers.swebench_structural import SWEBenchScorer

        scorer = SWEBenchScorer(_mock_backend(), "test-model")
        record = EvalRecord(
            record_id="swe-2",
            problem="Fix bug",
            reference="patch",
            category="agentic",
        )
        answer = "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new"
        is_correct, meta = scorer.score(record, answer)
        assert is_correct is None  # indeterminate
        assert meta["reason"] == "requires_test_execution"
        assert meta["has_diff_markers"] is True

    def test_terminalbench_native_no_results(self) -> None:
        from openjarvis.evals.core.types import EvalRecord
        from openjarvis.evals.scorers.terminalbench_native_structural import (
            TerminalBenchNativeScorer,
        )

        scorer = TerminalBenchNativeScorer(_mock_backend(), "test-model")
        record = EvalRecord(
            record_id="tb-1",
            problem="Run command",
            reference="",
            category="agentic",
        )
        is_correct, meta = scorer.score(record, "some output")
        assert is_correct is None
        assert meta["reason"] == "no_test_results"

    def test_terminalbench_native_resolved(self) -> None:
        from openjarvis.evals.core.types import EvalRecord
        from openjarvis.evals.scorers.terminalbench_native_structural import (
            TerminalBenchNativeScorer,
        )

        scorer = TerminalBenchNativeScorer(_mock_backend(), "test-model")
        record = EvalRecord(
            record_id="tb-2",
            problem="Run command",
            reference="",
            category="agentic",
            metadata={"is_resolved": True},
        )
        is_correct, meta = scorer.score(record, "output")
        assert is_correct is True
