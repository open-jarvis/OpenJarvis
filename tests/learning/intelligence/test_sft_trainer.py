"""Tests for the general-purpose SFT trainer."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestSFTTrainerConfig:
    def test_default_config(self) -> None:
        from openjarvis.core.config import SFTConfig

        cfg = SFTConfig()
        assert cfg.model_name == "Qwen/Qwen3-1.7B"
        assert cfg.use_lora is True
        assert cfg.lora_rank == 16
        assert cfg.min_pairs == 10

    def test_trainer_init(self) -> None:
        from openjarvis.core.config import SFTConfig
        from openjarvis.learning.intelligence.sft_trainer import SFTTrainer

        cfg = SFTConfig()
        trainer = SFTTrainer(cfg)
        assert trainer.config is cfg

    def test_target_modules_parsing(self) -> None:
        from openjarvis.core.config import SFTConfig
        from openjarvis.learning.intelligence.sft_trainer import SFTTrainer

        cfg = SFTConfig(target_modules="q_proj,v_proj,k_proj")
        trainer = SFTTrainer(cfg)
        assert trainer.target_module_list == ["q_proj", "v_proj", "k_proj"]


class TestSFTTrainerTrainOnPairs:
    def test_empty_pairs_skipped(self) -> None:
        from openjarvis.core.config import SFTConfig
        from openjarvis.learning.intelligence.sft_trainer import SFTTrainer

        trainer = SFTTrainer(SFTConfig())
        result = trainer.train_on_pairs([])
        assert result["status"] == "skipped"

    def test_too_few_pairs_skipped(self) -> None:
        from openjarvis.core.config import SFTConfig
        from openjarvis.learning.intelligence.sft_trainer import SFTTrainer

        trainer = SFTTrainer(SFTConfig(min_pairs=5))
        pairs = [{"input": "hi", "output": "hello"}]
        result = trainer.train_on_pairs(pairs)
        assert result["status"] == "skipped"
        assert "min_pairs" in result.get("reason", "")


class TestSFTTrainerTraceMining:
    def test_train_delegates_to_miner(self) -> None:
        from openjarvis.core.config import SFTConfig
        from openjarvis.learning.intelligence.sft_trainer import SFTTrainer

        trainer = SFTTrainer(SFTConfig(min_pairs=1))
        mock_store = MagicMock()

        with patch.object(trainer, "_mine_pairs", return_value=[]) as mock_mine:
            result = trainer.train(mock_store)
            mock_mine.assert_called_once_with(mock_store)
            assert result["status"] == "skipped"
