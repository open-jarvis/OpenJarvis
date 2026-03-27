"""SFT (Supervised Fine-Tuning) trainer for orchestrator.

Adapted from IPW's ``sft_trainer.py``.  Trains the orchestrator policy
using supervised learning on trajectories.  All ``torch``/``transformers``
imports are guarded so the module can be imported without GPU dependencies.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List

# Optional imports -----------------------------------------------------------
try:
    import torch
    import torch.nn.functional as F  # noqa: F401
    from torch.utils.data import DataLoader

    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    torch = None  # type: ignore[assignment]
    DataLoader = None  # type: ignore[assignment,misc]

from openjarvis.core.registry import LearningRegistry
from openjarvis.learning._stubs import IntelligenceLearningPolicy

logger = logging.getLogger(__name__)


def _select_torch_device():
    """Select the best available PyTorch device (cuda > mps > cpu)."""
    if not HAS_TORCH or torch is None:
        return None
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class OrchestratorSFTConfig:
    """Configuration for orchestrator SFT training."""

    # Model
    model_name: str = "Qwen/Qwen3-1.7B"
    max_seq_length: int = 4096

    # Training
    num_epochs: int = 3
    batch_size: int = 8
    learning_rate: float = 2e-5
    weight_decay: float = 0.01
    warmup_ratio: float = 0.1
    max_grad_norm: float = 1.0

    # Trace generation
    teacher_engine_key: str = ""
    teacher_model: str = ""
    traces_per_query: int = 2
    max_attempts_per_trace: int = 3
    generation_temperature: float = 0.7

    # Data source
    trace_cache_path: str = "data/orchestrator_sft_traces.jsonl"
    regenerate_traces: bool = False

    # Checkpoint
    checkpoint_dir: str = "checkpoints/orchestrator_sft"
    save_every_n_epochs: int = 1

    # Logging
    log_dir: str = "logs/orchestrator_sft"
    log_every_n_steps: int = 10
    use_wandb: bool = False

    # Memory
    gradient_checkpointing: bool = True

    # Available tools for structured prompt
    available_tools: List[str] = field(
        default_factory=lambda: [
            "calculator",
            "think",
            "code_interpreter",
            "web_search",
        ]
    )


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


class OrchestratorSFTDataset:
    """Dataset for SFT training from generated trace JSONL files."""

    def __init__(
        self,
        trace_path: str,
        tokenizer: Any,
        max_seq_length: int = 4096,
    ) -> None:
        self.tokenizer = tokenizer
        self.max_seq_length = max_seq_length
        self.traces: List[Dict[str, Any]] = []
        self._load_traces(trace_path)

    def _load_traces(self, trace_path: str) -> None:
        path = Path(trace_path)
        if not path.exists():
            return
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    self.traces.append(json.loads(line))

    def __len__(self) -> int:
        return len(self.traces)

    def __getitem__(self, idx: int) -> Dict[str, Any]:
        trace = self.traces[idx]
        text = self._format_conversation(trace.get("conversations", []))

        encoding = self.tokenizer(
            text,
            truncation=True,
            max_length=self.max_seq_length,
            padding="max_length",
            return_tensors="pt",
        )

        return {
            "input_ids": encoding["input_ids"].squeeze(0),
            "attention_mask": encoding["attention_mask"].squeeze(0),
            "labels": encoding["input_ids"].squeeze(0).clone(),
        }

    def _format_conversation(self, conversations: List[Dict[str, str]]) -> str:
        """Format conversation turns into training text."""
        if hasattr(self.tokenizer, "apply_chat_template"):
            try:
                messages = []
                for turn in conversations:
                    role = turn.get("role") or turn.get("from", "")
                    content = turn.get("content") or turn.get("value", "")

                    if role in ("human", "user"):
                        role = "user"
                    elif role in ("gpt", "assistant"):
                        role = "assistant"
                    elif role == "tool":
                        tool_name = turn.get("name", "tool")
                        content = f"[Tool '{tool_name}' returned]: {content}"
                        role = "user"

                    if role in ("user", "assistant", "system"):
                        messages.append({"role": role, "content": content})

                return self.tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=False
                )
            except Exception as exc:
                logger.debug("Auto chat template failed, using fallback: %s", exc)

        # Manual fallback
        parts: list[str] = []
        for turn in conversations:
            role = turn.get("role") or turn.get("from", "")
            content = turn.get("content") or turn.get("value", "")

            if role in ("human", "user"):
                parts.append(f"<|user|>\n{content}")
            elif role in ("gpt", "assistant"):
                parts.append(f"<|assistant|>\n{content}")
            elif role == "system":
                parts.append(f"<|system|>\n{content}")
            elif role == "tool":
                tool_name = turn.get("name", "tool")
                parts.append(f"<|user|>\n[Tool '{tool_name}' returned]: {content}")

        eos = getattr(self.tokenizer, "eos_token", "") or ""
        return "\n".join(parts) + eos

    def iter_batches(self, batch_size: int) -> Iterator[List[Dict[str, Any]]]:
        batch: list[Dict[str, Any]] = []
        for i in range(len(self)):
            batch.append(self[i])
            if len(batch) == batch_size:
                yield batch
                batch = []
        if batch:
            yield batch


# ---------------------------------------------------------------------------
# Trainer
# ---------------------------------------------------------------------------


class OrchestratorSFTTrainer:
    """SFT trainer for orchestrator policy.

    Performs standard next-token cross-entropy loss on successful
    trajectories.  ``torch`` must be installed to call :meth:`train`.
    """

    def __init__(self, config: OrchestratorSFTConfig) -> None:
        self.config = config
        self.device = None
        self.global_step = 0

        if HAS_TORCH and torch is not None:
            self.device = _select_torch_device()

        self._init_model()
        self._init_data()
        self._init_optimizer()

    def _init_model(self) -> None:
        from openjarvis.learning.intelligence.orchestrator.policy_model import (
            OrchestratorPolicyModel,
        )

        if not HAS_TORCH:
            self.policy: Any = OrchestratorPolicyModel()
            return

        device_str = str(self.device) if self.device else None
        self.policy = OrchestratorPolicyModel.from_pretrained(
            self.config.model_name,
            gradient_checkpointing=self.config.gradient_checkpointing,
            device=device_str,
        )
        if self.policy.model is not None:
            self.policy.model.train()

    def _init_data(self) -> None:
        trace_path = Path(self.config.trace_cache_path)

        if self.config.regenerate_traces or not trace_path.exists():
            self._generate_traces()

        self.dataset = OrchestratorSFTDataset(
            trace_path=str(trace_path),
            tokenizer=self.policy.tokenizer,
            max_seq_length=self.config.max_seq_length,
        )

    def _generate_traces(self) -> None:
        """Generate SFT traces (placeholder — requires running engine)."""
        trace_path = Path(self.config.trace_cache_path)
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        if not trace_path.exists():
            trace_path.touch()

    def _init_optimizer(self) -> None:
        if not HAS_TORCH or self.policy.model is None:
            self.optimizer: Any = None
            self.scheduler: Any = None
            self.dataloader: Any = None
            return

        self.optimizer = torch.optim.AdamW(
            self.policy.model.parameters(),
            lr=self.config.learning_rate,
            weight_decay=self.config.weight_decay,
        )

        self.dataloader = DataLoader(
            self.dataset,
            batch_size=self.config.batch_size,
            shuffle=True,
            num_workers=0,
        )

        total_steps = len(self.dataloader) * self.config.num_epochs
        warmup_steps = int(total_steps * self.config.warmup_ratio)

        def lr_lambda(step: int) -> float:
            if step < warmup_steps:
                return step / max(1, warmup_steps)
            return max(
                0.0,
                1.0 - (step - warmup_steps) / (total_steps - warmup_steps),
            )

        self.scheduler = torch.optim.lr_scheduler.LambdaLR(self.optimizer, lr_lambda)

    def train(self) -> None:
        """Run the SFT training loop."""
        if not HAS_TORCH:
            raise RuntimeError(
                "PyTorch is required for training. "
                "Install with: pip install torch transformers"
            )

        for epoch in range(self.config.num_epochs):
            self._train_epoch(epoch)

            if (epoch + 1) % self.config.save_every_n_epochs == 0:
                self._save_checkpoint(epoch)

    def _train_epoch(self, epoch: int) -> Dict[str, float]:
        if self.policy.model is None or self.dataloader is None:
            return {"epoch": epoch, "loss": 0.0}

        self.policy.model.train()
        total_loss = 0.0
        num_batches = 0

        for batch in self.dataloader:
            loss = self._train_step(batch)
            total_loss += loss
            num_batches += 1
            self.global_step += 1

        avg_loss = total_loss / num_batches if num_batches > 0 else 0.0
        return {"epoch": epoch, "loss": avg_loss}

    def _train_step(self, batch: Dict[str, Any]) -> float:
        input_ids = batch["input_ids"].to(self.device)
        attention_mask = batch["attention_mask"].to(self.device)
        labels = batch["labels"].to(self.device)

        outputs = self.policy.model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            labels=labels,
        )
        loss = outputs.loss

        self.optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(
            self.policy.model.parameters(),
            self.config.max_grad_norm,
        )
        self.optimizer.step()
        self.scheduler.step()

        return loss.item()

    def _save_checkpoint(self, epoch: int) -> None:
        checkpoint_dir = Path(self.config.checkpoint_dir)
        checkpoint_dir.mkdir(parents=True, exist_ok=True)

        checkpoint_path = checkpoint_dir / f"epoch_{epoch + 1}"
        if self.policy.model is not None:
            self.policy.save(str(checkpoint_path))

            state_path = checkpoint_path / "training_state.json"
            state = {
                "epoch": epoch,
                "global_step": self.global_step,
                "config": asdict(self.config),
            }
            with open(state_path, "w") as f:
                json.dump(state, f, indent=2)


# ---------------------------------------------------------------------------
# Registry wrapper
# ---------------------------------------------------------------------------


def _ensure_registered() -> None:
    if LearningRegistry.contains("orchestrator_sft"):
        return

    @LearningRegistry.register("orchestrator_sft")
    class OrchestratorSFTPolicy(IntelligenceLearningPolicy):
        """Wrapper that registers the SFT trainer as a learning policy."""

        def update(self, trace_store: Any, **kwargs: object) -> Dict[str, Any]:
            config = OrchestratorSFTConfig(
                **{
                    k: v
                    for k, v in kwargs.items()
                    if k in OrchestratorSFTConfig.__dataclass_fields__
                }
            )
            trainer = OrchestratorSFTTrainer(config)
            trainer.train()
            return {"status": "sft_training_complete"}


_ensure_registered()


__all__ = [
    "OrchestratorSFTConfig",
    "OrchestratorSFTDataset",
    "OrchestratorSFTTrainer",
    "_select_torch_device",
]
