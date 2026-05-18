"""Tests for the ACE agent optimizer (mocked — no ace dep required)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


class TestACEOptimizerConfig:
    def test_default_config(self) -> None:
        from openjarvis.core.config import ACEOptimizerConfig

        cfg = ACEOptimizerConfig()
        assert cfg.api_provider == "openai"
        assert cfg.num_epochs == 1
        assert cfg.max_num_rounds == 3
        assert cfg.playbook_token_budget == 80_000
        assert cfg.min_traces == 20

    def test_optimizer_init(self) -> None:
        from openjarvis.core.config import ACEOptimizerConfig
        from openjarvis.learning.agents.ace_optimizer import ACEAgentOptimizer

        cfg = ACEOptimizerConfig()
        optimizer = ACEAgentOptimizer(cfg)
        assert optimizer.config is cfg


class TestTraceDataProcessor:
    def test_answer_is_correct_substring_match(self) -> None:
        from openjarvis.learning.agents.ace_optimizer import _TraceDataProcessor

        assert _TraceDataProcessor.answer_is_correct("the answer is 42", "42")
        assert _TraceDataProcessor.answer_is_correct("FORTY-TWO is right", "forty-two")
        assert not _TraceDataProcessor.answer_is_correct("twelve", "42")

    def test_empty_ground_truth_is_never_correct(self) -> None:
        from openjarvis.learning.agents.ace_optimizer import _TraceDataProcessor

        assert not _TraceDataProcessor.answer_is_correct("anything", "")
        assert not _TraceDataProcessor.answer_is_correct("", "")

    def test_evaluate_accuracy_mean_of_correctness(self) -> None:
        from openjarvis.learning.agents.ace_optimizer import _TraceDataProcessor

        preds = ["the answer is 1", "wrong", "the answer is 3"]
        truths = ["1", "2", "3"]
        # 2 of 3 correct
        assert _TraceDataProcessor.evaluate_accuracy(preds, truths) == 2 / 3

    def test_evaluate_accuracy_empty_returns_zero(self) -> None:
        from openjarvis.learning.agents.ace_optimizer import _TraceDataProcessor

        assert _TraceDataProcessor.evaluate_accuracy([], []) == 0.0


class TestSplitSamples:
    def test_70_15_15_split(self) -> None:
        from openjarvis.learning.agents.ace_optimizer import _split_samples

        samples = [{"i": i} for i in range(100)]
        train, val, test = _split_samples(samples)
        assert len(train) == 70
        assert len(val) == 15
        assert len(test) == 15

    def test_split_is_order_preserving(self) -> None:
        from openjarvis.learning.agents.ace_optimizer import _split_samples

        samples = [{"i": i} for i in range(20)]
        train, val, test = _split_samples(samples)
        assert train[0]["i"] == 0
        assert val[0]["i"] == 14  # 20*0.70 == 14
        assert test[0]["i"] == 17  # 20*0.85 == 17


class TestTracesToSamples:
    def test_drops_empty_query_or_result(self) -> None:
        from openjarvis.learning.agents.ace_optimizer import _traces_to_samples

        traces = [
            MagicMock(query="What is 2+2?", result="4"),
            MagicMock(query="", result="something"),
            MagicMock(query="Q", result=""),
            MagicMock(query=None, result="r"),
            MagicMock(query="Q2", result="A2"),
        ]
        samples = _traces_to_samples(traces)
        assert len(samples) == 2
        assert samples[0] == {"question": "What is 2+2?", "ground_truth_answer": "4"}
        assert samples[1] == {"question": "Q2", "ground_truth_answer": "A2"}


class TestACEOptimizerOptimize:
    def _store_with(self, n: int):
        store = MagicMock()
        store.list_traces.return_value = [
            MagicMock(query=f"Q{i}", result=f"A{i}") for i in range(n)
        ]
        return store

    def test_too_few_traces_skipped(self) -> None:
        from openjarvis.core.config import ACEOptimizerConfig
        from openjarvis.learning.agents.ace_optimizer import ACEAgentOptimizer

        cfg = ACEOptimizerConfig(min_traces=20)
        result = ACEAgentOptimizer(cfg).optimize(self._store_with(5))
        assert result["status"] == "skipped"
        assert "5 traces" in result["reason"]

    def test_missing_ace_dep_returns_error(self) -> None:
        from openjarvis.core.config import ACEOptimizerConfig
        from openjarvis.learning.agents import ace_optimizer

        with patch.object(ace_optimizer, "HAS_ACE", False):
            cfg = ACEOptimizerConfig(min_traces=5)
            result = ace_optimizer.ACEAgentOptimizer(cfg).optimize(
                self._store_with(20)
            )
        assert result["status"] == "error"
        assert "learning-ace" in result["reason"]

    def test_filters_to_usable_samples(self) -> None:
        """If filtering trims samples below min_traces, skip cleanly."""
        from openjarvis.core.config import ACEOptimizerConfig
        from openjarvis.learning.agents import ace_optimizer

        # 20 traces but only 3 have both query+result populated
        store = MagicMock()
        store.list_traces.return_value = [
            MagicMock(query=f"Q{i}" if i < 3 else "", result=f"A{i}" if i < 3 else "")
            for i in range(20)
        ]
        cfg = ACEOptimizerConfig(min_traces=10)
        with patch.object(ace_optimizer, "HAS_ACE", True):
            result = ace_optimizer.ACEAgentOptimizer(cfg).optimize(store)
        assert result["status"] == "skipped"
        assert "3 usable samples" in result["reason"]

    def test_successful_run_returns_playbook_metadata(self, tmp_path: Path) -> None:
        from openjarvis.core.config import ACEOptimizerConfig
        from openjarvis.learning.agents import ace_optimizer

        # Stub ACE: a class whose .run() writes final_playbook.txt.
        playbook_text = "## STRATEGIES\n[str-00001] helpful=5 :: be concise"

        class _FakeACE:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def run(self, **kwargs):
                save_dir = Path(kwargs["config"]["save_dir"])
                (save_dir / "final_playbook.txt").write_text(playbook_text)

        with patch.object(ace_optimizer, "HAS_ACE", True), patch.object(
            ace_optimizer, "ace", MagicMock(ACE=_FakeACE)
        ):
            cfg = ACEOptimizerConfig(
                min_traces=5,
                save_dir=str(tmp_path),
                task_name="unittest",
            )
            result = ace_optimizer.ACEAgentOptimizer(cfg).optimize(
                self._store_with(20)
            )

        assert result["status"] == "completed"
        assert result["traces_used"] == 20
        assert result["samples_used"] == 20
        assert result["playbook_path"].endswith("final_playbook.txt")
        assert result["playbook_chars"] == len(playbook_text)

    def test_ace_completes_without_playbook_surfaces_error(
        self, tmp_path: Path
    ) -> None:
        """ACE returns but doesn't write final_playbook.txt → surface error."""
        from openjarvis.core.config import ACEOptimizerConfig
        from openjarvis.learning.agents import ace_optimizer

        class _SilentACE:
            def __init__(self, **kwargs):
                pass

            def run(self, **kwargs):  # writes nothing
                pass

        with patch.object(ace_optimizer, "HAS_ACE", True), patch.object(
            ace_optimizer, "ace", MagicMock(ACE=_SilentACE)
        ):
            cfg = ACEOptimizerConfig(
                min_traces=5,
                save_dir=str(tmp_path),
            )
            result = ace_optimizer.ACEAgentOptimizer(cfg).optimize(
                self._store_with(20)
            )

        assert result["status"] == "error"
        assert "without writing" in result["reason"]

    def test_ace_raises_returns_error(self, tmp_path: Path) -> None:
        from openjarvis.core.config import ACEOptimizerConfig
        from openjarvis.learning.agents import ace_optimizer

        class _BoomACE:
            def __init__(self, **kwargs):
                pass

            def run(self, **kwargs):
                raise RuntimeError("API key invalid")

        with patch.object(ace_optimizer, "HAS_ACE", True), patch.object(
            ace_optimizer, "ace", MagicMock(ACE=_BoomACE)
        ):
            cfg = ACEOptimizerConfig(
                min_traces=5,
                save_dir=str(tmp_path),
            )
            result = ace_optimizer.ACEAgentOptimizer(cfg).optimize(
                self._store_with(20)
            )

        assert result["status"] == "error"
        assert "API key invalid" in result["reason"]
