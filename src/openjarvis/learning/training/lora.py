"""LoRATrainer — fine-tune local models via LoRA/QLoRA from trace-derived SFT pairs.

All ``torch``, ``transformers``, and ``peft`` imports are guarded so the
module can be imported without GPU dependencies.  The :class:`LoRATrainingConfig`
dataclass works without any optional deps; :class:`LoRATrainer` raises
``ImportError`` at construction time when ``torch`` is unavailable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Optional imports -----------------------------------------------------------
try:
    import torch

    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    torch = None  # type: ignore[assignment]

try:
    from transformers import AutoModelForCausalLM, AutoTokenizer

    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False
    AutoModelForCausalLM = None  # type: ignore[assignment,misc]
    AutoTokenizer = None  # type: ignore[assignment,misc]

try:
    from peft import LoraConfig, TaskType, get_peft_model

    HAS_PEFT = True
except ImportError:
    HAS_PEFT = False
    LoraConfig = None  # type: ignore[assignment,misc]
    TaskType = None  # type: ignore[assignment,misc]
    get_peft_model = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Device selection (shared with orchestrator sft_trainer)
# ---------------------------------------------------------------------------


def _select_device(hint: Optional[str] = None) -> str:
    """Select the best available PyTorch device.

    Priority: explicit *hint* > cuda > mps > cpu.
    """
    if hint is not None:
        return hint
    if not HAS_TORCH or torch is None:
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class LoRATrainingConfig:
    """Configuration for LoRA / QLoRA fine-tuning."""

    # LoRA params
    lora_rank: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    target_modules: List[str] = field(default_factory=lambda: ["q_proj", "v_proj"])

    # Training params
    num_epochs: int = 3
    batch_size: int = 4
    learning_rate: float = 2e-5
    weight_decay: float = 0.01
    warmup_ratio: float = 0.1
    max_grad_norm: float = 1.0
    max_seq_length: int = 2048

    # QLoRA
    use_4bit: bool = False

    # Output
    output_dir: str = "checkpoints/lora"
    save_every_n_epochs: int = 1

    # Memory
    gradient_checkpointing: bool = True

    def __post_init__(self) -> None:
        if self.lora_rank < 1:
            raise ValueError(f"lora_rank must be >= 1, got {self.lora_rank}")
        if self.num_epochs < 1:
            raise ValueError(f"num_epochs must be >= 1, got {self.num_epochs}")


# ---------------------------------------------------------------------------
# Trainer
# ---------------------------------------------------------------------------


class LoRATrainer:
    """Fine-tune a local causal LM with LoRA (or QLoRA) adapters.

    Parameters
    ----------
    config:
        LoRA training configuration.
    model_name:
        HuggingFace model identifier or local path.
    device:
        PyTorch device string.  ``None`` auto-detects (cuda > mps > cpu).

    Raises
    ------
    ImportError
        If ``torch`` is not installed.
    """

    def __init__(
        self,
        config: LoRATrainingConfig,
        *,
        model_name: str = "Qwen/Qwen3-0.6B",
        device: Optional[str] = None,
    ) -> None:
        if not HAS_TORCH:
            raise ImportError(
                "torch is required for LoRATrainer. "
                "Install with: pip install torch transformers peft"
            )

        self.config = config
        self.model_name = model_name
        self.device = _select_device(device)
        self.tokenizer: Any = None
        self.model: Any = None

    # -- Public API ----------------------------------------------------------

    def prepare_dataset(self, pairs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert SFT pairs to tokenized examples.

        Each returned dict contains ``input_ids``, ``attention_mask``,
        and ``text`` (the raw formatted string before tokenization).

        Parameters
        ----------
        pairs:
            List of dicts with at least ``input`` and ``output`` keys,
            as produced by :class:`TrainingDataMiner.extract_sft_pairs`.
        """
        self._ensure_tokenizer()

        dataset: List[Dict[str, Any]] = []
        for pair in pairs:
            text = self._format_pair(pair)
            encoding = self.tokenizer(
                text,
                truncation=True,
                max_length=self.config.max_seq_length,
                padding="max_length",
                return_tensors="pt",
            )
            dataset.append(
                {
                    "input_ids": encoding["input_ids"].squeeze(0),
                    "attention_mask": encoding["attention_mask"].squeeze(0),
                    "text": text,
                }
            )

        return dataset

    def train(self, pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Run LoRA fine-tuning on the given SFT pairs.

        Parameters
        ----------
        pairs:
            List of dicts with at least ``input`` and ``output`` keys.

        Returns
        -------
        dict
            Training summary with keys: ``status``, ``epochs``,
            ``total_steps``, ``avg_loss``, ``adapter_path``,
            ``training_samples``.
        """
        if not pairs:
            return {"status": "skipped", "reason": "no training data"}

        dataset = self.prepare_dataset(pairs)
        self._load_model()
        self._apply_lora()

        optimizer = torch.optim.AdamW(
            self.model.parameters(),
            lr=self.config.learning_rate,
            weight_decay=self.config.weight_decay,
        )

        total_steps = 0
        cumulative_loss = 0.0
        num_loss_steps = 0

        self.model.train()

        for epoch in range(self.config.num_epochs):
            epoch_loss = self._train_epoch(dataset, optimizer)
            steps_in_epoch = max(
                1, (len(dataset) + self.config.batch_size - 1) // self.config.batch_size
            )
            total_steps += steps_in_epoch
            cumulative_loss += epoch_loss * steps_in_epoch
            num_loss_steps += steps_in_epoch

            logger.info(
                "Epoch %d/%d  loss=%.4f",
                epoch + 1,
                self.config.num_epochs,
                epoch_loss,
            )

            if (epoch + 1) % self.config.save_every_n_epochs == 0:
                self._save_adapter(epoch + 1)

        avg_loss = cumulative_loss / num_loss_steps if num_loss_steps else 0.0
        adapter_path = str(Path(self.config.output_dir) / "final")
        self._save_adapter_to(adapter_path)

        return {
            "status": "completed",
            "epochs": self.config.num_epochs,
            "total_steps": total_steps,
            "avg_loss": avg_loss,
            "adapter_path": adapter_path,
            "training_samples": len(pairs),
        }

    # -- Internal helpers ----------------------------------------------------

    def _ensure_tokenizer(self) -> None:
        """Lazily load the tokenizer."""
        if self.tokenizer is not None:
            return

        if not HAS_TRANSFORMERS:
            raise ImportError(
                "transformers is required for LoRATrainer. "
                "Install with: pip install transformers"
            )

        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

    def _load_model(self) -> None:
        """Load the base model for fine-tuning."""
        if self.model is not None:
            return

        if not HAS_TRANSFORMERS:
            raise ImportError(
                "transformers is required for LoRATrainer. "
                "Install with: pip install transformers"
            )

        self._ensure_tokenizer()

        model_kwargs: Dict[str, Any] = {"torch_dtype": torch.bfloat16}

        if self.config.use_4bit:
            try:
                from transformers import BitsAndBytesConfig

                model_kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.bfloat16,
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_quant_type="nf4",
                )
            except ImportError:
                logger.warning(
                    "bitsandbytes not installed; falling back to bf16 (QLoRA disabled)"
                )

        if self.device == "cuda" or self.device == "auto":
            model_kwargs["device_map"] = "auto"
        else:
            model_kwargs["device_map"] = {"": self.device}

        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_name, **model_kwargs
        )

        if self.config.gradient_checkpointing and hasattr(
            self.model, "gradient_checkpointing_enable"
        ):
            self.model.gradient_checkpointing_enable(
                gradient_checkpointing_kwargs={"use_reentrant": False}
            )

    def _apply_lora(self) -> None:
        """Wrap the loaded model with LoRA adapters via peft."""
        if not HAS_PEFT:
            raise ImportError(
                "peft is required for LoRA training. Install with: pip install peft"
            )

        lora_config = LoraConfig(
            task_type=TaskType.CAUSAL_LM,
            r=self.config.lora_rank,
            lora_alpha=self.config.lora_alpha,
            lora_dropout=self.config.lora_dropout,
            target_modules=self.config.target_modules,
        )
        self.model = get_peft_model(self.model, lora_config)
        logger.info(
            "LoRA applied: rank=%d, alpha=%d, targets=%s",
            self.config.lora_rank,
            self.config.lora_alpha,
            self.config.target_modules,
        )

    def _format_pair(self, pair: Dict[str, Any]) -> str:
        """Format an SFT pair as a chat-style training string."""
        user_input = pair.get("input", "")
        assistant_output = pair.get("output", "")

        if self.tokenizer is not None and hasattr(
            self.tokenizer, "apply_chat_template"
        ):
            try:
                messages = [
                    {"role": "user", "content": user_input},
                    {"role": "assistant", "content": assistant_output},
                ]
                return self.tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=False
                )
            except Exception as exc:
                logger.debug("Auto chat template failed, using manual format: %s", exc)

        eos = ""
        if self.tokenizer is not None:
            eos = getattr(self.tokenizer, "eos_token", "") or ""
        return f"<|user|>\n{user_input}\n<|assistant|>\n{assistant_output}{eos}"

    def _train_epoch(
        self,
        dataset: List[Dict[str, Any]],
        optimizer: Any,
    ) -> float:
        """Train one epoch over the dataset.  Returns average loss."""
        total_loss = 0.0
        num_batches = 0

        for i in range(0, len(dataset), self.config.batch_size):
            batch_items = dataset[i : i + self.config.batch_size]
            loss = self._train_step(batch_items, optimizer)
            total_loss += loss
            num_batches += 1

        return total_loss / num_batches if num_batches else 0.0

    def _train_step(
        self,
        batch_items: List[Dict[str, Any]],
        optimizer: Any,
    ) -> float:
        """Execute a single training step on a micro-batch."""
        input_ids = torch.stack([item["input_ids"] for item in batch_items]).to(
            self.device
        )
        attention_mask = torch.stack(
            [item["attention_mask"] for item in batch_items]
        ).to(self.device)

        outputs = self.model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            labels=input_ids,
        )
        loss = outputs.loss

        optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(
            self.model.parameters(), self.config.max_grad_norm
        )
        optimizer.step()

        return loss.item()

    def _save_adapter(self, epoch: int) -> None:
        """Save adapter checkpoint for the given epoch."""
        path = str(Path(self.config.output_dir) / f"epoch_{epoch}")
        self._save_adapter_to(path)

    def _save_adapter_to(self, path: str) -> None:
        """Save the LoRA adapter (and tokenizer) to *path*."""
        out = Path(path)
        out.mkdir(parents=True, exist_ok=True)

        if self.model is not None:
            self.model.save_pretrained(path)
        if self.tokenizer is not None:
            self.tokenizer.save_pretrained(path)

        logger.info("Adapter saved to %s", path)


__all__ = [
    "HAS_TORCH",
    "LoRATrainer",
    "LoRATrainingConfig",
]
