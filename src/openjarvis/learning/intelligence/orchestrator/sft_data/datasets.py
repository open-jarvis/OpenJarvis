"""Loaders for the orchestrator reasoning-SFT task sources.

Two HuggingFace reasoning datasets give us verifiable question/answer tasks for
the small orchestrator's cold-start SFT and the GRPO prompt pool:

- ``natolambert/GeneralThought-430K-filtered`` — open reasoning traces scraped
  from gr.inc. Each row carries a ``question``, a short ``reference_answer``
  (the gold), a long ``model_answer`` (R1's full solution), and provenance in
  ``question_source`` / ``task``. There is **no** clean single "category" field;
  we derive a coarse ``domain`` (math / medical / code / chat / misc) from
  ``question_source`` so the verifier can pick the right checker.

- ``open-thoughts/OpenThoughts3-1.2M`` — OpenThoughts3 distillation set. Each
  row has a ``domain`` in {code, math, science}, a ``source``, a ``difficulty``,
  and a ``conversations`` list ``[{from: human, value}, {from: gpt, value}]``.
  The human turn is the question; the gpt turn is a ``<think>…</think>`` trace
  followed by the final solution, from which we extract the gold answer.

Mirrors the style of the sibling ``hotpotqa.py`` / ``toolscale.py`` loaders: a
plain dataclass plus loaders that accept a ``source=`` iterable override so the
normalization path is exercised offline with no network. Network imports of
``datasets`` are kept lazy (inside the function).
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, List, Optional

GENERALTHOUGHT_ID = "natolambert/GeneralThought-430K-filtered"
OPENTHOUGHTS_ID = "open-thoughts/OpenThoughts3-1.2M"


@dataclass
class Task:
    task_id: str
    question: str
    answer: str
    domain: str  # coarse area: math / code / science / medical / chat / misc
    difficulty: str = ""  # OpenThoughts difficulty tier (GeneralThought has none)
    dataset: str = ""  # source dataset: GeneralThought / OpenThoughts3
    subsector: str = ""  # fine source: NuminaMath / NHSQA / TACO / glaive / ...

    @property
    def instruction(self) -> str:
        return self.question


# --- GeneralThought -----------------------------------------------------------

# question_source -> coarse domain. GeneralThought has no literal category field;
# the source string is the most reliable signal (NuminaMath is math, NHSQA is
# medical, TACO/glaive are code, oasst1/lmsys are open chat, everything else misc).
_SOURCE_DOMAIN = (
    ("numina", "math"),
    ("math", "math"),
    ("nhsqa", "medical"),
    ("medical", "medical"),
    ("medicine", "medical"),
    ("taco", "code"),
    ("code", "code"),
    ("glaive", "code"),
    ("oasst", "chat"),
    ("lmsys", "chat"),
    ("chat", "chat"),
)


def _generalthought_domain(row: Dict[str, Any]) -> str:
    src = str(row.get("question_source") or "").lower()
    task = str(row.get("task") or "").lower()
    hay = f"{src} {task}"
    for needle, dom in _SOURCE_DOMAIN:
        if needle in hay:
            return dom
    return "misc"


def _normalize_generalthought(row: Dict[str, Any], *, index: int = 0) -> Optional[Task]:
    question = str(row.get("question") or "").strip()
    # Prefer the short reference answer (exact-match-able); fall back to the
    # long model_answer when no reference is present.
    answer = str(row.get("reference_answer") or "").strip()
    if not answer:
        answer = str(row.get("model_answer") or "").strip()
    if not question or not answer:
        return None
    task_id = str(row.get("question_id") or f"generalthought-{index}")
    return Task(
        task_id=task_id,
        question=question,
        answer=answer,
        domain=_generalthought_domain(row),
        difficulty=str(row.get("difficulty") or "").strip(),  # usually absent for GT
        dataset="GeneralThought",
        subsector=str(row.get("question_source") or "").strip(),
    )


def load_generalthought(
    *,
    n: int = 2000,
    seed: int = 42,
    source: Optional[Iterable[Dict[str, Any]]] = None,
    buffer: Optional[int] = None,
) -> Iterator[Task]:
    """Yield up to ``n`` GeneralThought tasks, randomly mixed across categories.

    ``source`` overrides the HF stream with an iterable of raw row dicts (tests).
    We over-stream a buffer and shuffle it so the yielded tasks are a random mix
    of the source's categories rather than a single leading shard. ``buffer``
    overrides the shuffle-buffer size; pass a small value (e.g. for smoke runs)
    to avoid streaming the default 6000-row floor.
    """
    if source is None:
        from datasets import load_dataset  # lazy: optional dep / network

        source = load_dataset(GENERALTHOUGHT_ID, split="train", streaming=True)

    rng = random.Random(seed)
    # Buffer a generous multiple of n so the shuffle actually mixes categories,
    # but stay bounded for the multi-hundred-K streams.
    buf_cap = buffer if buffer is not None else max(n * 6, 6000)
    buf: List[Task] = []
    for i, row in enumerate(source):
        task = _normalize_generalthought(dict(row), index=i)
        if task is None:
            continue
        buf.append(task)
        if len(buf) >= buf_cap:
            break
    rng.shuffle(buf)
    for task in buf[:n]:
        yield task


# --- OpenThoughts3 ------------------------------------------------------------

_BOXED_RE = re.compile(r"\\boxed\{")


def _extract_boxed(text: str) -> Optional[str]:
    """Return the contents of the last ``\\boxed{...}`` in ``text`` (brace-balanced)."""
    last = None
    for m in _BOXED_RE.finditer(text):
        start = m.end()
        depth = 1
        i = start
        while i < len(text) and depth > 0:
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            i += 1
        if depth == 0:
            last = text[start : i - 1].strip()
    return last


def _conversation_qa(conversations: Any) -> Optional[tuple[str, str]]:
    """Pull (question, gold_answer) from an OpenThoughts ``conversations`` list."""
    if not isinstance(conversations, list):
        return None
    question = ""
    full = ""
    for turn in conversations:
        if not isinstance(turn, dict):
            continue
        who = str(turn.get("from") or "").lower()
        val = str(turn.get("value") or "")
        if who in ("human", "user") and not question:
            question = val.strip()
        elif who in ("gpt", "assistant"):
            full = val
    if not question or not full:
        return None
    # Drop the <think>…</think> trace; keep the post-reasoning solution.
    visible = re.sub(r"(?s)<think>.*?</think>", "", full).strip()
    body = visible or full
    answer = _extract_boxed(body) or _extract_boxed(full) or body.strip()
    if not answer:
        return None
    return question, answer


def _normalize_openthoughts(row: Dict[str, Any], *, index: int = 0) -> Optional[Task]:
    qa = _conversation_qa(row.get("conversations"))
    if qa is None:
        return None
    question, answer = qa
    if not question or not answer:
        return None
    domain = str(row.get("domain") or "unknown").strip().lower() or "unknown"
    task_id = (
        str(row.get("id") or row.get("source") or f"openthoughts-{index}") + f"-{index}"
    )
    return Task(
        task_id=task_id,
        question=question,
        answer=answer,
        domain=domain,
        difficulty=str(row.get("difficulty") or "").strip(),
        dataset="OpenThoughts3",
        subsector=str(row.get("source") or "").strip(),
    )


# The 1.2M set ships as 120 uniform parquet shards with no domain in the file
# names, but the rows are front-ordered by domain. Probing one row per shard puts
# code in shards ~0-30, math ~32-104, science ~105-119. Streaming the single
# combined split therefore has to read the entire code (+ math) prefix before it
# reaches math/science — minutes of wasted I/O. Instead we stream each domain from
# shards *inside* its own region. A few shards (~10K rows each) cover any quota.
_OT_SHARD_FMT = "data/train-{:05d}-of-00120.parquet"
_OT_DOMAIN_SHARDS: Dict[str, List[int]] = {
    "code": [0, 1, 2, 3],
    "math": [45, 46, 47, 48],
    "science": [112, 113, 114, 115, 116, 117, 118, 119],
}


def load_openthoughts(
    *,
    n_code: int = 2000,
    n_math: int = 2000,
    n_science: int = 2000,
    seed: int = 42,
    source: Optional[Iterable[Dict[str, Any]]] = None,
) -> Iterator[Task]:
    """Yield OpenThoughts3 tasks balanced across code / math / science.

    ``source`` overrides the stream with raw row dicts (tests): rows are routed
    into per-domain buffers, stopping once every quota is met. With no override we
    stream each domain from its own shard region (see ``_OT_DOMAIN_SHARDS``) so a
    balanced pull never has to read the entire front-ordered code/math prefix.
    """
    quotas = {"code": n_code, "math": n_math, "science": n_science}
    bufs: Dict[str, List[Task]] = {k: [] for k in quotas}

    if source is not None:
        for i, row in enumerate(source):
            task = _normalize_openthoughts(dict(row), index=i)
            if task is None:
                continue
            dom = task.domain
            if dom in bufs and len(bufs[dom]) < quotas[dom]:
                bufs[dom].append(task)
            if all(len(bufs[k]) >= quotas[k] for k in quotas):
                break
    else:
        from datasets import load_dataset  # lazy: optional dep / network

        idx = 0
        for dom, quota in quotas.items():
            if quota <= 0:
                continue
            files = [_OT_SHARD_FMT.format(s) for s in _OT_DOMAIN_SHARDS[dom]]
            ds = load_dataset(
                OPENTHOUGHTS_ID, data_files=files, split="train", streaming=True
            )
            for row in ds:
                task = _normalize_openthoughts(dict(row), index=idx)
                idx += 1
                if task is None or task.domain != dom:
                    continue
                bufs[dom].append(task)
                if len(bufs[dom]) >= quota:
                    break

    rng = random.Random(seed)
    out: List[Task] = []
    for k in quotas:
        out.extend(bufs[k])
    rng.shuffle(out)
    for task in out:
        yield task


# --- combined SFT / GRPO sets -------------------------------------------------


def load_sft_tasks(
    *, seed: int = 42, cap: Optional[int] = None, balanced: bool = True
) -> List[Task]:
    """The 8K cold-start SFT set: 2K GeneralThought + 2K code + 2K math + 2K science.

    ``cap`` (smoke runs): when set, draw ~``cap`` tasks total.
      - default (``balanced=False``): GeneralThought only with a small stream
        buffer — fastest, but the domain mix is whatever GeneralThought yields
        (math/code/medical/chat), so a given sample can skew (e.g. all-medical).
      - ``balanced=True``: ~cap/4 from each of GeneralThought + OpenThoughts
        code/math/science, so the smoke is representative of the real run. Now
        cheap because OpenThoughts streams from per-domain shards (no front-prefix).
    """
    if cap is not None and cap > 0:
        if balanced:
            per = max(cap // 4, 1)
            tasks = list(load_generalthought(n=per, seed=seed, buffer=max(per * 6, 64)))
            tasks.extend(
                load_openthoughts(n_code=per, n_math=per, n_science=per, seed=seed)
            )
            rng = random.Random(seed)
            rng.shuffle(tasks)
            return tasks[:cap]
        buf = max(cap * 4, 64)
        tasks = list(load_generalthought(n=cap, seed=seed, buffer=buf))
        random.Random(seed).shuffle(tasks)
        return tasks[:cap]
    tasks: List[Task] = []
    tasks.extend(load_generalthought(n=2000, seed=seed))
    tasks.extend(load_openthoughts(n_code=2000, n_math=2000, n_science=2000, seed=seed))
    rng = random.Random(seed)
    rng.shuffle(tasks)
    return tasks


def load_grpo_prompts(*, n: int = 30000, seed: int = 42) -> List[Task]:
    """Pool ``n`` unique prompts from the same datasets, deduped by question.

    We draw a roughly even split from GeneralThought and OpenThoughts3 (code /
    math / science), dedupe on the question text, and cap at ``n``.
    """
    per = max(n // 4 + 1, 1)
    pool: List[Task] = []
    pool.extend(load_generalthought(n=per, seed=seed))
    pool.extend(load_openthoughts(n_code=per, n_math=per, n_science=per, seed=seed))

    rng = random.Random(seed)
    rng.shuffle(pool)

    seen: set[str] = set()
    out: List[Task] = []
    for task in pool:
        key = task.question.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(task)
        if len(out) >= n:
            break
    return out


__all__ = [
    "GENERALTHOUGHT_ID",
    "OPENTHOUGHTS_ID",
    "Task",
    "load_generalthought",
    "load_grpo_prompts",
    "load_openthoughts",
    "load_sft_tasks",
]
