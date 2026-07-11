"""Control-token sanitation in the SFT serializer + clean gate.

Regression guard for the leak audit: leaked control/special tokens
(``<|im_end|>``, ``<|tool_call>``, gemma ``<start_of_turn>``/``<end_of_turn>``,
``<|"|>`` …) used to survive into the supervised final answer because the clean
gate only rejected the bare ``<tool_call>`` form. Defense in depth now:

1. ``_final_answer_block`` STRIPS residual control tokens so a good answer with a
   stray token is salvaged (not dropped).
2. ``_target_is_clean`` REJECTS a rollout whose final answer is nothing but
   control tokens, or where a token survives the strip.

Both must leave legitimate ``<``/``>`` in math/code untouched.
"""

from __future__ import annotations

import pytest

from openjarvis.agents.hybrid.toolorchestra.rollout import UnifiedRollout, UnifiedTurn
from openjarvis.learning.intelligence.orchestrator.sft_data.reject_sample import (
    _target_is_clean,
)
from openjarvis.learning.intelligence.orchestrator.sft_data.unified_serialize import (
    _CONTROL_TOKEN_RE,
    _final_answer_block,
    _strip_control_tokens,
)

# --- serializer strips control tokens, leaving a clean FINAL_ANSWER line ------


@pytest.mark.parametrize(
    "raw, expected_answer",
    [
        ("FINAL_ANSWER: 42<end_of_turn>", "42"),
        ("FINAL_ANSWER: 42<|end_of_turn|>", "42"),
        ("FINAL_ANSWER: 42<|im_end|>", "42"),
        ("FINAL_ANSWER: 42<|eot_id|>", "42"),
        ("FINAL_ANSWER: The result<|tool_call>", "The result"),
        ('FINAL_ANSWER: foo <|"|> bar', "foo  bar"),
        ("<start_of_turn>model", "model"),
    ],
)
def test_final_answer_block_strips_tokens(raw: str, expected_answer: str) -> None:
    out = _final_answer_block(raw)
    assert out == f"FINAL_ANSWER: {expected_answer}"
    # No control token survives the serializer.
    assert not _CONTROL_TOKEN_RE.search(out), out


def test_bare_im_end_only_becomes_empty_answer() -> None:
    # An answer that is nothing but a control token strips to empty; the clean
    # gate (below) is what rejects such a rollout.
    assert _final_answer_block("<|im_end|>") == "FINAL_ANSWER: "


def test_math_and_code_angle_brackets_survive() -> None:
    # The narrow regex must NOT eat legitimate comparisons / generics.
    for good in [
        "FINAL_ANSWER: x < 3 and y > 2",
        "FINAL_ANSWER: List<int> and a<b>c",
        "FINAL_ANSWER: if a < b: return a > 0",
    ]:
        out = _final_answer_block(good)
        assert out == good, out
        assert not _CONTROL_TOKEN_RE.search(out)


def test_strip_helper_handles_nested_and_whitespace() -> None:
    assert _strip_control_tokens("  hi <|im_end|>  ") == "hi"
    assert _strip_control_tokens("a<|im_start|>b<|im_end|>c") == "abc"


# --- clean gate: salvage vs reject -------------------------------------------


def _roll(final_answer: str) -> UnifiedRollout:
    """A minimal well-formed rollout (one expert call, clean obs) whose only
    variable is the final answer."""
    return UnifiedRollout(
        turns=[
            UnifiedTurn(
                reasoning="route it",
                tool_name="expert_a",
                arguments={"input": "q"},
                observation="valid observation",
            ),
            UnifiedTurn(reasoning=final_answer, tool_name=None),
        ],
        final_answer=final_answer,
        cost_usd=0.01,
        tokens=10,
        num_tool_calls=1,
        anon_map={"expert_a": "gpt"},
    )


@pytest.mark.parametrize(
    "final_answer, clean",
    [
        # Salvageable: a good answer with a trailing stray token stays clean
        # (the serializer strips the token from the emitted target).
        ("42<end_of_turn>", True),
        ("42<|end_of_turn|>", True),
        ("The result<|tool_call>", True),
        ('foo <|"|> bar', True),
        ("<start_of_turn>model", True),
        ("x < 3 and y > 2", True),
        ("a normal plain answer", True),
        # Unsalvageable: the answer is nothing but a control token -> rejected.
        ("<|im_end|>", False),
        ("<|eot_id|>", False),
        ("<end_of_turn>", False),
        # Bare tool-call tag: already rejected by the existing gate.
        ("<tool_call>{}</tool_call>", False),
    ],
)
def test_clean_gate_salvages_or_rejects(final_answer: str, clean: bool) -> None:
    assert _target_is_clean(_roll(final_answer)) is clean
