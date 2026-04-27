#!/usr/bin/env python3
"""Gather consensus edits from learning-session plan.json files.

Walks ``<sessions_root>/<session_id>/plan.json`` (default
``~/.openjarvis/learning/sessions``), counts votes per
``(op, target, payload-value)`` tuple across every plan, applies a majority
threshold, and writes a single ``consensus_edits.json`` that the apply step
consumes.

Inputs (one of):
    --sessions-root <dir>   Walk plan.json files under this directory (default).
    --tallies-file <json>   Skip walking; read pre-aggregated tallies (the
                            shape produced by --emit-tallies). Useful when the
                            session directory is on another machine or when
                            reproducing a historical snapshot.

Output:
    <out>/consensus_edits.json   Final consensus edits (read by apply step).
                                 Includes a ``deferred_to_m3`` block listing
                                 free-text ops (prompt patches, few-shot
                                 exemplars, tool descriptions) that cannot be
                                 merged by majority voting and are recorded
                                 verbatim for the M3 hill-climber to consume
                                 as candidate seeds.
    <out>/raw_tallies.json       Full per-(op, target, value) vote counts plus
                                 an ``audit_tallies`` section for the deferred
                                 free-text ops.
    <out>/raw_edits.jsonl        One row per edit found (audit trail).

Why this exists: the consensus values used by m2 used to be hard-coded in
m2_create_distilled_configs.py (DISTILLED_TEMP, DISTILLED_MAX_TURNS,
REMOVE_TOOLS). That meant the analysis was off-tree and unreproducible. This
script makes the tally reproducible and the consensus edits a data artifact.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_SESSIONS_ROOT = Path.home() / ".openjarvis" / "learning" / "sessions"


@dataclass
class EditKey:
    """A (op, target, value) tuple identifying one distinct edit proposal."""

    op: str
    target: str
    value: str  # JSON-serialised payload value (or tool name for add/remove tool)

    def as_tuple(self) -> tuple[str, str, str]:
        return (self.op, self.target, self.value)


@dataclass
class Tally:
    op: str
    target: str
    value: Any
    votes: int = 0
    sample_session_ids: list[str] = field(default_factory=list)


# ── Edit-row extraction ──────────────────────────────────────────────────────


def edit_to_key(edit: dict) -> EditKey | None:
    """Reduce an Edit dict to a vote key.

    Returns None for ops we don't tally (e.g. lora_finetune, prompt patches,
    where the value space is too sparse for plain majority voting).
    """
    op = edit.get("op")
    target = edit.get("target", "")
    payload = edit.get("payload") or {}

    if op in ("add_tool_to_agent", "remove_tool_from_agent"):
        tool = payload.get("tool_name") or payload.get("name") or payload.get("tool")
        if not tool:
            return None
        return EditKey(op=op, target=target, value=str(tool))

    if op == "set_agent_param":
        param = payload.get("param") or payload.get("name")
        value = payload.get("value")
        if param is None or value is None:
            return None
        # Bucket numeric temperature values (0.21 → "0.2") so close votes
        # collapse onto the same bin.
        if param == "temperature" and isinstance(value, (int, float)):
            value = round(float(value), 1)
        return EditKey(op=op, target=f"{target}.{param}", value=json.dumps(value))

    if op == "set_model_param":
        param = payload.get("param") or payload.get("name")
        value = payload.get("value")
        if param is None or value is None:
            return None
        return EditKey(op=op, target=f"{target}.{param}", value=json.dumps(value))

    if op == "set_agent_class":
        # Applier reads payload["new_class"]; target is the agent name.
        new_class = payload.get("new_class")
        if new_class is None:
            return None
        return EditKey(op=op, target=target, value=json.dumps(new_class))

    if op == "set_model_for_query_class":
        # Applier reads payload["query_class"] and payload["model"]; bucket as
        # (op, target=query_class, value=model) so the consensus row reads as
        # "for query class X, the consensus model is Y."
        query_class = payload.get("query_class")
        model = payload.get("model")
        if query_class is None or model is None:
            return None
        return EditKey(op=op, target=str(query_class), value=json.dumps(model))

    # Free-text ops (prompt patches, few-shot, tool descriptions) and lora are
    # handled by edit_to_audit_key / lora_finetune is excluded entirely.
    return None


# Free-text ops that we record verbatim instead of merging by majority vote.
# M3 hill-climber consumes these as candidate seeds.
DEFERRED_OPS: tuple[str, ...] = (
    "patch_system_prompt",
    "replace_system_prompt",
    "edit_few_shot_exemplars",
    "edit_tool_description",
)


def edit_to_audit_key(edit: dict) -> EditKey | None:
    """Reduce a free-text edit to an audit key for exact-payload tallying.

    Returns None for ops not in DEFERRED_OPS. The value is the full payload
    JSON-serialised with sorted keys so identical payloads collapse onto a
    single row regardless of dict ordering.
    """
    op = edit.get("op")
    if op not in DEFERRED_OPS:
        return None
    target = edit.get("target", "")
    payload = edit.get("payload") or {}
    try:
        value = json.dumps(payload, sort_keys=True)
    except TypeError:
        value = repr(payload)
    return EditKey(op=op, target=target, value=value)


def walk_plans(sessions_root: Path) -> list[tuple[str, dict]]:
    """Return [(session_id, edit), ...] across every plan.json under root."""
    out: list[tuple[str, dict]] = []
    if not sessions_root.exists():
        print(f"WARN: sessions root does not exist: {sessions_root}", file=sys.stderr)
        return out

    for plan_path in sorted(sessions_root.glob("*/plan.json")):
        session_id = plan_path.parent.name
        try:
            plan = json.loads(plan_path.read_text())
        except Exception as e:
            print(f"WARN: failed to read {plan_path}: {e}", file=sys.stderr)
            continue
        for edit in plan.get("edits", []):
            out.append((session_id, edit))
    return out


# ── Tally + threshold ────────────────────────────────────────────────────────


def tally_edits(edits: list[tuple[str, dict]]) -> dict[tuple[str, str, str], Tally]:
    tallies: dict[tuple[str, str, str], Tally] = {}
    for session_id, edit in edits:
        key = edit_to_key(edit)
        if key is None:
            continue
        try:
            value: Any = json.loads(key.value)
        except (json.JSONDecodeError, TypeError):
            value = key.value
        t = tallies.setdefault(
            key.as_tuple(),
            Tally(op=key.op, target=key.target, value=value),
        )
        t.votes += 1
        if len(t.sample_session_ids) < 5:
            t.sample_session_ids.append(session_id)
    return tallies


def audit_tally_edits(
    edits: list[tuple[str, dict]],
) -> dict[tuple[str, str, str], Tally]:
    """Tally exact-payload occurrences for free-text ops in DEFERRED_OPS."""
    tallies: dict[tuple[str, str, str], Tally] = {}
    for session_id, edit in edits:
        key = edit_to_audit_key(edit)
        if key is None:
            continue
        # Decode payload back to a dict for downstream consumers; fall back to
        # the raw string if it isn't JSON for any reason.
        try:
            payload: Any = json.loads(key.value)
        except (json.JSONDecodeError, TypeError):
            payload = key.value
        t = tallies.setdefault(
            key.as_tuple(),
            Tally(op=key.op, target=key.target, value=payload),
        )
        t.votes += 1
        if len(t.sample_session_ids) < 5:
            t.sample_session_ids.append(session_id)
    return tallies


def pick_consensus(
    tallies: dict[tuple[str, str, str], Tally],
    *,
    min_votes: int,
    min_majority: float,
) -> dict[str, Any]:
    """Pick the majority value per (op, target) group.

    For numeric/scalar ops (set_agent_param, set_model_param): the value with
    the most votes wins, provided it has both >= min_votes votes AND
    >= min_majority share among all votes for that (op, target) group.

    For tool ops (add/remove): every (op, target, tool) tuple with >= min_votes
    is included independently (you can remove multiple tools).
    """
    # Group by (op, target)
    by_group: dict[tuple[str, str], list[Tally]] = defaultdict(list)
    for t in tallies.values():
        by_group[(t.op, t.target)].append(t)

    consensus_scalar: list[dict] = []
    consensus_tools: dict[str, list[dict]] = {
        "add_tool_to_agent": [],
        "remove_tool_from_agent": [],
    }

    for (op, target), group in by_group.items():
        total = sum(t.votes for t in group)
        if op in consensus_tools:
            for t in group:
                if t.votes >= min_votes:
                    consensus_tools[op].append(
                        {
                            "target": target,
                            "tool_name": t.value,
                            "votes": t.votes,
                            "total_votes_in_group": total,
                        }
                    )
        else:
            winner = max(group, key=lambda t: t.votes)
            share = winner.votes / total if total else 0.0
            if winner.votes >= min_votes and share >= min_majority:
                consensus_scalar.append(
                    {
                        "op": op,
                        "target": target,
                        "value": winner.value,
                        "votes": winner.votes,
                        "total_votes_in_group": total,
                        "majority_share": round(share, 3),
                    }
                )

    return {
        "scalar_edits": consensus_scalar,
        "add_tools": consensus_tools["add_tool_to_agent"],
        "remove_tools": consensus_tools["remove_tool_from_agent"],
    }


def build_deferred_to_m3(
    audit_tallies: dict[tuple[str, str, str], Tally],
) -> dict[str, list[dict]]:
    """Group audit-tally rows by op into the deferred_to_m3 block.

    No min_votes / min_majority filtering — singletons are kept so the M3
    hill-climber can decide what's worth pursuing. Rows are sorted by votes
    descending within each op.
    """
    by_op: dict[str, list[dict]] = {op: [] for op in DEFERRED_OPS}
    by_group_total: dict[tuple[str, str], int] = defaultdict(int)
    for t in audit_tallies.values():
        by_group_total[(t.op, t.target)] += t.votes
    for t in audit_tallies.values():
        if t.op not in by_op:
            continue
        by_op[t.op].append(
            {
                "target": t.target,
                "payload": t.value,
                "votes": t.votes,
                "total_votes_in_group": by_group_total[(t.op, t.target)],
                "sample_session_ids": list(t.sample_session_ids),
            }
        )
    for op, rows in by_op.items():
        rows.sort(key=lambda r: (-r["votes"], r["target"]))
    return by_op


# ── I/O helpers ──────────────────────────────────────────────────────────────


def write_raw_edits(edits: list[tuple[str, dict]], out_path: Path) -> None:
    with out_path.open("w", encoding="utf-8") as f:
        for session_id, edit in edits:
            f.write(json.dumps({"session_id": session_id, **edit}) + "\n")


def serialise_tallies(tallies: dict[tuple[str, str, str], Tally]) -> list[dict]:
    return [
        {
            "op": t.op,
            "target": t.target,
            "value": t.value,
            "votes": t.votes,
            "sample_session_ids": t.sample_session_ids,
        }
        for t in sorted(tallies.values(), key=lambda x: (-x.votes, x.op, x.target))
    ]


def deserialise_tallies(rows: list[dict]) -> dict[tuple[str, str, str], Tally]:
    out: dict[tuple[str, str, str], Tally] = {}
    for row in rows:
        key = (row["op"], row["target"], json.dumps(row["value"]))
        out[key] = Tally(
            op=row["op"],
            target=row["target"],
            value=row["value"],
            votes=int(row["votes"]),
            sample_session_ids=list(row.get("sample_session_ids", [])),
        )
    return out


# ── Entry point ──────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = p.add_mutually_exclusive_group()
    src.add_argument(
        "--sessions-root",
        type=Path,
        default=DEFAULT_SESSIONS_ROOT,
        help=f"Walk plan.json files under this dir (default: {DEFAULT_SESSIONS_ROOT})",
    )
    src.add_argument(
        "--tallies-file",
        type=Path,
        help="Skip walking; load pre-aggregated tallies from this JSON.",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path("results/neurips-2026/distillation-m2/consensus"),
        help="Output directory (default: results/.../distillation-m2/consensus)",
    )
    p.add_argument(
        "--min-votes",
        type=int,
        default=5,
        help="Minimum votes for a value to qualify as consensus (default: 5)",
    )
    p.add_argument(
        "--min-majority",
        type=float,
        default=0.4,
        help=(
            "For scalar ops: winning value must hold this share of group "
            "votes. M1 used plurality (~0.4), not strict majority (default: 0.4)."
        ),
    )
    args = p.parse_args(argv)

    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.tallies_file:
        tallies_doc = json.loads(args.tallies_file.read_text())
        tallies = deserialise_tallies(tallies_doc.get("tallies", tallies_doc))
        audit_tallies = deserialise_tallies(tallies_doc.get("audit_tallies", []))
        n_edits = sum(t.votes for t in tallies.values()) + sum(
            t.votes for t in audit_tallies.values()
        )
        n_sessions = tallies_doc.get("n_sessions")
        source = str(args.tallies_file)
        print(f"Loaded {len(tallies)} distinct edits ({n_edits} votes) from {source}")
    else:
        edits = walk_plans(args.sessions_root)
        n_edits = len(edits)
        n_sessions = len({sid for sid, _ in edits})
        print(f"Walked {args.sessions_root}: {n_sessions} sessions, {n_edits} edits")
        if n_edits == 0:
            print("No edits found — nothing to tally.", file=sys.stderr)
            return 1
        write_raw_edits(edits, out_dir / "raw_edits.jsonl")
        tallies = tally_edits(edits)
        audit_tallies = audit_tally_edits(edits)
        source = str(args.sessions_root)

    raw_tallies_path = out_dir / "raw_tallies.json"
    raw_tallies_path.write_text(
        json.dumps(
            {
                "n_sessions": n_sessions,
                "n_edits": n_edits,
                "source": source,
                "tallies": serialise_tallies(tallies),
                "audit_tallies": serialise_tallies(audit_tallies),
            },
            indent=2,
        )
    )

    consensus = pick_consensus(
        tallies,
        min_votes=args.min_votes,
        min_majority=args.min_majority,
    )
    consensus["deferred_to_m3"] = build_deferred_to_m3(audit_tallies)
    consensus_doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source,
        "n_sessions": n_sessions,
        "n_edits": n_edits,
        "thresholds": {
            "min_votes": args.min_votes,
            "min_majority": args.min_majority,
        },
        "consensus": consensus,
    }
    consensus_path = out_dir / "consensus_edits.json"
    consensus_path.write_text(json.dumps(consensus_doc, indent=2))

    # ── Summary ──────────────────────────────────────────────────────────────
    print()
    print(f"Raw tallies → {raw_tallies_path}")
    print(f"Consensus   → {consensus_path}")
    print()
    print(f"Scalar consensus edits ({len(consensus['scalar_edits'])}):")
    for e in consensus["scalar_edits"]:
        print(
            f"  {e['op']:20} {e['target']:30} = {e['value']!r:10}  "
            f"({e['votes']}/{e['total_votes_in_group']} votes, "
            f"{e['majority_share']:.0%} share)"
        )
    if consensus["remove_tools"]:
        print(f"Tools to remove ({len(consensus['remove_tools'])}):")
        for t in consensus["remove_tools"]:
            print(f"  {t['tool_name']:20} ({t['votes']} votes)")
    if consensus["add_tools"]:
        print(f"Tools to add ({len(consensus['add_tools'])}):")
        for t in consensus["add_tools"]:
            print(f"  {t['tool_name']:20} ({t['votes']} votes)")
    deferred = consensus["deferred_to_m3"]
    print(
        f"Deferred to M3: {len(deferred['patch_system_prompt'])} prompt patches / "
        f"{len(deferred['replace_system_prompt'])} replace_prompts / "
        f"{len(deferred['edit_few_shot_exemplars'])} few_shot / "
        f"{len(deferred['edit_tool_description'])} tool_descs"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
