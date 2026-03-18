"""Tests for EvalRunner episode mode."""

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord


class TestDatasetProviderEpisodes:
    def test_default_iter_episodes(self) -> None:
        """Default iter_episodes wraps each record in its own episode."""

        class SimpleDataset(DatasetProvider):
            dataset_id = "test"
            dataset_name = "Test"

            def __init__(self):
                self._records = [
                    EvalRecord("r1", "q1", "a1", "chat"),
                    EvalRecord("r2", "q2", "a2", "chat"),
                ]

            def load(self, **kw):
                pass

            def iter_records(self):
                return iter(self._records)

            def size(self):
                return len(self._records)

        ds = SimpleDataset()
        episodes = list(ds.iter_episodes())
        assert len(episodes) == 2
        assert len(episodes[0]) == 1
        assert episodes[0][0].record_id == "r1"


class TestRunConfigEpisodeMode:
    def test_episode_mode_field(self) -> None:
        from openjarvis.evals.core.types import RunConfig

        cfg = RunConfig(
            benchmark="test",
            backend="test",
            model="test",
            episode_mode=True,
        )
        assert cfg.episode_mode is True

    def test_episode_mode_default_false(self) -> None:
        from openjarvis.evals.core.types import RunConfig

        cfg = RunConfig(benchmark="test", backend="test", model="test")
        assert cfg.episode_mode is False
