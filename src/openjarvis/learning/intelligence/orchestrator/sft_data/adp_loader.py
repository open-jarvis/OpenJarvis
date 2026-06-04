"""Full-trajectory reader for NeuLab ADP (``neulab/agent-data-collection``).

The eval-side loader (:mod:`openjarvis.evals.datasets.adp`) keeps only
``(problem, reference)`` per row — it drops every intermediate step, which is
exactly the signal the orchestrator needs. This module instead transcribes
**all** turns of a trajectory into a canonical
:class:`~openjarvis.learning.intelligence.orchestrator.types.Episode`.

No GPU / no API keys: we read the demonstrated traces and re-tier them
downstream; we never re-execute a model here.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Iterable, Iterator, List, MutableMapping, Optional

from openjarvis.learning.intelligence.orchestrator.types import (
    Episode,
    OrchestratorAction,
    OrchestratorObservation,
)

HF_DATASET_ID = "neulab/agent-data-collection"
HF_SPLIT = "std"

# Same configs the eval loader concatenates; the meeting steer favours the
# coding / agentic / tool-use ones.
DEFAULT_CONFIGS: tuple[str, ...] = (
    "codeactinstruct",
    "code_feedback",
    "openhands",
    "agenttuning_os",
    "agenttuning_db",
    "swe-smith",
)

# ADP turn ``class_`` values that denote a tool/code action vs. plain message.
_CODE_CLASSES = {"code_action", "ipython_action", "bash_action"}
_SEARCH_CLASSES = {"search_action", "browse_action", "web_action"}
_MESSAGE_CLASSES = {"message_action"}


@dataclass
class CanonicalStep:
    """One transcribed ADP turn: what the demonstration did at this step."""

    kind: str
    """Normalised step kind: ``reason`` | ``code`` | ``search`` | ``message``."""

    content: str
    """The turn's text (the action the demonstration took)."""

    observation: str = ""
    """The environment/tool result that followed, if any."""

    is_final: bool = False
    """Whether this is the trajectory's final answer turn."""


def _parse_content(raw: object) -> List[MutableMapping[str, object]]:
    """Parse the ``content`` field (a list, or a string repr of one)."""
    if isinstance(raw, list):
        return raw  # type: ignore[return-value]
    if isinstance(raw, str):
        try:
            parsed = ast.literal_eval(raw)
            if isinstance(parsed, list):
                return parsed  # type: ignore[return-value]
        except (ValueError, SyntaxError):
            pass
    return []


def _classify(turn: MutableMapping[str, object]) -> str:
    cls = str(turn.get("class_") or "").lower()
    if cls in _CODE_CLASSES:
        return "code"
    if cls in _SEARCH_CLASSES:
        return "search"
    if cls in _MESSAGE_CLASSES:
        return "message"
    return "reason"


def trajectory_rows_to_episode(
    record_id: str,
    turns: List[MutableMapping[str, object]],
) -> Optional[Episode]:
    """Transcribe one ADP trajectory's turns into a canonical ``Episode``.

    The orchestrator-relevant structure is preserved: the first user turn is the
    problem; every subsequent agent turn becomes a step (with its following
    observation, if the trace recorded one). Returns ``None`` if there is no
    usable problem or no agent steps.
    """
    problem: Optional[str] = None
    steps: List[CanonicalStep] = []

    # Group agent turns with the observation/user turn that follows them.
    pending: Optional[CanonicalStep] = None
    for turn in turns:
        source = str(turn.get("source") or "").lower()
        text = str(turn.get("content") or "").strip()
        if not text:
            continue

        if source == "user":
            if problem is None:
                problem = text
            elif pending is not None:
                # A user/environment turn after an agent action = its observation.
                pending.observation = text[:2000]
            continue

        # Agent-sourced turn -> a new step.
        if pending is not None:
            steps.append(pending)
        pending = CanonicalStep(kind=_classify(turn), content=text)

    if pending is not None:
        steps.append(pending)

    if not problem or not steps:
        return None

    steps[-1].is_final = True
    steps[-1].kind = "message" if steps[-1].kind == "reason" else steps[-1].kind

    episode = Episode(
        task_id=record_id,
        initial_prompt=problem,
        ground_truth=steps[-1].content[:2000],
        # ADP rows are demonstrated solutions; treat them as correct teachers.
        correct=True,
    )
    for st in steps:
        episode.add_step(
            OrchestratorAction(
                thought="",  # filled in by the paradigm renderer
                tool_name=st.kind,
                tool_input=st.content,
                is_final_answer=st.is_final,
            ),
            OrchestratorObservation(content=st.observation or st.content),
        )
    episode.final_answer = steps[-1].content[:2000]
    episode.metadata["source"] = "adp"
    return episode


def iter_trajectories(
    *,
    max_tasks: Optional[int] = None,
    configs: Iterable[str] = DEFAULT_CONFIGS,
    min_steps: int = 1,
    max_steps: int = 24,
) -> Iterator[Episode]:
    """Stream canonical ``Episode`` objects from ADP.

    Network is touched lazily inside the loop (``datasets.load_dataset`` with
    ``streaming=True``) so importing this module stays free. Configs that fail
    to load (gated/missing) are skipped.
    """
    from datasets import load_dataset

    emitted = 0
    for cfg in configs:
        if max_tasks is not None and emitted >= max_tasks:
            break
        try:
            stream = load_dataset(HF_DATASET_ID, cfg, split=HF_SPLIT, streaming=True)
        except Exception:
            continue
        for i, row in enumerate(stream):
            if max_tasks is not None and emitted >= max_tasks:
                break
            row = dict(row)  # type: ignore[arg-type]
            turns = _parse_content(row.get("content"))
            row_id = row.get("id")
            rec_id = str(row_id) if row_id is not None else f"{cfg}-{i}"
            episode = trajectory_rows_to_episode(rec_id, turns)
            if episode is None:
                continue
            n = episode.num_turns()
            if n < min_steps or n > max_steps:
                continue
            emitted += 1
            yield episode


__all__ = [
    "CanonicalStep",
    "DEFAULT_CONFIGS",
    "iter_trajectories",
    "trajectory_rows_to_episode",
]
