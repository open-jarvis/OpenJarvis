"""Google Sheets experiment tracker for the eval framework."""

from __future__ import annotations

import logging
import time
from typing import Any, List, Optional

from openjarvis.evals.core.tracker import ResultTracker
from openjarvis.evals.core.types import EvalResult, MetricStats, RunConfig, RunSummary

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    gspread = None  # type: ignore[assignment]
    Credentials = None  # type: ignore[assignment,misc]

LOGGER = logging.getLogger(__name__)

# Canonical column order for the summary row.
SHEET_COLUMNS: List[str] = [
    "timestamp",
    "benchmark",
    "model",
    "backend",
    "total_samples",
    "scored_samples",
    "correct",
    "accuracy",
    "errors",
    "mean_latency_seconds",
    "total_cost_usd",
    "total_energy_joules",
    "avg_power_watts",
    "total_input_tokens",
    "total_output_tokens",
    "latency_mean",
    "latency_p90",
    "latency_p95",
    "energy_mean",
    "energy_p90",
    "throughput_mean",
    "throughput_p90",
    "ipw_mean",
    "ipj_mean",
    "mfu_mean",
    "mbu_mean",
    "ttft_mean",
    "ttft_p90",
    "gpu_utilization_mean",
]


def _stat_val(ms: Optional[MetricStats], attr: str) -> Any:
    """Safely extract a stat value from a MetricStats, returning '' if None."""
    if ms is None:
        return ""
    return getattr(ms, attr, "")


class SheetsTracker(ResultTracker):
    """Appends a summary row to a Google Sheet after each eval run."""

    def __init__(
        self,
        spreadsheet_id: str,
        worksheet: str = "Results",
        credentials_path: str = "",
    ) -> None:
        if gspread is None:
            raise ImportError(
                "gspread is not installed. Install it with: uv sync --extra eval-sheets"
            )
        self._spreadsheet_id = spreadsheet_id
        self._worksheet_name = worksheet
        self._credentials_path = credentials_path

    def on_run_start(self, config: RunConfig) -> None:
        pass

    def on_result(self, result: EvalResult, config: RunConfig) -> None:
        # No-op: summary-only to avoid excessive API calls.
        pass

    def on_summary(self, summary: RunSummary) -> None:
        row = self._build_row(summary)
        try:
            gc = self._authorize()
            spreadsheet = gc.open_by_key(self._spreadsheet_id)
            try:
                ws = spreadsheet.worksheet(self._worksheet_name)
            except gspread.exceptions.WorksheetNotFound:
                ws = spreadsheet.add_worksheet(
                    title=self._worksheet_name,
                    rows=1000,
                    cols=len(SHEET_COLUMNS),
                )
            # Ensure header row exists (idempotent)
            existing = ws.row_values(1)
            if not existing or existing[0] != SHEET_COLUMNS[0]:
                ws.update(range_name="A1", values=[SHEET_COLUMNS])
            ws.append_row(row, value_input_option="RAW")
            LOGGER.info("Appended summary row to Google Sheet")
        except Exception as exc:
            LOGGER.warning("SheetsTracker.on_summary failed: %s", exc)

    def on_run_end(self) -> None:
        pass

    def _authorize(self):
        """Authenticate with Google Sheets API."""
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        if self._credentials_path:
            creds = Credentials.from_service_account_file(
                self._credentials_path,
                scopes=scopes,
            )
        else:
            # Fall back to Application Default Credentials
            import google.auth

            creds, _ = google.auth.default(scopes=scopes)
        return gspread.authorize(creds)

    def _build_row(self, s: RunSummary) -> List[Any]:
        """Build a flat row matching SHEET_COLUMNS order."""
        return [
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            s.benchmark,
            s.model,
            s.backend,
            s.total_samples,
            s.scored_samples,
            s.correct,
            s.accuracy,
            s.errors,
            s.mean_latency_seconds,
            s.total_cost_usd,
            s.total_energy_joules,
            s.avg_power_watts,
            s.total_input_tokens,
            s.total_output_tokens,
            _stat_val(s.latency_stats, "mean"),
            _stat_val(s.latency_stats, "p90"),
            _stat_val(s.latency_stats, "p95"),
            _stat_val(s.energy_stats, "mean"),
            _stat_val(s.energy_stats, "p90"),
            _stat_val(s.throughput_stats, "mean"),
            _stat_val(s.throughput_stats, "p90"),
            _stat_val(s.ipw_stats, "mean"),
            _stat_val(s.ipj_stats, "mean"),
            _stat_val(s.mfu_stats, "mean"),
            _stat_val(s.mbu_stats, "mean"),
            _stat_val(s.ttft_stats, "mean"),
            _stat_val(s.ttft_stats, "p90"),
            _stat_val(s.gpu_utilization_stats, "mean"),
        ]


__all__ = ["SheetsTracker", "SHEET_COLUMNS"]
