"""Verify error-path EvalResult propagates framework_name from backend.

Regression test for the bug where _process_one()'s exception fallback
constructed EvalResult without ``framework=``, causing the dataclass
default of ``"openjarvis"`` to silently mislabel data from foreign
backends (hermes, openclaw) when a task errored before reaching the
happy-path EvalResult construction.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.runner import EvalRunner
from openjarvis.evals.core.scorer import Scorer
from openjarvis.evals.core.types import EvalRecord, RunConfig


class _FailingBackend:
    """Mock backend whose generate_full() always raises."""

    backend_id = "hermes"
    framework_name = "hermes"

    def generate(self, *args: Any, **kwargs: Any) -> str:
        raise RuntimeError("simulated backend failure")

    def generate_full(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        raise RuntimeError("simulated backend failure")

    def close(self) -> None:
        pass


class _SingleRecordDataset(DatasetProvider):
    dataset_id = "mock"
    dataset_name = "mock"

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        pass

    def iter_records(self) -> Iterable[EvalRecord]:
        yield EvalRecord(
            record_id="rec-1",
            problem="Say hi.",
            reference="hi",
            category="chat",
        )

    def size(self) -> int:
        return 1


class _NoopScorer(Scorer):
    scorer_id = "noop"

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        return False, {}


class TestErrorPathFrameworkPropagation:
    def test_failed_task_keeps_backend_framework_name(self, tmp_path: Any) -> None:
        """When the backend raises, EvalResult.framework should still be the
        backend's framework_name, not the dataclass default 'openjarvis'."""
        cfg = RunConfig(
            benchmark="mock",
            backend="hermes",
            model="mock-model",
            max_samples=1,
            max_workers=1,
            output_path=str(tmp_path / "out.jsonl"),
        )
        runner = EvalRunner(
            config=cfg,
            dataset=_SingleRecordDataset(),
            backend=_FailingBackend(),
            scorer=_NoopScorer(),
        )
        runner.run()

        results: List[Any] = runner.results
        assert len(results) == 1
        result = results[0]
        # The KEY assertion: framework must come from backend.framework_name,
        # NOT from the EvalResult dataclass default of "openjarvis".
        assert result.framework == "hermes", (
            f"Expected framework='hermes' (from backend.framework_name), "
            f"got {result.framework!r}"
        )
        assert result.error is not None
        assert "simulated backend failure" in result.error

    def test_default_framework_when_backend_missing_attr(self, tmp_path: Any) -> None:
        """Backends that don't override framework_name should still produce
        a sensible default (the ABC's "openjarvis"), via getattr fallback."""

        class _BackendWithoutFrameworkName:
            backend_id = "legacy"

            def generate(self, *a: Any, **kw: Any) -> str:
                raise RuntimeError("boom")

            def generate_full(self, *a: Any, **kw: Any) -> Dict[str, Any]:
                raise RuntimeError("boom")

            def close(self) -> None:
                pass

        cfg = RunConfig(
            benchmark="mock",
            backend="legacy",
            model="mock-model",
            max_samples=1,
            max_workers=1,
            output_path=str(tmp_path / "out.jsonl"),
        )
        runner = EvalRunner(
            config=cfg,
            dataset=_SingleRecordDataset(),
            backend=_BackendWithoutFrameworkName(),  # type: ignore[arg-type]
            scorer=_NoopScorer(),
        )
        runner.run()

        results = runner.results
        assert len(results) == 1
        # getattr() defensive fallback in the runner kicks in; result keeps
        # the conservative "openjarvis" tag rather than crashing.
        assert results[0].framework == "openjarvis"
        assert results[0].error is not None


class _MockBackendWithCommit:
    """Mock backend that exposes framework_name AND framework_commit_value."""

    backend_id = "hermes"
    framework_name = "hermes"
    framework_commit_value = "abc12345"

    def generate(self, *args: Any, **kwargs: Any) -> str:
        raise RuntimeError("simulated")

    def generate_full(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        raise RuntimeError("simulated")

    def close(self) -> None:
        pass


class TestErrorPathCommitPropagation:
    def test_failed_task_keeps_backend_framework_commit(self, tmp_path: Any) -> None:
        """When the backend raises, EvalResult.framework_commit should be
        the backend's framework_commit_value, not empty."""
        cfg = RunConfig(
            benchmark="mock",
            backend="hermes",
            model="mock-model",
            max_samples=1,
            max_workers=1,
            output_path=str(tmp_path / "out.jsonl"),
        )
        runner = EvalRunner(
            config=cfg,
            dataset=_SingleRecordDataset(),
            backend=_MockBackendWithCommit(),  # type: ignore[arg-type]
            scorer=_NoopScorer(),
        )
        runner.run()
        results = runner.results
        assert len(results) >= 1
        for r in results:
            assert r.framework == "hermes"
            assert r.framework_commit == "abc12345", (
                f"Expected framework_commit='abc12345' "
                f"(from backend.framework_commit_value), "
                f"got {r.framework_commit!r}"
            )
            assert r.error is not None
