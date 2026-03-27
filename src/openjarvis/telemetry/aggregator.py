"""Read-only telemetry aggregation — query stored inference records."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ModelStats:
    """Aggregated statistics for a single model."""

    model_id: str = ""
    call_count: int = 0
    total_tokens: int = 0
    prompt_tokens: int = 0
    prompt_tokens_evaluated: int = 0
    completion_tokens: int = 0
    total_latency: float = 0.0
    avg_latency: float = 0.0
    total_cost: float = 0.0
    avg_ttft: float = 0.0
    total_energy_joules: float = 0.0
    avg_gpu_utilization_pct: float = 0.0
    avg_throughput_tok_per_sec: float = 0.0
    avg_tokens_per_joule: float = 0.0
    avg_energy_per_output_token_joules: float = 0.0
    avg_throughput_per_watt: float = 0.0
    total_prefill_energy_joules: float = 0.0
    total_decode_energy_joules: float = 0.0
    avg_mean_itl_ms: float = 0.0
    avg_median_itl_ms: float = 0.0
    avg_p95_itl_ms: float = 0.0


@dataclass(slots=True)
class EngineStats:
    """Aggregated statistics for a single engine backend."""

    engine: str = ""
    call_count: int = 0
    total_tokens: int = 0
    total_latency: float = 0.0
    avg_latency: float = 0.0
    total_cost: float = 0.0
    avg_ttft: float = 0.0
    total_energy_joules: float = 0.0
    avg_gpu_utilization_pct: float = 0.0
    avg_throughput_tok_per_sec: float = 0.0
    avg_tokens_per_joule: float = 0.0
    avg_energy_per_output_token_joules: float = 0.0
    avg_throughput_per_watt: float = 0.0
    total_prefill_energy_joules: float = 0.0
    total_decode_energy_joules: float = 0.0
    avg_mean_itl_ms: float = 0.0
    avg_median_itl_ms: float = 0.0
    avg_p95_itl_ms: float = 0.0


@dataclass(slots=True)
class AggregatedStats:
    """Top-level summary combining per-model and per-engine stats."""

    total_calls: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    total_latency: float = 0.0
    total_energy_joules: float = 0.0
    avg_throughput_tok_per_sec: float = 0.0
    avg_gpu_utilization_pct: float = 0.0
    avg_energy_per_output_token_joules: float = 0.0
    avg_throughput_per_watt: float = 0.0
    total_prefill_energy_joules: float = 0.0
    total_decode_energy_joules: float = 0.0
    avg_mean_itl_ms: float = 0.0
    avg_median_itl_ms: float = 0.0
    avg_p95_itl_ms: float = 0.0
    per_model: List[ModelStats] = field(default_factory=list)
    per_engine: List[EngineStats] = field(default_factory=list)


class TelemetryAggregator:
    """Read-only query layer over the telemetry SQLite database."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row

    @staticmethod
    def _time_filter(
        since: Optional[float] = None,
        until: Optional[float] = None,
    ) -> tuple[str, list[Any]]:
        """Build a WHERE clause fragment for time-range filtering."""
        clauses: list[str] = []
        params: list[Any] = []
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until is not None:
            clauses.append("timestamp <= ?")
            params.append(until)
        if clauses:
            return " WHERE " + " AND ".join(clauses), params
        return "", params

    def _safe_col(self, col_name: str) -> bool:
        """Check if a column exists in the telemetry table."""
        try:
            self._conn.execute(f"SELECT {col_name} FROM telemetry LIMIT 0")
            return True
        except sqlite3.OperationalError as exc:
            logger.debug("Telemetry aggregator table check failed: %s", exc)
            return False

    def per_model_stats(
        self,
        *,
        since: Optional[float] = None,
        until: Optional[float] = None,
    ) -> List[ModelStats]:
        where, params = self._time_filter(since, until)

        # Build optional columns for new fields (graceful on old DBs)
        extra_cols = ""
        has_pte = self._safe_col("prompt_tokens_evaluated")
        has_tpj = self._safe_col("tokens_per_joule")
        has_derived = self._safe_col("energy_per_output_token_joules")
        has_phase = self._safe_col("prefill_energy_joules")
        has_itl = self._safe_col("mean_itl_ms")

        if has_pte:
            extra_cols += ", SUM(prompt_tokens_evaluated) AS prompt_tokens_evaluated"
        if has_tpj:
            extra_cols += ", AVG(tokens_per_joule) AS avg_tokens_per_joule"
        if has_derived:
            extra_cols += (
                ", AVG(energy_per_output_token_joules)"
                " AS avg_energy_per_output_token_joules"
                ", AVG(throughput_per_watt) AS avg_throughput_per_watt"
            )
        if has_phase:
            extra_cols += (
                ", SUM(prefill_energy_joules) AS total_prefill_energy_joules"
                ", SUM(decode_energy_joules) AS total_decode_energy_joules"
            )
        if has_itl:
            extra_cols += (
                ", AVG(mean_itl_ms) AS avg_mean_itl_ms"
                ", AVG(median_itl_ms) AS avg_median_itl_ms"
                ", AVG(p95_itl_ms) AS avg_p95_itl_ms"
            )

        sql = (
            "SELECT model_id,"
            " COUNT(*) AS call_count,"
            " SUM(total_tokens) AS total_tokens,"
            " SUM(prompt_tokens) AS prompt_tokens,"
            " SUM(completion_tokens) AS completion_tokens,"
            " SUM(latency_seconds) AS total_latency,"
            " AVG(latency_seconds) AS avg_latency,"
            " SUM(cost_usd) AS total_cost,"
            " AVG(ttft) AS avg_ttft,"
            " SUM(energy_joules) AS total_energy_joules,"
            " AVG(gpu_utilization_pct) AS avg_gpu_utilization_pct,"
            " AVG(throughput_tok_per_sec) AS avg_throughput_tok_per_sec"
            f"{extra_cols}"
            f" FROM telemetry{where}"
            " GROUP BY model_id ORDER BY call_count DESC"
        )
        rows = self._conn.execute(sql, params).fetchall()
        result = []
        for r in rows:
            ms = ModelStats(
                model_id=r["model_id"],
                call_count=r["call_count"],
                total_tokens=r["total_tokens"] or 0,
                prompt_tokens=r["prompt_tokens"] or 0,
                completion_tokens=r["completion_tokens"] or 0,
                total_latency=r["total_latency"] or 0.0,
                avg_latency=r["avg_latency"] or 0.0,
                total_cost=r["total_cost"] or 0.0,
                avg_ttft=r["avg_ttft"] or 0.0,
                total_energy_joules=r["total_energy_joules"] or 0.0,
                avg_gpu_utilization_pct=r["avg_gpu_utilization_pct"] or 0.0,
                avg_throughput_tok_per_sec=r["avg_throughput_tok_per_sec"] or 0.0,
            )
            if has_pte:
                ms.prompt_tokens_evaluated = r["prompt_tokens_evaluated"] or 0
            if has_tpj:
                ms.avg_tokens_per_joule = r["avg_tokens_per_joule"] or 0.0
            if has_derived:
                ms.avg_energy_per_output_token_joules = (
                    r["avg_energy_per_output_token_joules"] or 0.0
                )
                ms.avg_throughput_per_watt = r["avg_throughput_per_watt"] or 0.0
            if has_phase:
                ms.total_prefill_energy_joules = r["total_prefill_energy_joules"] or 0.0
                ms.total_decode_energy_joules = r["total_decode_energy_joules"] or 0.0
            if has_itl:
                ms.avg_mean_itl_ms = r["avg_mean_itl_ms"] or 0.0
                ms.avg_median_itl_ms = r["avg_median_itl_ms"] or 0.0
                ms.avg_p95_itl_ms = r["avg_p95_itl_ms"] or 0.0
            result.append(ms)
        return result

    def per_engine_stats(
        self,
        *,
        since: Optional[float] = None,
        until: Optional[float] = None,
    ) -> List[EngineStats]:
        where, params = self._time_filter(since, until)

        extra_cols = ""
        has_tpj = self._safe_col("tokens_per_joule")
        has_derived = self._safe_col("energy_per_output_token_joules")
        has_phase = self._safe_col("prefill_energy_joules")
        has_itl = self._safe_col("mean_itl_ms")

        if has_tpj:
            extra_cols += ", AVG(tokens_per_joule) AS avg_tokens_per_joule"
        if has_derived:
            extra_cols += (
                ", AVG(energy_per_output_token_joules)"
                " AS avg_energy_per_output_token_joules"
                ", AVG(throughput_per_watt) AS avg_throughput_per_watt"
            )
        if has_phase:
            extra_cols += (
                ", SUM(prefill_energy_joules) AS total_prefill_energy_joules"
                ", SUM(decode_energy_joules) AS total_decode_energy_joules"
            )
        if has_itl:
            extra_cols += (
                ", AVG(mean_itl_ms) AS avg_mean_itl_ms"
                ", AVG(median_itl_ms) AS avg_median_itl_ms"
                ", AVG(p95_itl_ms) AS avg_p95_itl_ms"
            )

        sql = (
            "SELECT engine,"
            " COUNT(*) AS call_count,"
            " SUM(total_tokens) AS total_tokens,"
            " SUM(latency_seconds) AS total_latency,"
            " AVG(latency_seconds) AS avg_latency,"
            " SUM(cost_usd) AS total_cost,"
            " AVG(ttft) AS avg_ttft,"
            " SUM(energy_joules) AS total_energy_joules,"
            " AVG(gpu_utilization_pct) AS avg_gpu_utilization_pct,"
            " AVG(throughput_tok_per_sec) AS avg_throughput_tok_per_sec"
            f"{extra_cols}"
            f" FROM telemetry{where}"
            " GROUP BY engine ORDER BY call_count DESC"
        )
        rows = self._conn.execute(sql, params).fetchall()
        result = []
        for r in rows:
            es = EngineStats(
                engine=r["engine"],
                call_count=r["call_count"],
                total_tokens=r["total_tokens"] or 0,
                total_latency=r["total_latency"] or 0.0,
                avg_latency=r["avg_latency"] or 0.0,
                total_cost=r["total_cost"] or 0.0,
                avg_ttft=r["avg_ttft"] or 0.0,
                total_energy_joules=r["total_energy_joules"] or 0.0,
                avg_gpu_utilization_pct=r["avg_gpu_utilization_pct"] or 0.0,
                avg_throughput_tok_per_sec=r["avg_throughput_tok_per_sec"] or 0.0,
            )
            if has_tpj:
                es.avg_tokens_per_joule = r["avg_tokens_per_joule"] or 0.0
            if has_derived:
                es.avg_energy_per_output_token_joules = (
                    r["avg_energy_per_output_token_joules"] or 0.0
                )
                es.avg_throughput_per_watt = r["avg_throughput_per_watt"] or 0.0
            if has_phase:
                es.total_prefill_energy_joules = r["total_prefill_energy_joules"] or 0.0
                es.total_decode_energy_joules = r["total_decode_energy_joules"] or 0.0
            if has_itl:
                es.avg_mean_itl_ms = r["avg_mean_itl_ms"] or 0.0
                es.avg_median_itl_ms = r["avg_median_itl_ms"] or 0.0
                es.avg_p95_itl_ms = r["avg_p95_itl_ms"] or 0.0
            result.append(es)
        return result

    def top_models(
        self,
        n: int = 5,
        *,
        since: Optional[float] = None,
    ) -> List[ModelStats]:
        stats = self.per_model_stats(since=since)
        return stats[:n]

    def summary(
        self,
        *,
        since: Optional[float] = None,
        until: Optional[float] = None,
    ) -> AggregatedStats:
        model_stats = self.per_model_stats(since=since, until=until)
        engine_stats = self.per_engine_stats(since=since, until=until)
        total_calls = sum(m.call_count for m in model_stats)

        def _weighted_avg(attr: str) -> float:
            if total_calls == 0:
                return 0.0
            return (
                sum(getattr(m, attr) * m.call_count for m in model_stats) / total_calls
            )

        return AggregatedStats(
            total_calls=total_calls,
            total_tokens=sum(m.total_tokens for m in model_stats),
            total_cost=sum(m.total_cost for m in model_stats),
            total_latency=sum(m.total_latency for m in model_stats),
            total_energy_joules=sum(m.total_energy_joules for m in model_stats),
            avg_throughput_tok_per_sec=_weighted_avg("avg_throughput_tok_per_sec"),
            avg_gpu_utilization_pct=_weighted_avg("avg_gpu_utilization_pct"),
            avg_energy_per_output_token_joules=_weighted_avg(
                "avg_energy_per_output_token_joules"
            ),
            avg_throughput_per_watt=_weighted_avg("avg_throughput_per_watt"),
            total_prefill_energy_joules=sum(
                m.total_prefill_energy_joules for m in model_stats
            ),
            total_decode_energy_joules=sum(
                m.total_decode_energy_joules for m in model_stats
            ),
            avg_mean_itl_ms=_weighted_avg("avg_mean_itl_ms"),
            avg_median_itl_ms=_weighted_avg("avg_median_itl_ms"),
            avg_p95_itl_ms=_weighted_avg("avg_p95_itl_ms"),
            per_model=model_stats,
            per_engine=engine_stats,
        )

    def per_batch_stats(
        self,
        *,
        since: Optional[float] = None,
        until: Optional[float] = None,
        exclude_warmup: bool = False,
    ) -> List[Dict[str, Any]]:
        """Aggregate telemetry by batch_id.

        Returns list of dicts with batch_id, total_requests, total_tokens,
        total_energy_joules, energy_per_token_joules.
        """
        clauses: list[str] = ["batch_id != ''"]
        params: list[Any] = []
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until is not None:
            clauses.append("timestamp <= ?")
            params.append(until)
        if exclude_warmup:
            clauses.append("is_warmup = 0")
        where = " WHERE " + " AND ".join(clauses)

        sql = (
            "SELECT batch_id,"
            " COUNT(*) AS total_requests,"
            " SUM(prompt_tokens + completion_tokens) AS total_tokens,"
            " SUM(energy_joules) AS total_energy_joules"
            f" FROM telemetry{where}"
            " GROUP BY batch_id ORDER BY total_requests DESC"
        )
        rows = self._conn.execute(sql, params).fetchall()
        results: List[Dict[str, Any]] = []
        for r in rows:
            total_tokens = r["total_tokens"] or 0
            total_energy = r["total_energy_joules"] or 0.0
            results.append(
                {
                    "batch_id": r["batch_id"],
                    "total_requests": r["total_requests"],
                    "total_tokens": total_tokens,
                    "total_energy_joules": total_energy,
                    "energy_per_token_joules": (
                        total_energy / total_tokens if total_tokens > 0 else 0.0
                    ),
                }
            )
        return results

    def export_records(
        self,
        *,
        since: Optional[float] = None,
        until: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        where, params = self._time_filter(since, until)
        sql = f"SELECT * FROM telemetry{where} ORDER BY timestamp"
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def record_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM telemetry").fetchone()
        return row[0] if row else 0

    def clear(self) -> int:
        count = self.record_count()
        self._conn.execute("DELETE FROM telemetry")
        self._conn.commit()
        return count

    def close(self) -> None:
        self._conn.close()


__all__ = [
    "AggregatedStats",
    "EngineStats",
    "ModelStats",
    "TelemetryAggregator",
]
