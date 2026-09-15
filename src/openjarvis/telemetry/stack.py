"""Privacy-safe resource sampling for a local OpenJarvis process tree."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

_SCHEMA = "openjarvis.stack-benchmark.v1"


@dataclass(frozen=True)
class ProcessCounters:
    """The scheduler counters needed to calculate CPU usage."""

    ppid: int
    cpu_ticks: int


@dataclass(frozen=True)
class ProcessMemory:
    """Resident and proportional resident memory for one process."""

    pss_kib: int
    rss_kib: int


@dataclass(frozen=True)
class StackSample:
    """One resource-only stack observation; never contains request content."""

    timestamp_ns: int
    pids: tuple[int, ...]
    pss_kib: int
    rss_kib: int
    cpu_percent_one_core: float
    cpu_percent_machine: float
    gpu_utilization_pct: float | None
    gpu_memory_used_mib: int | None

    def as_json_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["schema"] = _SCHEMA
        payload["pids"] = list(self.pids)
        return {key: payload[key] for key in sorted(payload)}


def _parse_proc_stat(text: str) -> ProcessCounters:
    """Parse ``/proc/<pid>/stat`` without being confused by a spaced comm."""

    try:
        fields = text.rsplit(")", 1)[1].split()
        return ProcessCounters(ppid=int(fields[1]), cpu_ticks=int(fields[11]) + int(fields[12]))
    except (IndexError, ValueError) as exc:
        raise ValueError("invalid proc stat") from exc


def read_process_counters(proc_root: Path = Path("/proc")) -> dict[int, ProcessCounters]:
    """Read process leaders from procfs, ignoring short-lived processes."""

    counters: dict[int, ProcessCounters] = {}
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return counters
    for entry in entries:
        if not entry.name.isdecimal():
            continue
        try:
            counters[int(entry.name)] = _parse_proc_stat((entry / "stat").read_text())
        except (OSError, ValueError):
            continue
    return counters


def descendant_pids(
    roots: Sequence[int], counters: Mapping[int, ProcessCounters]
) -> tuple[int, ...]:
    """Return live roots plus every live descendant exactly once, sorted by PID."""

    children: dict[int, list[int]] = {}
    for pid, counter in counters.items():
        children.setdefault(counter.ppid, []).append(pid)
    selected: set[int] = set()
    pending = list(roots)
    while pending:
        pid = pending.pop()
        if pid in selected or pid not in counters:
            continue
        selected.add(pid)
        pending.extend(children.get(pid, ()))
    return tuple(sorted(selected))


def _read_memory(pid: int, proc_root: Path) -> ProcessMemory:
    pss_kib = 0
    rss_kib = 0
    try:
        for line in (proc_root / str(pid) / "smaps_rollup").read_text().splitlines():
            if line.startswith("Pss:"):
                pss_kib = int(line.split()[1])
            elif line.startswith("Rss:"):
                rss_kib = int(line.split()[1])
    except (OSError, IndexError, ValueError):
        try:
            for line in (proc_root / str(pid) / "status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    rss_kib = int(line.split()[1])
                    break
        except (OSError, IndexError, ValueError):
            pass
    return ProcessMemory(pss_kib=pss_kib, rss_kib=rss_kib)


def read_process_memory(
    pids: Sequence[int], proc_root: Path = Path("/proc")
) -> dict[int, ProcessMemory]:
    """Read PSS/RSS for requested process leaders, tolerating process exit."""

    return {pid: _read_memory(pid, proc_root) for pid in pids}


def read_gpu_snapshot() -> tuple[float | None, int | None]:
    """Return mean GPU utilization and total used VRAM, or ``None`` if unavailable."""

    try:
        import pynvml

        pynvml.nvmlInit()
        try:
            device_count = pynvml.nvmlDeviceGetCount()
            if device_count == 0:
                return None, None
            utilizations = []
            used_bytes = 0
            for index in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(index)
                utilizations.append(float(pynvml.nvmlDeviceGetUtilizationRates(handle).gpu))
                used_bytes += int(pynvml.nvmlDeviceGetMemoryInfo(handle).used)
            return sum(utilizations) / len(utilizations), used_bytes // (1024 * 1024)
        finally:
            pynvml.nvmlShutdown()
    except Exception:
        return None, None


def make_stack_sample(
    *,
    timestamp_ns: int,
    roots: Sequence[int],
    before: Mapping[int, ProcessCounters],
    after: Mapping[int, ProcessCounters],
    memory: Mapping[int, ProcessMemory],
    elapsed_seconds: float,
    clock_ticks_per_second: int,
    logical_cpus: int,
    gpu_utilization_pct: float | None,
    gpu_memory_used_mib: int | None,
) -> StackSample:
    """Build one sample from two procfs counter snapshots."""

    if elapsed_seconds <= 0:
        raise ValueError("elapsed_seconds must be positive")
    if clock_ticks_per_second <= 0 or logical_cpus <= 0:
        raise ValueError("clock and CPU counts must be positive")
    pids = descendant_pids(roots, after)
    cpu_ticks = sum(
        max(0, after[pid].cpu_ticks - before[pid].cpu_ticks)
        for pid in pids
        if pid in before
    )
    one_core = cpu_ticks * 100.0 / (elapsed_seconds * clock_ticks_per_second)
    return StackSample(
        timestamp_ns=timestamp_ns,
        pids=pids,
        pss_kib=sum(memory.get(pid, ProcessMemory(0, 0)).pss_kib for pid in pids),
        rss_kib=sum(memory.get(pid, ProcessMemory(0, 0)).rss_kib for pid in pids),
        cpu_percent_one_core=one_core,
        cpu_percent_machine=one_core / logical_cpus,
        gpu_utilization_pct=gpu_utilization_pct,
        gpu_memory_used_mib=gpu_memory_used_mib,
    )


def _percentile(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot summarize no samples")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile / 100.0
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _summary(values: Sequence[float]) -> dict[str, float]:
    return {
        "p50": _percentile(values, 50),
        "p95": _percentile(values, 95),
        "p99": _percentile(values, 99),
        "peak": max(values),
    }


def summarize_samples(samples: Sequence[StackSample]) -> dict[str, object]:
    """Summarize raw samples; do not average independently calculated percentiles."""

    if not samples:
        raise ValueError("cannot summarize no samples")
    result: dict[str, object] = {
        "schema": _SCHEMA,
        "samples": len(samples),
        "cpu_percent_one_core": _summary([s.cpu_percent_one_core for s in samples]),
        "cpu_percent_machine": _summary([s.cpu_percent_machine for s in samples]),
        "pss_mib": _summary([s.pss_kib / 1024.0 for s in samples]),
        "rss_mib": _summary([s.rss_kib / 1024.0 for s in samples]),
        "process_count": max(len(s.pids) for s in samples),
    }
    gpu_utilization = [s.gpu_utilization_pct for s in samples if s.gpu_utilization_pct is not None]
    gpu_memory = [s.gpu_memory_used_mib for s in samples if s.gpu_memory_used_mib is not None]
    if gpu_utilization:
        result["gpu_utilization_pct"] = _summary(gpu_utilization)
    if gpu_memory:
        result["gpu_memory_used_mib"] = _summary(gpu_memory)
    return result


def write_jsonl(path: Path, samples: Sequence[StackSample]) -> None:
    """Write one privacy-safe resource sample per JSONL line."""

    with path.open("w", encoding="utf-8") as stream:
        for sample in samples:
            stream.write(json.dumps(sample.as_json_dict(), sort_keys=True) + "\n")


def collect_stack_samples(
    roots: Sequence[int],
    *,
    seconds: float,
    interval_seconds: float,
    proc_root: Path = Path("/proc"),
    clock_ns: Callable[[], int] = time.monotonic_ns,
    sleep: Callable[[float], None] = time.sleep,
    gpu_reader: Callable[[], tuple[float | None, int | None]] = read_gpu_snapshot,
) -> list[StackSample]:
    """Sample a live process tree without mutating the measured processes."""

    if seconds <= 0 or interval_seconds <= 0:
        raise ValueError("seconds and interval_seconds must be positive")
    ticks_per_second = int(os.sysconf("SC_CLK_TCK"))
    logical_cpus = os.cpu_count() or 1
    before = read_process_counters(proc_root)
    if not descendant_pids(roots, before):
        raise ProcessLookupError(f"no requested root PID is live: {tuple(roots)}")
    started_ns = clock_ns()
    previous_ns = started_ns
    samples: list[StackSample] = []
    while (clock_ns() - started_ns) < int(seconds * 1_000_000_000):
        sleep(interval_seconds)
        now_ns = clock_ns()
        after = read_process_counters(proc_root)
        pids = descendant_pids(roots, after)
        if not pids:
            raise ProcessLookupError(f"all requested root PIDs exited: {tuple(roots)}")
        memory = read_process_memory(pids, proc_root)
        gpu_utilization, gpu_memory = gpu_reader()
        samples.append(
            make_stack_sample(
                timestamp_ns=now_ns,
                roots=roots,
                before=before,
                after=after,
                memory=memory,
                elapsed_seconds=(now_ns - previous_ns) / 1_000_000_000,
                clock_ticks_per_second=ticks_per_second,
                logical_cpus=logical_cpus,
                gpu_utilization_pct=gpu_utilization,
                gpu_memory_used_mib=gpu_memory,
            )
        )
        before = after
        previous_ns = now_ns
    return samples


__all__ = [
    "ProcessCounters",
    "ProcessMemory",
    "StackSample",
    "collect_stack_samples",
    "descendant_pids",
    "make_stack_sample",
    "read_gpu_snapshot",
    "read_process_counters",
    "read_process_memory",
    "summarize_samples",
    "write_jsonl",
]
