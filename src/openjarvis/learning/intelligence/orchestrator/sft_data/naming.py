"""Single source of truth for orchestrator dataset names.

    raw/{name}-{stamp}/data.jsonl          raw/qwen-july-7-2026-0553pm/data.jsonl
    sft/{name}-{split}-{stamp}.jsonl       sft/qwen-train-july-7-2026-0553pm.jsonl

The raw dir and every file carved from it share the same ``stamp``, so a curated
split always traces back to the generation run that produced it by eye.

The stamp is written out (``july-7-2026-0553pm``) rather than numeric because
these names are read by humans far more often than they are parsed. The cost is
that month names sort alphabetically, so ``ls`` is NOT chronological — use
``ls -t``.
"""

from __future__ import annotations

import re
import time
from typing import Optional

__all__ = ["run_stamp", "dataset_name", "raw_dir_name", "stamp_from"]

# {month}-{day}-{year}-{hhmm}{am|pm}, e.g. july-7-2026-0553pm
_STAMP_RE = re.compile(r"[a-z]+-\d{1,2}-\d{4}-\d{4}(?:am|pm)", re.I)


def stamp_from(filename: str) -> Optional[str]:
    """Pull the stamp out of a raw dir / dataset name, or None if it carries none.

    ``qwen-clean-july-7-2026-0553pm.jsonl`` -> ``july-7-2026-0553pm``. Lets a split
    inherit its POOL's stamp instead of stamping itself with today's date — the
    split belongs to the run that generated the data, not to the day it was carved.
    """
    m = _STAMP_RE.search(filename)
    return m.group(0).lower() if m else None


def run_stamp(when: Optional[time.struct_time] = None) -> str:
    """``july-7-2026-0553pm`` — month-in-words, day, year, 12h clock.

    Local time, matching the wall-clock the run was launched at.
    """
    t = when or time.localtime()
    month = time.strftime("%B", t).lower()  # july
    day = t.tm_mday  # no zero-pad: 7, not 07
    clock = time.strftime("%I%M%p", t).lower()  # 0553pm (zero-padded hour)
    return f"{month}-{day}-{t.tm_year}-{clock}"


def raw_dir_name(name: str, stamp: Optional[str] = None, tag: str = "") -> str:
    """``qwen-july-7-2026-0553pm`` (+ ``-{tag}`` when disambiguating a variant)."""
    base = f"{name}-{stamp or run_stamp()}"
    return f"{base}-{tag}" if tag else base


def dataset_name(name: str, split: str, stamp: Optional[str] = None) -> str:
    """``qwen-train-july-7-2026-0553pm`` (no extension)."""
    return f"{name}-{split}-{stamp or run_stamp()}"
