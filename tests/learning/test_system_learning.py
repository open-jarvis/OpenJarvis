"""Tests for LearningOrchestrator integration with SystemBuilder."""


class TestSystemLearningIntegration:
    def test_learning_orchestrator_not_created_when_disabled(self):
        """Default config has training_enabled=False, so no orchestrator."""
        from openjarvis.core.config import JarvisConfig
        from openjarvis.system import SystemBuilder

        config = JarvisConfig()
        assert config.learning.training_enabled is False
        result = SystemBuilder._setup_learning_orchestrator(config)
        assert result is None

    def test_learning_orchestrator_created_when_enabled(self):
        """When training_enabled=True, orchestrator is created."""
        from openjarvis.core.config import JarvisConfig
        from openjarvis.learning.learning_orchestrator import LearningOrchestrator
        from openjarvis.system import SystemBuilder

        config = JarvisConfig()
        config.learning.training_enabled = True
        result = SystemBuilder._setup_learning_orchestrator(config)
        assert isinstance(result, LearningOrchestrator)

    def test_config_has_training_fields(self):
        """LearningConfig has the training pipeline fields."""
        from openjarvis.core.config import LearningConfig

        config = LearningConfig()
        assert config.training_enabled is False
        assert config.training_schedule == ""
        assert config.intelligence.sft.lora_rank == 16
        assert config.intelligence.sft.lora_alpha == 32
        assert config.intelligence.sft.min_pairs == 10
        assert config.min_improvement == 0.02

    def test_training_components_exported(self):
        """Learning package exports all training components."""
        from openjarvis.learning import (
            AgentConfigEvolver,
            LearningOrchestrator,
            LoRATrainer,
            TrainingDataMiner,
        )

        assert TrainingDataMiner is not None
        assert LoRATrainer is not None
        assert AgentConfigEvolver is not None
        assert LearningOrchestrator is not None
