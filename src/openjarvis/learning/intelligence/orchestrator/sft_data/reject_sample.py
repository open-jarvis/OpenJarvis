"""Rejection-sampling SFT-data generator (the ToolOrchestra cold-start).

For each ToolScale task: roll out a teacher orchestrator N times, verify each
trajectory, keep the passing ones (optionally just the cheapest), and serialize
them into the unified-tool ``conversations`` JSONL the SFT trainer consumes.

The expensive/network parts are injected so the orchestration is pure and
offline-testable:

* ``rollout_fn(task) -> UnifiedRollout`` — one teacher rollout (temperature>0).
* ``verify_fn(task, rollout) -> bool``   — did the trajectory solve the task?

:func:`gold_coverage_verify` is a dependency-free default verifier (checks the
trajectory's tool calls cover the task's golden action names); a real run should
compose it with an LLM judge on the final answer.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional

from openjarvis.agents.hybrid.expert_registry import ExpertTool
from openjarvis.agents.hybrid.toolorchestra.rollout import UnifiedRollout
from openjarvis.learning.intelligence.orchestrator.sft_data.unified_serialize import (
    _CONTROL_TOKEN_RE,
    _strip_control_tokens,
    trajectory_to_record,
)

logger = logging.getLogger(__name__)

# The sampler only touches ``task.task_id`` / ``task.instruction`` / ``task.domain``
# (via ``trajectory_to_record``), so any task dataclass works — ToolScaleTask or the
# reasoning ``datasets.Task``. ``gold_coverage_verify`` additionally needs
# ``gold_action_names()`` (ToolScale-only), but callers using ``datasets.Task`` pass
# their own ``verify_fn`` (e.g. ``verify.make_verifier()``) instead.
TaskLike = Any
RolloutFn = Callable[[TaskLike], Optional[UnifiedRollout]]
VerifyFn = Callable[[TaskLike, UnifiedRollout], bool]

# Human-readable blurb for each source dataset, stamped onto every record as
# ``dataset_description`` so a row is self-describing (what corpus the question
# came from) without a lookup. Keyed on the record's ``dataset`` value.
DATASET_DESCRIPTIONS = {
    "GeneralThought": (
        "natolambert/GeneralThought-430K-filtered — filtered reasoning Q&A from "
        "gr.inc; each item has a question and a short reference (gold) answer "
        "distilled from DeepSeek-R1 traces."
    ),
    "OpenThoughts3": (
        "open-thoughts/OpenThoughts3-1.2M — code/math/science reasoning tasks; "
        "the gold answer is extracted from the boxed final solution."
    ),
}


def dataset_description(dataset: str) -> str:
    """Blurb for a source dataset name (empty string if unknown)."""
    return DATASET_DESCRIPTIONS.get((dataset or "").strip(), "")


# Markers of a broken expert/observation that must never become a training
# target (empty turns, tracebacks, truncated tool errors, dead-provider strings).
_ERR_MARKERS = (
    "Traceback (most recent call last)",
    "insufficient_quota",
    "rate limit",
    "RateLimitError",
    "[invalid tool",
    "Error code: 4",
    "Error code: 5",
    "InternalServerError",
    "ConnectionError",
    "timed out",
    # A tool call that reached dispatch with no/empty input, or a bridged-tool
    # crash — the call was malformed. The trajectory routed garbage; drop it.
    "no input provided",
    "[openjarvis-tool error",
)

# A final answer cut off mid-expression ends on a dangling connective
# (``a=1, b=``, ``result = ``, ``compute (``) — the decode hit the token cap
# before finishing. A real distilled answer never ends this way.
_TRUNCATED_TAIL_RE = re.compile(r"[=,(\[{+\-*/]\s*$")


def _target_is_clean(roll: UnifiedRollout) -> bool:
    """Structural gate on whether a trajectory is fit to be an SFT *target*.

    The judge decides semantic correctness; this catches the ~10-12% of records
    whose targets are empty / a Traceback / a truncated tool error / unrouted —
    garbage the model must never be trained to imitate. Requirements:
      * non-empty final answer, no error marker, balanced ``<think>`` (not
        truncated mid-thought);
      * at least one model-expert tool call (it actually *routed*);
      * no error-marker / empty observation in the kept trajectory.
    """
    fa = (roll.final_answer or "").strip()
    if not fa:
        return False
    if any(m in fa for m in _ERR_MARKERS):
        return False
    if fa.count("<think>") != fa.count(
        "</think>"
    ):  # unbalanced think tags (truncated OR stray </think>)
        return False
    if _TRUNCATED_TAIL_RE.search(fa):  # truncated mid-expression (e.g. "a=1, b=")
        return False
    # Malformed final: a proper final answer is plain text, NOT a stray/broken
    # <tool_call> tag (the model's answer leaking inside a tool call that failed
    # to parse). (\boxed{} is NOT rejected here — the serializer de-boxes it, so
    # an otherwise-good boxed answer is salvaged rather than thrown away.)
    if "<tool_call>" in fa or "</tool_call>" in fa:
        return False
    # Control-token backstop (defense in depth). The serializer strips leaked
    # control/special tokens (<|im_end|>, <|tool_call>, <start_of_turn>, …) to
    # salvage good answers, so we mirror that strip and gate on the RESULT:
    #   * strips to empty  -> the answer WAS nothing but control tokens -> drop.
    #   * a token survives the strip -> something malformed the stripper can't
    #     safely delete mid-answer -> drop rather than train on it.
    # A clean answer (or one the stripper fully salvages) sails through.
    fa_stripped = _strip_control_tokens(fa)
    if not fa_stripped:
        return False
    if _CONTROL_TOKEN_RE.search(fa_stripped):
        return False
    # Degenerate repetition: the same substantive line emitted many times (the
    # small-model decode loop). Reject rather than train on it.
    _lines = [ln.strip() for ln in fa.split("\n") if len(ln.strip()) > 30]
    if _lines and Counter(_lines).most_common(1)[0][1] >= 4:
        return False
    # Word-salad run-on: a giant unbroken line (no newline) is the other decode
    # collapse — the model spraying novel tokens instead of repeating. Reject.
    if any(len(ln) > 2000 for ln in fa.split("\n")):
        return False
    # Markdown-table dump: the model wrote a formatted table/essay instead of the
    # short exact value the format demands. A ``|---|`` separator row is the tell.
    if re.search(r"\|\s*:?-{2,}", fa):
        return False
    # Essay-style final: the format wants a distilled answer, not a multi-section
    # writeup. Check the answer AFTER the FINAL_ANSWER marker (reasoning before it
    # is fine). NOTE: length/bold limits relaxed for the BALANCED/harder mix —
    # code & multi-step math answers are legitimately longer and use **bold** for
    # the key result, so the old 700-char + any-bold rejects were dropping ~half
    # the correct hard-task answers. Keep the STRUCTURAL essay signals (many
    # numbered sections, markdown headers, tables) which still catch real essays.
    _marks = list(re.finditer(r"(?im)FINAL[_\s]?ANSWER\s*:?", fa))
    _ans = fa[_marks[-1].end() :].strip() if _marks else fa
    if len(_ans) > 2000:  # was 700 — too tight for code/math
        return False
    # Tool-status echo as the final answer: on code tasks the orchestrator
    # sometimes ends with a file_write/shell status line ("Successfully wrote to
    # /tmp/x.py") instead of the actual answer — a non-answer that slips the
    # length/format checks. Reject. (Audit: ~code/math trajectories where the
    # trace collapsed but the row was still scored correct.)
    if re.search(
        r"(?i)\b(successfully (wrote|created|saved|executed|ran)|written to /|"
        r"file (written|saved|created)|no further actions?)\b",
        _ans,
    ):
        return False
    if (
        len(re.findall(r"(?m)^\s*\d+\.\s", _ans)) >= 6
    ):  # many numbered sections = essay (was 4)
        return False
    if re.search(r"(?m)^\s*#{1,6}\s", _ans):  # markdown headers = essay
        return False
    # Garbled / shouty final: a multi-word answer that's mostly UPPERCASE, or has
    # an absurdly long merged all-letter token, is decode garble — the audit found
    # e.g. "RABES PEPTETANUS BOOSTERS" (for "rabies PEP, tetanus boosters") passing.
    if len(_ans) > 20:
        _alpha = [c for c in _ans if c.isalpha()]
        if (
            _alpha
            and sum(c.isupper() for c in _alpha) / len(_alpha) > 0.7
            and len(_ans.split()) >= 3
        ):
            return False
        if any(len(w) > 25 and w.isalpha() for w in _ans.split()):
            return False
    # Reject runaway final answers — a distilled answer, not a multi-KB essay or
    # a verbatim dump of an expert observation. (Audit: 279 finals >4k chars, the
    # worst a 409k-char wordlist; ~363 were prefix-identical to a tool obs.)
    if len(fa) > 8000:
        return False
    fa_head = re.sub(r"\s+", " ", fa[:200]).strip()
    for t in roll.turns:
        if t.observation:
            obs_head = re.sub(r"\s+", " ", t.observation[:200]).strip()
            if (
                fa_head and fa_head == obs_head and len(fa) > 200
            ):  # long final = copied tool dump (short relays are legit)
                return False
    # "routed" = delegated to a model EXPERT (not just a utility like web_search).
    # When anonymized, expert calls are the anon labels in anon_map; otherwise
    # fall back to "made any tool call".
    expert_names = set(roll.anon_map or {})
    called = {name for name, _ in roll.tool_calls()}
    if expert_names:
        if not (called & expert_names):
            return False
    elif roll.num_tool_calls < 1:
        return False
    for t in roll.turns:
        if t.tool_name is not None:
            obs = (t.observation or "").strip()
            if not obs or any(m in obs for m in _ERR_MARKERS):
                return False
    # Reasoning-side decode collapse: an intermediate turn whose reasoning is a
    # giant unbroken line, or is dominated by exotic unicode / emoji spam, is
    # garbage even when the final answer looks fine (the answer-only guards above
    # miss it). The audit found a trajectory with a thousands-char symbol blob in
    # its reasoning that scored correct and slipped through.
    for t in roll.turns:
        r = t.reasoning or ""
        if any(len(ln) > 2000 for ln in r.split("\n")):
            return False
        if len(r) > 200:
            weird = sum(1 for ch in r if ord(ch) > 0x2100 and not ch.isalnum())
            if weird / len(r) > 0.10:  # >10% exotic-unicode/emoji = decode spam
                return False
    return True


def gold_coverage_verify(task: TaskLike, rollout: UnifiedRollout) -> bool:
    """Dependency-free proxy verifier: trajectory must (a) produce a non-empty
    answer and (b) call tools covering every golden action name.

    This is the offline stand-in for ToolScale's execution-correctness checker
    (which needs the DB simulator). Compose with an LLM judge for real runs.
    """
    if not rollout.final_answer.strip():
        return False
    gold = set(task.gold_action_names())
    if not gold:
        return True
    called = {name for name, _ in rollout.tool_calls()}
    return gold.issubset(called)


def _process_task(
    task: TaskLike,
    *,
    rollout_fn: RolloutFn,
    verify_fn: VerifyFn,
    samples_per_task: int,
    max_keep_per_task: int,
    stop_at_keep: bool = False,
    keep_all: bool = False,
) -> List[tuple[UnifiedRollout, bool]]:
    """One task's rejection-sampling unit of work: roll out ``samples_per_task``
    times and verify each. Returns ``(rollout, is_correct)`` for **every** sample
    (the caller decides what to write). Runs in a worker thread, so the only
    shared state it touches is the injected fns (each rollout builds its own
    OpenAI client; the tool executor is built under a lock).

    ``stop_at_keep``: short-circuit as soon as ``max_keep_per_task`` passing
    trajectories are found, instead of always exhausting ``samples_per_task``.
    Big throughput win (no wasted rollouts on already-solved tasks), but it
    trades away the cheapest-of-N cost optimisation (we keep the first passers,
    not the cheapest). Ignored when ``keep_all`` is set (we want every sample).
    Default off preserves the original semantics."""
    results: List[tuple[UnifiedRollout, bool]] = []
    n_correct = 0
    for _ in range(samples_per_task):
        roll = rollout_fn(task)
        if roll is None:
            continue
        ok = bool(verify_fn(task, roll))
        results.append((roll, ok))
        if ok:
            n_correct += 1
            if stop_at_keep and not keep_all and n_correct >= max_keep_per_task:
                break
    return results


def generate_sft_dataset(
    out_path: str,
    *,
    tasks: Iterable[TaskLike],
    tools: List[ExpertTool],
    rollout_fn: RolloutFn,
    verify_fn: VerifyFn = gold_coverage_verify,
    samples_per_task: int = 4,
    max_keep_per_task: int = 1,
    reward_fn: Optional[Callable[[UnifiedRollout], float]] = None,
    concurrency: int = 1,
    stop_at_keep: bool = False,
    keep_all: bool = False,
    record_extra: Optional[dict] = None,
) -> dict:
    """Run rejection sampling over ``tasks`` and write the SFT JSONL.

    ``max_keep_per_task`` caps records kept per task; when >1 the cheapest
    passing trajectories are kept first. ``concurrency`` rolls out that many tasks
    in parallel (each task issues its samples sequentially, so ~``concurrency``
    requests hit the served model at once) — set 1 for the original sequential
    behaviour. Records are written as each task finishes, so peak memory is bounded
    by the in-flight tasks, not the whole dataset. Returns stats + writes a
    ``.stats.json``.

    ``keep_all``: write **every** rolled-out trajectory (correct and incorrect)
    rather than dropping the failures. Each record gets ``correct`` (verifier
    verdict) and ``kept`` (True on the cheapest-correct sample — the one the
    rejection sampler would have selected). This preserves the full sample set so
    you can compute accuracy / inspect failures; the SFT trainer should filter on
    ``correct`` (or ``kept``). Default off = original drop-the-failures behaviour.
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    tasks = list(tasks)
    seen = len(tasks)
    written = 0
    correct_written = 0
    incorrect_written = 0
    dropped = 0  # tasks that produced no kept record
    tasks_solved = 0  # tasks with >=1 correct sample
    domain_counts: Counter[str] = Counter()

    def _work(task: TaskLike) -> tuple[TaskLike, List[tuple[UnifiedRollout, bool]]]:
        return task, _process_task(
            task,
            rollout_fn=rollout_fn,
            verify_fn=verify_fn,
            samples_per_task=samples_per_task,
            max_keep_per_task=max_keep_per_task,
            stop_at_keep=stop_at_keep,
            keep_all=keep_all,
        )

    def _emit(fh, task: TaskLike, roll: UnifiedRollout, ok: bool, kept: bool) -> None:
        nonlocal written, correct_written, incorrect_written
        reward = reward_fn(roll) if reward_fn else 0.0
        record = trajectory_to_record(
            task.task_id,
            task.instruction,
            tools,
            roll,
            reward=reward,
            domain=task.domain,
        )
        record["correct"] = ok
        record["kept"] = kept
        record["clean"] = _target_is_clean(roll)
        # Task provenance so every record is self-describing: area (domain),
        # difficulty tier, source dataset, and fine subsector. Lets us slice
        # train/holdout/analysis by any of these later.
        record["area"] = task.domain
        record["difficulty"] = getattr(task, "difficulty", "") or ""
        record["dataset"] = getattr(task, "dataset", "") or ""
        record["dataset_description"] = dataset_description(record["dataset"])
        record["subsector"] = getattr(task, "subsector", "") or ""
        # Gold reference answer the verifier graded against. Persisted so every
        # record supports gold-vs-model inspection downstream (Braintrust, error
        # analysis) instead of only a bare `correct` boolean.
        record["gold_answer"] = getattr(task, "answer", "") or ""
        # Stamp provenance (which model/orchestrator generated this trajectory)
        # so records are self-identifying when pooled across model families.
        if record_extra:
            record.update(record_extra)
        fh.write(json.dumps(record) + "\n")
        fh.flush()
        written += 1
        correct_written += int(ok)
        incorrect_written += int(not ok)
        domain_counts[task.domain] += 1

    def _write(fh, task: TaskLike, results: List[tuple[UnifiedRollout, bool]]) -> None:
        nonlocal dropped, tasks_solved
        # A trajectory is only eligible to be *kept* as a training target if the
        # judge passed it AND it's structurally clean (non-error, routed, not
        # truncated). Unclean-but-correct rollouts are still written in keep_all
        # mode (for analysis) but never marked kept.
        correct = [r for r in results if r[1] and _target_is_clean(r[0])]
        cheapest = min((r for r, _ in correct), key=lambda r: r.cost_usd, default=None)
        if correct:
            tasks_solved += 1
        if keep_all:
            # Write every sample; mark the cheapest-correct one as kept.
            if not results:
                dropped += 1
                return
            for roll, ok in results:
                _emit(fh, task, roll, ok, kept=(roll is cheapest))
        else:
            # Original behaviour: keep only cheapest-correct, capped.
            if not correct:
                dropped += 1
                return
            for roll in sorted((r for r, _ in correct), key=lambda r: r.cost_usd)[
                :max_keep_per_task
            ]:
                _emit(fh, task, roll, True, kept=(roll is cheapest))

    with out.open("w") as fh:
        if concurrency <= 1:
            for task in tasks:
                _, results = _work(task)
                _write(fh, task, results)
        else:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            done = 0
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = {pool.submit(_work, t): t for t in tasks}
                for fut in as_completed(futures):
                    task = futures[fut]
                    try:
                        _, results = fut.result()
                    except Exception as exc:  # a task's worker died; count + skip
                        logger.warning(
                            "task %s failed: %s", getattr(task, "task_id", "?"), exc
                        )
                        results = []
                    _write(fh, task, results)
                    done += 1
                    if done % 50 == 0 or done == seen:
                        logger.info(
                            "rejection-sampling: %d/%d tasks done "
                            "(%d written, %d solved, %d dropped)",
                            done,
                            seen,
                            written,
                            tasks_solved,
                            dropped,
                        )

    stats = {
        "out_path": str(out),
        "tasks_seen": seen,
        "records_written": written,
        "records_correct": correct_written,
        "records_incorrect": incorrect_written,
        "tasks_solved": tasks_solved,
        "tasks_dropped": dropped,
        "task_accuracy": round(tasks_solved / seen, 4) if seen else 0.0,
        "samples_per_task": samples_per_task,
        "keep_all": keep_all,
        "concurrency": concurrency,
        "domain_distribution": dict(domain_counts),
    }
    out.with_suffix(out.suffix + ".stats.json").write_text(json.dumps(stats, indent=2))
    logger.info(
        "Wrote %d SFT records to %s (%d correct, %d incorrect)",
        written,
        out,
        correct_written,
        incorrect_written,
    )
    return stats


__all__ = ["generate_sft_dataset", "gold_coverage_verify"]
