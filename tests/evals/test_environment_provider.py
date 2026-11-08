"""Tests for EnvironmentProvider ABC."""

from friday_ai.evals.core.environment import EnvironmentProvider


class _MockEnv(EnvironmentProvider):
    """Concrete implementation for testing."""

    def setup(self):
        return {"url": "http://localhost:8080"}

    def reset(self):
        pass

    def validate(self, record):
        return True, {"status": "ok"}

    def teardown(self):
        pass


class TestEnvironmentProvider:
    def test_concrete_implementation(self) -> None:
        env = _MockEnv()
        info = env.setup()
        assert info["url"] == "http://localhost:8080"

    def test_validate_returns_tuple(self) -> None:
        from friday_ai.evals.core.types import EvalRecord

        env = _MockEnv()
        record = EvalRecord("r1", "problem", "ref", "agentic")
        is_correct, meta = env.validate(record)
        assert is_correct is True
        assert meta["status"] == "ok"

    def test_lifecycle(self) -> None:
        env = _MockEnv()
        env.setup()
        env.reset()
        env.teardown()
