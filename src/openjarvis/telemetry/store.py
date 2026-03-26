"""SQLite-backed telemetry storage."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from openjarvis.core.events import Event, EventBus, EventType
from openjarvis.core.types import TelemetryRecord

logger = logging.getLogger(__name__)

_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS telemetry (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       REAL    NOT NULL,
    model_id        TEXT    NOT NULL,
    engine          TEXT    NOT NULL DEFAULT '',
    agent           TEXT    NOT NULL DEFAULT '',
    prompt_tokens   INTEGER NOT NULL DEFAULT 0,
    prompt_tokens_evaluated INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens    INTEGER NOT NULL DEFAULT 0,
    latency_seconds REAL    NOT NULL DEFAULT 0.0,
    ttft            REAL    NOT NULL DEFAULT 0.0,
    cost_usd        REAL    NOT NULL DEFAULT 0.0,
    energy_joules   REAL    NOT NULL DEFAULT 0.0,
    power_watts     REAL    NOT NULL DEFAULT 0.0,
    gpu_utilization_pct  REAL NOT NULL DEFAULT 0.0,
    gpu_memory_used_gb   REAL NOT NULL DEFAULT 0.0,
    gpu_temperature_c    REAL NOT NULL DEFAULT 0.0,
    throughput_tok_per_sec REAL NOT NULL DEFAULT 0.0,
    prefill_latency_seconds REAL NOT NULL DEFAULT 0.0,
    decode_latency_seconds  REAL NOT NULL DEFAULT 0.0,
    energy_method   TEXT    NOT NULL DEFAULT '',
    energy_vendor   TEXT    NOT NULL DEFAULT '',
    batch_id        TEXT    NOT NULL DEFAULT '',
    is_warmup       INTEGER NOT NULL DEFAULT 0,
    cpu_energy_joules    REAL NOT NULL DEFAULT 0.0,
    gpu_energy_joules    REAL NOT NULL DEFAULT 0.0,
    dram_energy_joules   REAL NOT NULL DEFAULT 0.0,
    tokens_per_joule     REAL NOT NULL DEFAULT 0.0,
    energy_per_output_token_joules REAL NOT NULL DEFAULT 0.0,
    throughput_per_watt  REAL NOT NULL DEFAULT 0.0,
    prefill_energy_joules REAL NOT NULL DEFAULT 0.0,
    decode_energy_joules REAL NOT NULL DEFAULT 0.0,
    mean_itl_ms          REAL NOT NULL DEFAULT 0.0,
    median_itl_ms        REAL NOT NULL DEFAULT 0.0,
    p90_itl_ms           REAL NOT NULL DEFAULT 0.0,
    p95_itl_ms           REAL NOT NULL DEFAULT 0.0,
    p99_itl_ms           REAL NOT NULL DEFAULT 0.0,
    std_itl_ms           REAL NOT NULL DEFAULT 0.0,
    is_streaming         INTEGER NOT NULL DEFAULT 0,
    metadata        TEXT    NOT NULL DEFAULT '{}'
);
"""

_INSERT = """\
INSERT INTO telemetry (
    timestamp, model_id, engine, agent,
    prompt_tokens, prompt_tokens_evaluated, completion_tokens, total_tokens,
    latency_seconds, ttft, cost_usd, energy_joules, power_watts,
    gpu_utilization_pct, gpu_memory_used_gb, gpu_temperature_c,
    throughput_tok_per_sec, prefill_latency_seconds, decode_latency_seconds,
    energy_method, energy_vendor, batch_id, is_warmup,
    cpu_energy_joules, gpu_energy_joules, dram_energy_joules,
    tokens_per_joule,
    energy_per_output_token_joules, throughput_per_watt,
    prefill_energy_joules, decode_energy_joules,
    mean_itl_ms, median_itl_ms, p90_itl_ms, p95_itl_ms, p99_itl_ms, std_itl_ms,
    is_streaming,
    metadata
) VALUES (
    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
    ?, ?, ?, ?, ?, ?, ?, ?, ?
)
"""

_MIGRATE_COLUMNS = [
    ("gpu_utilization_pct", "REAL NOT NULL DEFAULT 0.0"),
    ("gpu_memory_used_gb", "REAL NOT NULL DEFAULT 0.0"),
    ("gpu_temperature_c", "REAL NOT NULL DEFAULT 0.0"),
    ("throughput_tok_per_sec", "REAL NOT NULL DEFAULT 0.0"),
    ("prefill_latency_seconds", "REAL NOT NULL DEFAULT 0.0"),
    ("decode_latency_seconds", "REAL NOT NULL DEFAULT 0.0"),
    ("energy_method", "TEXT NOT NULL DEFAULT ''"),
    ("energy_vendor", "TEXT NOT NULL DEFAULT ''"),
    ("batch_id", "TEXT NOT NULL DEFAULT ''"),
    ("is_warmup", "INTEGER NOT NULL DEFAULT 0"),
    ("cpu_energy_joules", "REAL NOT NULL DEFAULT 0.0"),
    ("gpu_energy_joules", "REAL NOT NULL DEFAULT 0.0"),
    ("dram_energy_joules", "REAL NOT NULL DEFAULT 0.0"),
    ("tokens_per_joule", "REAL NOT NULL DEFAULT 0.0"),
    ("energy_per_output_token_joules", "REAL NOT NULL DEFAULT 0.0"),
    ("throughput_per_watt", "REAL NOT NULL DEFAULT 0.0"),
    ("prefill_energy_joules", "REAL NOT NULL DEFAULT 0.0"),
    ("decode_energy_joules", "REAL NOT NULL DEFAULT 0.0"),
    ("mean_itl_ms", "REAL NOT NULL DEFAULT 0.0"),
    ("median_itl_ms", "REAL NOT NULL DEFAULT 0.0"),
    ("p90_itl_ms", "REAL NOT NULL DEFAULT 0.0"),
    ("p95_itl_ms", "REAL NOT NULL DEFAULT 0.0"),
    ("p99_itl_ms", "REAL NOT NULL DEFAULT 0.0"),
    ("std_itl_ms", "REAL NOT NULL DEFAULT 0.0"),
    ("is_streaming", "INTEGER NOT NULL DEFAULT 0"),
    ("prompt_tokens_evaluated", "INTEGER NOT NULL DEFAULT 0"),
]


class TelemetryStore:
    """Append-only SQLite store for inference telemetry records."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        """Add new columns to existing databases (idempotent)."""
        for col_name, col_def in _MIGRATE_COLUMNS:
            try:
                self._conn.execute(
                    f"ALTER TABLE telemetry ADD COLUMN {col_name} {col_def}",
                )
            except sqlite3.OperationalError:
                pass  # Column already exists — safe to ignore
        self._conn.commit()

    def record(self, rec: TelemetryRecord) -> None:
        """Persist a single telemetry record."""
        self._conn.execute(
            _INSERT,
            (
                rec.timestamp,
                rec.model_id,
                rec.engine,
                rec.agent,
                rec.prompt_tokens,
                rec.prompt_tokens_evaluated,
                rec.completion_tokens,
                rec.total_tokens,
                rec.latency_seconds,
                rec.ttft,
                rec.cost_usd,
                rec.energy_joules,
                rec.power_watts,
                rec.gpu_utilization_pct,
                rec.gpu_memory_used_gb,
                rec.gpu_temperature_c,
                rec.throughput_tok_per_sec,
                rec.prefill_latency_seconds,
                rec.decode_latency_seconds,
                rec.energy_method,
                rec.energy_vendor,
                rec.batch_id,
                1 if rec.is_warmup else 0,
                rec.cpu_energy_joules,
                rec.gpu_energy_joules,
                rec.dram_energy_joules,
                rec.tokens_per_joule,
                rec.energy_per_output_token_joules,
                rec.throughput_per_watt,
                rec.prefill_energy_joules,
                rec.decode_energy_joules,
                rec.mean_itl_ms,
                rec.median_itl_ms,
                rec.p90_itl_ms,
                rec.p95_itl_ms,
                rec.p99_itl_ms,
                rec.std_itl_ms,
                1 if rec.is_streaming else 0,
                json.dumps(rec.metadata),
            ),
        )
        self._conn.commit()

    def subscribe_to_bus(self, bus: EventBus) -> None:
        """Subscribe to ``TELEMETRY_RECORD`` events on *bus*."""
        bus.subscribe(EventType.TELEMETRY_RECORD, self._on_event)

    def _on_event(self, event: Event) -> None:
        rec = event.data.get("record")
        if isinstance(rec, TelemetryRecord):
            try:
                self.record(rec)
            except Exception as exc:
                logger.debug("Failed to record telemetry event: %s", exc)

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    # -- helpers for querying (used by tests) --------------------------------

    def _fetchall(self, sql: str = "SELECT * FROM telemetry") -> list:
        return self._conn.execute(sql).fetchall()


__all__ = ["TelemetryStore"]
