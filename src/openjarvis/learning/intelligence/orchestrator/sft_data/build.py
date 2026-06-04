"""End-to-end SFT dataset builder + CLI.

    ADP trajectory -> canonical Episode -> render_all -> select_best
        -> to_record -> JSONL  (+ a sidecar ``.stats.json``)

Runs with no GPU and no API keys (the cold-start re-tiers demonstrated traces;
it does not execute models). Network is only touched to stream ADP rows.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional

from openjarvis.learning.intelligence.orchestrator.reward import (
    MultiObjectiveReward,
    Normalizers,
    RewardWeights,
)
from openjarvis.learning.intelligence.orchestrator.sft_data.adp_loader import (
    DEFAULT_CONFIGS,
    iter_trajectories,
)
from openjarvis.learning.intelligence.orchestrator.sft_data.paradigms import render_all
from openjarvis.learning.intelligence.orchestrator.sft_data.select import select_best
from openjarvis.learning.intelligence.orchestrator.sft_data.serialize import to_record
from openjarvis.learning.intelligence.orchestrator.types import Episode

logger = logging.getLogger(__name__)


def build_sft_dataset(
    out_path: str,
    *,
    max_tasks: Optional[int] = 2000,
    configs: Iterable[str] = DEFAULT_CONFIGS,
    source: Optional[Callable[..., Iterator[Episode]]] = None,
) -> dict:
    """Build the SFT JSONL at ``out_path`` and return stats.

    ``source`` overrides the ADP stream (used by tests to inject fixtures); it
    must be a callable returning an iterator of canonical :class:`Episode`.
    """
    reward = MultiObjectiveReward(RewardWeights(), Normalizers())
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    episodes = (
        source(max_tasks=max_tasks, configs=configs)
        if source is not None
        else iter_trajectories(max_tasks=max_tasks, configs=configs)
    )

    seen = 0
    written = 0
    dropped = 0
    paradigm_counts: Counter[str] = Counter()

    with out.open("w") as fh:
        for episode in episodes:
            seen += 1
            best = select_best(render_all(episode), reward=reward)
            if best is None:
                dropped += 1
                continue
            record = to_record(best, reward=reward.compute(best.episode))
            fh.write(json.dumps(record) + "\n")
            written += 1
            paradigm_counts[best.paradigm] += 1

    stats = {
        "out_path": str(out),
        "tasks_seen": seen,
        "records_written": written,
        "tasks_dropped": dropped,
        "paradigm_distribution": dict(paradigm_counts),
    }
    stats_path = out.with_suffix(out.suffix + ".stats.json")
    stats_path.write_text(json.dumps(stats, indent=2))
    logger.info("Wrote %d SFT records to %s (%s)", written, out, dict(paradigm_counts))
    return stats


def _main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build orchestrator SFT data from ADP."
    )
    parser.add_argument("--out", default="data/orchestrator_sft_traces.jsonl")
    parser.add_argument("--max-tasks", type=int, default=2000)
    parser.add_argument(
        "--adp-configs",
        default=",".join(DEFAULT_CONFIGS),
        help="comma-separated ADP sub-configs to stream",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    configs = [c.strip() for c in args.adp_configs.split(",") if c.strip()]
    stats = build_sft_dataset(args.out, max_tasks=args.max_tasks, configs=configs)
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())


__all__ = ["build_sft_dataset"]
