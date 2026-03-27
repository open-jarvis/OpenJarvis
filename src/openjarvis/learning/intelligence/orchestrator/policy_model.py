"""Policy model wrapper for orchestrator training.

Adapted from IPW's ``policy.py``.  Wraps a HuggingFace causal LM
(e.g. Qwen3-1.7B) to predict structured actions in the orchestrator
environment.  All ``torch``/``transformers`` imports are guarded so the
module can be imported without GPU dependencies.
"""

from __future__ import annotations

import logging
import re
from typing import Any, List, Optional

from openjarvis.learning.intelligence.orchestrator.types import (
    EpisodeState,
    OrchestratorAction,
    PolicyOutput,
)

# Optional imports -----------------------------------------------------------
try:
    import torch  # noqa: F401

    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    torch = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class OrchestratorPolicyModel:
    """Wrapper around a causal LM for orchestrator policy prediction.

    Input format (prompt)::

        Task: {initial_prompt}

        Available tools: calculator, think, ...

        History:
        Turn 1:
          Thought: ...
          Tool: ...
          Observation: ...

        What should you do next?
        Format your response as:
        THOUGHT: [your reasoning]
        TOOL: [tool_name]
        INPUT: [input for tool]

    Output format (from model)::

        THOUGHT: [reasoning]
        TOOL: [tool_name]
        INPUT: [input]
        --- or ---
        FINAL_ANSWER: [answer]
    """

    def __init__(
        self,
        model: Any = None,
        tokenizer: Any = None,
        max_tokens: int = 256,
        temperature: float = 0.7,
    ) -> None:
        self.model = model
        self.tokenizer = tokenizer
        self.max_tokens = max_tokens
        self.temperature = temperature

    # -- Factory methods -----------------------------------------------------

    @classmethod
    def from_pretrained(
        cls,
        model_name: str = "Qwen/Qwen3-1.7B",
        gradient_checkpointing: bool = False,
        load_in_8bit: bool = False,
        device: Optional[str] = None,
        **kwargs: Any,
    ) -> "OrchestratorPolicyModel":
        """Load model from a HuggingFace checkpoint.

        Raises ``ImportError`` if ``transformers`` is not installed.
        """
        import torch as _torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(model_name)

        model_kwargs: dict[str, Any] = {"torch_dtype": _torch.bfloat16}

        if load_in_8bit:
            try:
                from transformers import BitsAndBytesConfig

                model_kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_8bit=True
                )
            except ImportError as exc:
                logger.debug("FP8 not available, falling back to BF16: %s", exc)

        if device is not None:
            if device == "auto":
                model_kwargs["device_map"] = "auto"
            else:
                model_kwargs["device_map"] = {"": device}

        model = AutoModelForCausalLM.from_pretrained(model_name, **model_kwargs)

        if gradient_checkpointing and hasattr(model, "gradient_checkpointing_enable"):
            model.gradient_checkpointing_enable(
                gradient_checkpointing_kwargs={"use_reentrant": False}
            )

        return cls(model=model, tokenizer=tokenizer, **kwargs)

    @classmethod
    def from_checkpoint(
        cls, checkpoint_path: str, **kwargs: Any
    ) -> "OrchestratorPolicyModel":
        """Load from a previously saved checkpoint directory."""
        return cls.from_pretrained(checkpoint_path, **kwargs)

    # -- Prediction ----------------------------------------------------------

    def predict_action(
        self,
        state: EpisodeState,
        available_tools: List[str],
    ) -> OrchestratorAction:
        """Predict the next action given current state."""
        prompt = self._build_prompt(state, available_tools)

        if self.model is None:
            raise RuntimeError(
                "Cannot generate actions without a loaded model. "
                "Load with OrchestratorPolicyModel.from_pretrained() first."
            )

        output_text = self._generate(prompt)
        policy_output = self._parse_output(output_text, available_tools)
        return OrchestratorAction(
            thought=policy_output.thought,
            tool_name=policy_output.tool_name,
            tool_input=policy_output.tool_input,
            is_final_answer=policy_output.is_final_answer,
        )

    # -- Internal helpers ----------------------------------------------------

    def _build_prompt(
        self,
        state: EpisodeState,
        available_tools: List[str],
    ) -> str:
        """Build the text prompt from current state."""
        parts: list[str] = []

        parts.append(f"Task: {state.initial_prompt}")
        parts.append("")

        tools_str = ", ".join(available_tools)
        parts.append(f"Available tools: {tools_str}")
        parts.append("")

        if state.history:
            parts.append("History:")
            for i, (action, observation) in enumerate(state.history, 1):
                parts.append(f"Turn {i}:")
                parts.append(f"  Thought: {action.thought}")
                parts.append(f"  Tool: {action.tool_name}")
                parts.append(f"  Observation: {observation.content[:100]}...")
                parts.append("")

        parts.append("What should you do next?")
        parts.append("Format your response as:")
        parts.append("THOUGHT: [your reasoning]")
        parts.append("TOOL: [tool_name]")
        parts.append("INPUT: [input for tool]")
        parts.append("")

        return "\n".join(parts)

    def _parse_output(
        self,
        output_text: str,
        available_tools: List[str],
    ) -> PolicyOutput:
        """Parse structured model output into a :class:`PolicyOutput`."""
        # Check for FINAL_ANSWER first
        final_match = re.search(
            r"FINAL[_ ]?ANSWER:\s*(.+?)(?:\n|$)",
            output_text,
            re.IGNORECASE | re.DOTALL,
        )
        if final_match:
            thought_match = re.search(
                r"THOUGHT:\s*(.+?)(?:\n|$)", output_text, re.IGNORECASE
            )
            return PolicyOutput(
                thought=(thought_match.group(1).strip() if thought_match else ""),
                tool_name="",
                tool_input=final_match.group(1).strip(),
                is_final_answer=True,
                raw_text=output_text,
            )

        thought_match = re.search(
            r"THOUGHT:\s*(.+?)(?:\n|$)", output_text, re.IGNORECASE
        )
        tool_match = re.search(r"TOOL:\s*(.+?)(?:\n|$)", output_text, re.IGNORECASE)
        input_match = re.search(
            r"INPUT:\s*(.+?)(?:\nTHOUGHT:|\nTOOL:|\nFINAL|\Z)",
            output_text,
            re.IGNORECASE | re.DOTALL,
        )

        thought = (
            thought_match.group(1).strip() if thought_match else "No thought provided"
        )
        tool_name = (
            tool_match.group(1).strip()
            if tool_match
            else (available_tools[0] if available_tools else "unknown")
        )
        tool_input = input_match.group(1).strip() if input_match else ""

        # Validate / fuzzy-match tool name
        if tool_name not in available_tools:
            tool_name_lower = tool_name.lower()
            matched = False
            for t in available_tools:
                if t.lower() == tool_name_lower:
                    tool_name = t
                    matched = True
                    break
            if not matched:
                tool_name = available_tools[0] if available_tools else "unknown"

        return PolicyOutput(
            thought=thought,
            tool_name=tool_name,
            tool_input=tool_input,
            is_final_answer=False,
            raw_text=output_text,
        )

    def _generate(self, prompt: str) -> str:
        """Generate text from the loaded model."""
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.model.device)
        outputs = self.model.generate(
            **inputs,
            max_new_tokens=self.max_tokens,
            temperature=self.temperature,
            do_sample=True,
        )
        return self.tokenizer.decode(
            outputs[0][len(inputs.input_ids[0]) :],
            skip_special_tokens=True,
        )

    def save(self, path: str) -> None:
        """Save model and tokenizer to *path*."""
        if self.model is not None:
            self.model.save_pretrained(path)
            self.tokenizer.save_pretrained(path)

    def __repr__(self) -> str:
        model_name = "None" if self.model is None else type(self.model).__name__
        return (
            f"OrchestratorPolicyModel(model={model_name}, max_tokens={self.max_tokens})"
        )


__all__ = ["OrchestratorPolicyModel"]
