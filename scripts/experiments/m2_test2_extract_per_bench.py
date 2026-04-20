#!/usr/bin/env python3
"""M2 Test 2: Extract per-benchmark consensus edits from M1 sessions.

Instead of global consensus (used in M2 base run), filter M1 edit proposals
by which benchmark the session targeted, and produce benchmark-specific
consensus values. Tests the hypothesis: benchmark-scoped distillation beats
global consensus.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

RESULTS_ROOT = Path("results/neurips-2026/agent-optimization/distillation")
OUT_DIR = Path("results/neurips-2026/distillation-m2/test2")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def benchmark_from_config_name(cfg_name: str) -> str | None:
    """Parse benchmark from config name (e.g. opus-9b-tc15-C2 -> toolcall15)."""
    parts = cfg_name.split("-")
    bench_map = {"pb": "pinchbench", "tc15": "toolcall15", "tb": "taubench"}
    for p in parts:
        if p in bench_map:
            return bench_map[p]
    return None


per_bench_edits: dict[str, list[dict]] = defaultdict(list)
session_count_per_bench: Counter = Counter()

for plan_path in RESULTS_ROOT.rglob("plan.json"):
    parts = plan_path.parts
    exp_name = cfg_name = None
    for i, p in enumerate(parts):
        if p.startswith("exp"):
            exp_name = p
            cfg_name = parts[i + 1] if i + 1 < len(parts) else None
            break
    if not cfg_name:
        continue
    bench = benchmark_from_config_name(cfg_name)
    if not bench:
        continue

    plan = json.loads(plan_path.read_text())
    session_count_per_bench[bench] += 1
    for e in plan.get("edits", []):
        per_bench_edits[bench].append(e)

# For each benchmark, compute consensus on the "applicable" edit types
def edit_consensus(edits: list[dict]) -> dict:
    consensus = {}
    # Temperature
    temp_votes = Counter(
        e["payload"]["value"]
        for e in edits
        if e.get("op") == "set_model_param"
        and e.get("payload", {}).get("param") == "temperature"
    )
    consensus["temperature"] = {
        "value": temp_votes.most_common(1)[0][0] if temp_votes else None,
        "votes": dict(temp_votes.most_common(5)),
    }
    # max_turns
    mt_votes = Counter(
        e["payload"]["value"]
        for e in edits
        if e.get("op") == "set_agent_param"
        and e.get("payload", {}).get("param") == "max_turns"
    )
    consensus["max_turns"] = {
        "value": mt_votes.most_common(1)[0][0] if mt_votes else None,
        "votes": dict(mt_votes.most_common(5)),
    }
    # Remove tools (threshold: any with >= 2 votes)
    remove_votes = Counter(
        e["payload"].get("tool_name", "?")
        for e in edits
        if e.get("op") == "remove_tool_from_agent"
    )
    consensus["remove_tools"] = {
        "tools": [t for t, n in remove_votes.most_common() if n >= 2],
        "votes": dict(remove_votes),
    }
    # Add tools
    add_votes = Counter(
        e["payload"].get("tool_name", "?")
        for e in edits
        if e.get("op") == "add_tool_to_agent"
    )
    consensus["add_tools"] = {
        "tools": [t for t, n in add_votes.most_common() if n >= 2],
        "votes": dict(add_votes),
    }
    return consensus


print("=" * 80)
print("Per-benchmark M1 edit consensus")
print("=" * 80)
all_consensus = {}
for bench in ["pinchbench", "toolcall15", "taubench"]:
    edits = per_bench_edits.get(bench, [])
    c = edit_consensus(edits)
    all_consensus[bench] = {
        "sessions": session_count_per_bench[bench],
        "total_edits": len(edits),
        "consensus": c,
    }
    print(f"\n{bench} ({session_count_per_bench[bench]} sessions, {len(edits)} edits):")
    print(f"  temperature: {c['temperature']['value']}  votes: {c['temperature']['votes']}")
    print(f"  max_turns:   {c['max_turns']['value']}  votes: {c['max_turns']['votes']}")
    print(f"  remove:      {c['remove_tools']['tools']}  votes: {c['remove_tools']['votes']}")
    print(f"  add:         {c['add_tools']['tools']}  votes: {c['add_tools']['votes']}")

# Save consensus JSON for the config generator to consume
out = OUT_DIR / "per_benchmark_consensus.json"
out.write_text(json.dumps(all_consensus, indent=2, default=str))
print(f"\nSaved to {out}")

# Also note: GAIA, liveresearch, liveresearchbench, taubench-telecom, livecodebench
# were NOT used as M1 benchmark targets (M1 only targeted pb/tc15/tb).
# For those we have no benchmark-specific consensus — need global consensus OR
# pick the "closest" benchmark type:
#   - GAIA (agentic reasoning) ~ taubench (closest agent-based trace source)
#   - liveresearch (deep research) ~ taubench (monitor_operative agent)
#   - liveresearchbench (reasoning, direct) ~ toolcall15 (direct backend)
#   - taubench-telecom ~ taubench (same benchmark, different split)
#   - livecodebench (coding, direct) ~ toolcall15 (direct backend)
print()
print("Cross-benchmark mapping (for benchmarks not in M1 target set):")
print("  gaia → taubench (agent + reasoning)")
print("  liveresearch (DRB) → taubench (agent + multi-turn)")
print("  liveresearchbench (Salesforce) → toolcall15 (direct backend)")
print("  taubench-telecom → taubench (same benchmark, different split)")
print("  livecodebench → toolcall15 (direct backend)")
