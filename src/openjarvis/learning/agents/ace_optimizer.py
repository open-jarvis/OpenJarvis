"""ACE agent optimizer — context evolution via the ACE Generator /
Reflector / Curator triad.

ACE (`ace-agent/ace <https://github.com/ace-agent/ace>`_) optimizes
agent *context* — an annotated natural-language playbook of strategies
the agent reads at inference time — rather than mutating prompts (DSPy)
or evolving prompt populations (GEPA). The output is a textual
playbook with entries like::

    [str-00001] helpful=5 harmful=0 :: When the user asks for a unit
                                       conversion, prefer the exact
                                       rational form before rounding.

The wrapper adapts OpenJarvis traces into ACE's
``train_samples`` / ``val_samples`` / ``test_samples`` shape, builds a
minimal ``DataProcessor`` from the trace feedback signal, runs ACE in
``offline`` mode, and writes the resulting ``final_playbook.txt`` as a
sidecar overlay under ``~/.openjarvis/learning/ace/<task>/`` for the
agent runtime to pick up on next start.

ACE is not on PyPI as of v1.0.1. The ``learning-ace`` extra installs
from the upstream git repo; if the import fails we surface a
``status="error"`` with the install hint.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from openjarvis.core.config import ACEOptimizerConfig
from openjarvis.core.paths import get_config_dir
from openjarvis.core.registry import LearningRegistry
from openjarvis.learning._stubs import AgentLearningPolicy

logger = logging.getLogger(__name__)

# Optional dependency — ACE is git-installed via the `learning-ace`
# extra. When missing we still expose the optimizer class so callers
# can introspect ``HAS_ACE``; only ``optimize()`` requires the package.
try:
    import ace  # type: ignore[import-not-found]

    HAS_ACE = True
except ImportError:
    HAS_ACE = False
    ace = None  # type: ignore[assignment]


def _default_save_dir(task_name: str) -> Path:
    return get_config_dir() / "learning" / "ace" / task_name


class _TraceDataProcessor:
    """Adapter that exposes OpenJarvis traces in ACE's three-method API.

    ACE expects a processor with:

    - ``process_task_data(raw)`` — normalize a single sample
    - ``answer_is_correct(pred, truth)`` — per-sample comparison
    - ``evaluate_accuracy(preds, truths)`` — aggregate metric over a list

    We treat each trace as a ``{question, ground_truth_answer}`` pair
    and use the recorded ``feedback`` (0.0–1.0) as the ground truth
    when no explicit answer is available. ``answer_is_correct`` does a
    case-insensitive substring match; aggregate accuracy is the mean
    of per-sample correctness.
    """

    @staticmethod
    def process_task_data(raw: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "question": raw.get("question", ""),
            "ground_truth_answer": raw.get("ground_truth_answer", ""),
        }

    @staticmethod
    def answer_is_correct(predicted: str, ground_truth: str) -> bool:
        if not ground_truth:
            return False
        return ground_truth.strip().lower() in (predicted or "").strip().lower()

    @classmethod
    def evaluate_accuracy(
        cls, predictions: List[str], ground_truths: List[str]
    ) -> float:
        if not predictions:
            return 0.0
        n_correct = sum(
            1 for p, g in zip(predictions, ground_truths) if cls.answer_is_correct(p, g)
        )
        return n_correct / len(predictions)


def _traces_to_samples(traces: List[Any]) -> List[Dict[str, Any]]:
    """Convert OpenJarvis trace records to ACE's sample dict shape."""
    samples: List[Dict[str, Any]] = []
    for t in traces:
        question = getattr(t, "query", "") or ""
        answer = getattr(t, "result", "") or ""
        if not question or not answer:
            continue
        samples.append(
            {
                "question": question,
                "ground_truth_answer": answer,
            }
        )
    return samples


def _split_samples(
    samples: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """70/15/15 train/val/test split, preserving order for reproducibility."""
    n = len(samples)
    train_end = int(n * 0.70)
    val_end = int(n * 0.85)
    return samples[:train_end], samples[train_end:val_end], samples[val_end:]


class ACEAgentOptimizer:
    """Optimize an agent's playbook context using ACE.

    Parameters
    ----------
    config:
        :class:`ACEOptimizerConfig` controlling models, run length, and
        output location.
    """

    def __init__(self, config: ACEOptimizerConfig) -> None:
        self.config = config

    def optimize(self, trace_store: Any) -> Dict[str, Any]:
        """Run ACE offline-mode optimization on traces from the store.

        Returns a status dict mirroring DSPy / GEPA shape:
        ``{"status": "completed" | "skipped" | "error", ...}``.
        """
        kwargs: Dict[str, Any] = {"limit": 10_000}
        if self.config.agent_filter:
            kwargs["agent"] = self.config.agent_filter
        traces = trace_store.list_traces(**kwargs)

        if len(traces) < self.config.min_traces:
            return {
                "status": "skipped",
                "reason": (
                    f"only {len(traces)} traces, min_traces={self.config.min_traces}"
                ),
            }

        if not HAS_ACE:
            return {
                "status": "error",
                "reason": (
                    "ace not installed (pip install 'openjarvis[learning-ace]')"
                ),
            }

        samples = _traces_to_samples(traces)
        if len(samples) < self.config.min_traces:
            return {
                "status": "skipped",
                "reason": (
                    f"only {len(samples)} usable samples after filtering "
                    f"(min={self.config.min_traces})"
                ),
            }

        train, val, test = _split_samples(samples)
        save_dir = Path(
            self.config.save_dir or _default_save_dir(self.config.task_name)
        )
        save_dir.mkdir(parents=True, exist_ok=True)

        try:
            ace_system = ace.ACE(  # type: ignore[union-attr]
                api_provider=self.config.api_provider,
                generator_model=self.config.generator_model,
                reflector_model=self.config.reflector_model,
                curator_model=self.config.curator_model,
                max_tokens=self.config.max_tokens,
            )
            ace_system.run(
                mode="offline",
                train_samples=train,
                val_samples=val,
                test_samples=test,
                data_processor=_TraceDataProcessor(),
                config={
                    "num_epochs": self.config.num_epochs,
                    "max_num_rounds": self.config.max_num_rounds,
                    "eval_steps": self.config.eval_steps,
                    "playbook_token_budget": self.config.playbook_token_budget,
                    "task_name": self.config.task_name,
                    "save_dir": str(save_dir),
                    "api_provider": self.config.api_provider,
                },
            )
        except Exception as exc:
            logger.warning("ACE optimization failed: %s", exc)
            return {"status": "error", "reason": str(exc)}

        playbook_path = save_dir / "final_playbook.txt"
        if not playbook_path.exists():
            # ACE completed but didn't write the expected artifact — surface
            # so the user can diagnose without trusting a silent zero.
            return {
                "status": "error",
                "reason": (
                    f"ACE finished without writing {playbook_path}; "
                    "check ACE logs in save_dir"
                ),
            }

        playbook = playbook_path.read_text(encoding="utf-8")
        return {
            "status": "completed",
            "traces_used": len(traces),
            "samples_used": len(samples),
            "playbook_path": str(playbook_path),
            "playbook_chars": len(playbook),
            "save_dir": str(save_dir),
        }


@LearningRegistry.register("ace")
class _ACELearningPolicy(AgentLearningPolicy):
    """Wrapper to register :class:`ACEAgentOptimizer` in LearningRegistry."""

    def __init__(self, **kwargs: object) -> None:
        pass

    def update(self, trace_store: Any, **kwargs: object) -> Dict[str, Any]:
        config = ACEOptimizerConfig()
        optimizer = ACEAgentOptimizer(config)
        return optimizer.optimize(trace_store)


__all__ = ["ACEAgentOptimizer", "HAS_ACE"]
