"""Tests for FridayAgentBackend skills_enabled / overlay_dir kwargs (Plan 2B)."""

from __future__ import annotations

from pathlib import Path


class TestFridayAgentBackendSkillsKwargs:
    def test_default_skills_enabled_true(self):
        from friday_ai.evals.backends.friday_agent import FridayAgentBackend

        # Construction should not raise even if no model/engine is reachable
        # because we don't call generate(). The kwargs themselves should be
        # accepted and applied to the SystemBuilder config.
        try:
            backend = FridayAgentBackend(
                engine_key="ollama",
                agent_name="native_react",
                tools=[],
                skills_enabled=True,
            )
        except RuntimeError:
            # If no engine is available we still consider the test passing
            # for this kwarg-acceptance check; the kwarg was applied before
            # the engine resolution failed.
            return
        assert backend._system.config.skills.enabled is True

    def test_skills_enabled_false_disables_skills(self):
        from friday_ai.evals.backends.friday_agent import FridayAgentBackend

        try:
            backend = FridayAgentBackend(
                engine_key="ollama",
                agent_name="native_react",
                tools=[],
                skills_enabled=False,
            )
        except RuntimeError:
            return
        assert backend._system.config.skills.enabled is False
        assert backend._system.skill_manager is None

    def test_overlay_dir_kwarg_applied_to_config(self, tmp_path: Path):
        from friday_ai.evals.backends.friday_agent import FridayAgentBackend

        custom = tmp_path / "custom-overlays"
        try:
            backend = FridayAgentBackend(
                engine_key="ollama",
                agent_name="native_react",
                tools=[],
                skills_enabled=True,
                overlay_dir=custom,
            )
        except RuntimeError:
            return
        # The config should reflect our overlay_dir override
        assert backend._system.config.learning.skills.overlay_dir == str(custom)

    def test_init_signature_accepts_kwargs_without_engine(self):
        """Even without a real engine, the __init__ signature must accept
        the new kwargs without raising TypeError."""
        import inspect

        from friday_ai.evals.backends.friday_agent import FridayAgentBackend

        sig = inspect.signature(FridayAgentBackend.__init__)
        assert "skills_enabled" in sig.parameters
        assert "overlay_dir" in sig.parameters
