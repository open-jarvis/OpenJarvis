"""Rejection-sampling SFT-data generator (the ToolOrchestra cold-start).

For each reasoning task: roll out a teacher orchestrator N times, verify each
trajectory, keep the passing ones (optionally just the cheapest), and serialize
them into the unified-tool ``conversations`` JSONL the SFT trainer consumes.

The expensive/network parts are injected so the orchestration is pure and
offline-testable:

* ``rollout_fn(task) -> UnifiedRollout`` — one teacher rollout (temperature>0).
* ``verify_fn(task, rollout) -> bool``   — did the trajectory solve the task?
  (e.g. ``verify.make_verifier()``, an LLM judge over the final answer.)
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
# (via ``trajectory_to_record``), so any task dataclass works — the reasoning
# ``datasets.Task`` is what production uses, paired with its own ``verify_fn``
# (e.g. ``verify.make_verifier()``).
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

# A line that only source code starts with. Used to spot an UNFENCED program so the
# markdown/essay guards don't read its `#` comments as headers.
_CODE_SIGNAL_RE = re.compile(
    r"(?m)^\s*(?:#!|def |class |import |from \s*\w+\s+import|function |const |let |"
    r"var |public |private |#include|package |using |fn |func )"
)


def clean_reason(roll: UnifiedRollout) -> Optional[str]:
    """Why this trajectory is unfit to be an SFT *target* — ``None`` if it's fine.

    Returns the FIRST failing check as a human-readable string so rejections are
    auditable (persisted as ``clean_reason`` on every record). Previously this
    returned a bare bool, which meant a rejected record gave no clue why — and
    the reason is genuinely not recoverable from the saved JSONL, because the
    gate runs on the RAW rollout while the serializer scrubs the stored copy.


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
        return "empty final answer"
    if any(m in fa for m in _ERR_MARKERS):
        return "error marker in final answer"
    # A thought that OPENS and never closes = the decode hit the cap mid-thought.
    # A stray CLOSING </think> with no opener is NOT truncation — Qwen3.x's chat
    # template pre-fills the opening `<think>` tag, so the model's completion
    # begins inside the reasoning block and only ever emits the closing tag. The
    # old check (`!=`) treated that template artifact as truncation and rejected
    # essentially every thinking rollout; the serializer strips the stray tag
    # anyway, so the stored target was fine. Only unclosed thoughts are bad.
    if fa.count("<think>") > fa.count("</think>"):
        return "unclosed <think> (truncated mid-thought)"
    if _TRUNCATED_TAIL_RE.search(fa):  # truncated mid-expression (e.g. "a=1, b=")
        return "final truncated mid-expression"
    # Malformed final: a proper final answer is plain text, NOT a stray/broken
    # <tool_call> tag (the model's answer leaking inside a tool call that failed
    # to parse). (\boxed{} is NOT rejected here — the serializer de-boxes it, so
    # an otherwise-good boxed answer is salvaged rather than thrown away.)
    if "<tool_call>" in fa or "</tool_call>" in fa:
        return "tool_call tag leaked into final answer"
    # Control-token backstop (defense in depth). The serializer strips leaked
    # control/special tokens (<|im_end|>, <|tool_call>, <start_of_turn>, …) to
    # salvage good answers, so we mirror that strip and gate on the RESULT:
    #   * strips to empty  -> the answer WAS nothing but control tokens -> drop.
    #   * a token survives the strip -> something malformed the stripper can't
    #     safely delete mid-answer -> drop rather than train on it.
    # A clean answer (or one the stripper fully salvages) sails through.
    fa_stripped = _strip_control_tokens(fa)
    if not fa_stripped:
        return "final answer was only control tokens"
    if _CONTROL_TOKEN_RE.search(fa_stripped):
        return "control tokens in final answer"
    # Degenerate repetition: the same substantive line emitted many times (the
    # small-model decode loop). Reject rather than train on it.
    _lines = [ln.strip() for ln in fa.split("\n") if len(ln.strip()) > 30]
    if _lines and Counter(_lines).most_common(1)[0][1] >= 4:
        return "degenerate repetition"
    # Word-salad run-on: a giant unbroken line (no newline) is the other decode
    # collapse — the model spraying novel tokens instead of repeating. Reject.
    if any(len(ln) > 2000 for ln in fa.split("\n")):
        return "word-salad run-on line"
    # Essay-style final: the format wants a distilled answer, not a multi-section
    # writeup. Check the answer AFTER the FINAL_ANSWER marker (reasoning before it
    # is fine). NOTE: length/bold limits relaxed for the BALANCED/harder mix —
    # code & multi-step math answers are legitimately longer and use **bold** for
    # the key result, so the old 700-char + any-bold rejects were dropping ~half
    # the correct hard-task answers. Keep the STRUCTURAL essay signals (many
    # numbered sections, markdown headers, tables) which still catch real essays.
    _marks = list(re.finditer(r"(?im)FINAL[_\s]?ANSWER\s*:?", fa))
    _ans = fa[_marks[-1].end() :].strip() if _marks else fa
    # Every structural essay guard below runs on the PROSE only — a fenced code
    # block is a legitimate answer, not an essay, and its contents are not
    # markdown. Without this:
    #   * a Python comment ("# Use download_as_text()") matches the markdown-header
    #     regex `^\s*#{1,6}\s` and the whole answer is rejected as an "essay";
    #   * a numbered list in a docstring trips the numbered-sections guard;
    #   * an ASCII table in code output trips the markdown-table guard;
    #   * a real program blows the 2000-char limit on its own.
    # Audit 2026-07-13: this was the difference between code correct=12/22 and code
    # USABLE=3/22 — we were binning ~3 of every 4 correct code answers.
    _prose = re.sub(r"```.*?```", "", _ans, flags=re.DOTALL)
    _prose = re.sub(r"(?m)^ {4,}\S.*$", "", _prose)  # indented code blocks too
    # …and UNFENCED raw code. Haiku often answers a code task with a bare program
    # and no ``` fence at all, and then its shebang (`#!/usr/bin/env python3`) and
    # its comments (`# Read input`) trip the markdown-header regex exactly like the
    # fenced case did. If what's left after stripping fences still reads as code,
    # there is no prose to run essay guards against. (Audit 2026-07-13 — the fenced
    # fix caught only half of this bug.)
    if _CODE_SIGNAL_RE.search(_prose):
        _prose = ""
    # Markdown-table dump: the model wrote a formatted table instead of the short
    # exact value the format demands. A ``|---|`` separator row is the tell.
    if re.search(r"\|\s*:?-{2,}", _prose):
        return "markdown table dump"
    if len(_prose) > 2000:  # prose-only: a long program is fine, an essay is not
        return "final answer >2000 chars (essay)"
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
        return "tool-status echo as the answer"
    if (
        len(re.findall(r"(?m)^\s*\d+\.\s", _prose)) >= 6
    ):  # many numbered sections = essay (was 4)
        return "many numbered sections (essay)"
    if re.search(r"(?m)^\s*#{1,6}\s", _prose):  # markdown headers = essay
        return "markdown headers (essay)"
    # Garbled / shouty final: a multi-word answer that's mostly UPPERCASE, or has
    # an absurdly long merged all-letter token, is decode garble — the audit found
    # e.g. "RABES PEPTETANUS BOOSTERS" (for "rabies PEP, tetanus boosters") passing.
    if len(_ans) > 20:
        # Measure the caps ratio over PROSE tokens only. A chemistry answer is
        # legitimately uppercase-heavy — "HC≡CH → NaNH₂ → CH₃CH₂CH₂Br" is a
        # reaction scheme, not shouting — and the old whole-string ratio rejected
        # those outright (audit 2026-07-12), which is expensive because organic
        # chemistry is one of our highest-yield domains. So ignore any token that
        # carries a digit, a subscript/superscript, or a non-ASCII symbol (arrows,
        # bond glyphs): that's formula notation, not decode collapse. What's left
        # is real words, which is what the guard was built for ("RABES PEPTETANUS
        # BOOSTERS").
        _words = [
            w
            for w in _ans.split()
            if w.isalpha() and len(w) >= 3 and w.isascii()
        ]
        _alpha = [c for w in _words for c in w]
        if (
            len(_words) >= 3
            and _alpha
            and sum(c.isupper() for c in _alpha) / len(_alpha) > 0.7
        ):
            return "ALL-CAPS garble"
        if any(len(w) > 25 and w.isalpha() for w in _ans.split()):
            return "merged mega-token garble"
    # Reject runaway final answers — a distilled answer, not a multi-KB essay or
    # a verbatim dump of an expert observation. (Audit: 279 finals >4k chars, the
    # worst a 409k-char wordlist; ~363 were prefix-identical to a tool obs.)
    if len(fa) > 8000:
        return "runaway final (>8k chars)"
    fa_head = re.sub(r"\s+", " ", fa[:200]).strip()
    for t in roll.turns:
        if t.observation:
            obs_head = re.sub(r"\s+", " ", t.observation[:200]).strip()
            if (
                fa_head and fa_head == obs_head and len(fa) > 200
            ):  # long final = copied tool dump (short relays are legit)
                return "final answer copied verbatim from a tool result"
    # "routed" = delegated to a model EXPERT (not just a utility like web_search).
    # When anonymized, expert calls are the anon labels in anon_map; otherwise
    # fall back to "made any tool call".
    expert_names = set(roll.anon_map or {})
    called = {name for name, _ in roll.tool_calls()}
    if expert_names:
        if not (called & expert_names):
            return "NEVER routed to a model expert"
    elif roll.num_tool_calls < 1:
        return "no tool calls at all"
    # A broken EXPERT observation (rate limit / 5xx / dead provider) means the
    # trajectory routed into a hole and whatever follows is built on nothing —
    # reject it.
    #
    # A sandbox tool is different. `code_interpreter` returning a Python
    # "Traceback (most recent call last)" is the tool WORKING: the model ran code,
    # it raised, and the model reads the error and fixes it. That error-recovery
    # loop is precisely what we want to teach. Treating it as a broken tool threw
    # out 24% of rollouts (audit 2026-07-12: 21 of 23 flagged observations were
    # code_interpreter tracebacks the model then recovered from). Only an EMPTY
    # observation is fatal for a sandbox tool — that means the tool itself died.
    for t in roll.turns:
        if t.tool_name is None:
            continue
        obs = (t.observation or "").strip()
        if not obs:
            return "empty tool observation"
        is_expert = t.tool_name in expert_names if expert_names else False
        if is_expert and any(m in obs for m in _ERR_MARKERS):
            return "error observation from a model expert"
    # Reasoning-side decode collapse: an intermediate turn whose reasoning is a
    # giant unbroken line, or is dominated by exotic unicode / emoji spam, is
    # garbage even when the final answer looks fine (the answer-only guards above
    # miss it). The audit found a trajectory with a thousands-char symbol blob in
    # its reasoning that scored correct and slipped through.
    for t in roll.turns:
        r = t.reasoning or ""
        if any(len(ln) > 2000 for ln in r.split("\n")):
            return "reasoning decode collapse (giant line)"
        if len(r) > 200:
            weird = sum(1 for ch in r if ord(ch) > 0x2100 and not ch.isalnum())
            if weird / len(r) > 0.10:  # >10% exotic-unicode/emoji = decode spam
                return "reasoning unicode/emoji spam"
    return None


def _target_is_clean(roll: UnifiedRollout) -> bool:
    """Back-compat bool wrapper around :func:`clean_reason`."""
    return clean_reason(roll) is None


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
    verify_fn: VerifyFn,
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
        # Persist WHY a trajectory was rejected. The gate runs on the raw rollout
        # while the serializer scrubs the stored conversations, so the reason is
        # not recoverable from the saved record afterwards — capture it here.
        why = clean_reason(roll)
        record["clean"] = why is None
        record["clean_reason"] = why or ""
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


__all__ = ["generate_sft_dataset"]
