"""Apple Health connector -- reads HealthKit SQLite DB or iPhone Health export XML.

Two data sources are tried in order:
1. HealthKit SQLite DB at ``~/Library/Health/healthdb_secure.sqlite`` (macOS
   with HealthKit sync enabled).
2. Health Export XML placed by the user at
   ``~/.openjarvis/connectors/apple_health_export/export.xml``.

Both are local-only; no API keys are needed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry

logger = logging.getLogger(__name__)

_DEFAULT_EXPORT_PATH = str(
    DEFAULT_CONFIG_DIR / "connectors" / "apple_health_export" / "export.xml"
)
_DEFAULT_HEALTHKIT_DB_PATH = str(
    Path.home() / "Library" / "Health" / "healthdb_secure.sqlite"
)

# HK record type identifiers we care about
_STEP_COUNT = "HKQuantityTypeIdentifierStepCount"
_SLEEP_ANALYSIS = "HKCategoryTypeIdentifierSleepAnalysis"
_HEART_RATE = "HKQuantityTypeIdentifierHeartRate"
_RESTING_HEART_RATE = "HKQuantityTypeIdentifierRestingHeartRate"
_ACTIVE_ENERGY = "HKQuantityTypeIdentifierActiveEnergyBurned"


def _parse_health_date(date_str: str) -> datetime:
    """Parse date strings from Apple Health export XML.

    Format is typically ``2024-03-15 08:00:00 -0700``.
    """
    # Strip sub-second precision if present, then parse
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        # Fallback: try ISO-8601
        return datetime.fromisoformat(date_str.strip())


def _day_key(dt: datetime) -> str:
    """Return ``YYYY-MM-DD`` for a datetime."""
    return dt.strftime("%Y-%m-%d")


def _format_duration(seconds: float) -> str:
    """Return a human-readable duration like ``7h 23m``."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    if hours and minutes:
        return f"{hours}h {minutes:02d}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


@ConnectorRegistry.register("apple_health")
class AppleHealthConnector(BaseConnector):
    """Sync health data from Apple Health (local files only)."""

    connector_id = "apple_health"
    display_name = "Apple Health"
    auth_type = "local"

    def __init__(
        self,
        *,
        export_path: str = _DEFAULT_EXPORT_PATH,
        healthkit_db_path: str = _DEFAULT_HEALTHKIT_DB_PATH,
    ) -> None:
        self._export_path = Path(export_path)
        self._healthkit_db_path = Path(healthkit_db_path)
        self._status = SyncStatus()

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        return self._healthkit_db_path.exists() or self._export_path.exists()

    def disconnect(self) -> None:
        # Local connector -- nothing to revoke.
        pass

    def sync(
        self, *, since: Optional[datetime] = None, cursor: Optional[str] = None
    ) -> Iterator[Document]:
        """Yield health Documents, preferring HealthKit DB over export XML."""
        self._status.state = "syncing"
        try:
            # Try HealthKit SQLite first
            if self._healthkit_db_path.exists():
                try:
                    yield from self._sync_healthkit_db(since=since)
                    self._status.state = "idle"
                    self._status.last_sync = datetime.now()
                    return
                except Exception:
                    logger.debug(
                        "HealthKit DB not readable, falling back to export XML",
                        exc_info=True,
                    )

            # Fall back to export XML
            if self._export_path.exists():
                yield from self._sync_export_xml(since=since)

            self._status.state = "idle"
            self._status.last_sync = datetime.now()
        except Exception as exc:
            self._status.state = "error"
            self._status.error = str(exc)
            raise

    def sync_status(self) -> SyncStatus:
        return self._status

    # ------------------------------------------------------------------
    # HealthKit SQLite DB
    # ------------------------------------------------------------------

    def _sync_healthkit_db(
        self, *, since: Optional[datetime] = None
    ) -> Iterator[Document]:
        """Read health data from the local HealthKit SQLite database."""
        conn = sqlite3.connect(str(self._healthkit_db_path))
        conn.row_factory = sqlite3.Row
        try:
            # Query quantity_samples joined with samples for step count,
            # heart rate, active energy.  The schema uses Apple's CF
            # absolute time (seconds since 2001-01-01).
            cf_epoch = datetime(2001, 1, 1, tzinfo=timezone.utc)
            since_cf = (
                (since - cf_epoch).total_seconds()
                if since and since.tzinfo
                else (
                    (since.replace(tzinfo=timezone.utc) - cf_epoch).total_seconds()
                    if since
                    else 0
                )
            )

            # Steps
            steps_by_day: Dict[str, float] = defaultdict(float)
            rows = conn.execute(
                """
                SELECT s.start_date, qs.quantity
                FROM samples s
                JOIN quantity_samples qs ON s.data_id = qs.data_id
                WHERE s.data_type = 7 AND s.start_date > ?
                """,
                (since_cf,),
            ).fetchall()
            for row in rows:
                dt = cf_epoch.replace(tzinfo=timezone.utc) + timedelta(
                    seconds=row["start_date"]
                )
                steps_by_day[_day_key(dt)] += row["quantity"]

            for day, total in sorted(steps_by_day.items()):
                yield Document(
                    doc_id=f"apple_health-steps-{day}",
                    source="apple_health",
                    doc_type="steps",
                    content=json.dumps({"date": day, "steps": int(total)}),
                    title=f"{int(total):,} steps",
                    timestamp=datetime.fromisoformat(day),
                    metadata={"data_type": "steps", "day": day},
                )
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Export XML
    # ------------------------------------------------------------------

    def _sync_export_xml(
        self, *, since: Optional[datetime] = None
    ) -> Iterator[Document]:
        """Stream-parse the Apple Health export XML and yield Documents."""
        steps_by_day: Dict[str, float] = defaultdict(float)
        sleep_by_day: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        hr_by_day: Dict[str, List[float]] = defaultdict(list)
        energy_by_day: Dict[str, float] = defaultdict(float)
        workouts: List[Dict[str, Any]] = []

        for event, elem in ET.iterparse(str(self._export_path), events=("end",)):
            tag = elem.tag

            if tag == "Record":
                rec_type = elem.get("type", "")
                start_str = elem.get("startDate", "")
                if not start_str:
                    elem.clear()
                    continue

                try:
                    start_dt = _parse_health_date(start_str)
                except (ValueError, TypeError):
                    elem.clear()
                    continue

                if since and start_dt.replace(tzinfo=None) < since.replace(tzinfo=None):
                    elem.clear()
                    continue

                day = _day_key(start_dt)

                if rec_type == _STEP_COUNT:
                    val = float(elem.get("value", 0))
                    steps_by_day[day] += val

                elif rec_type == _SLEEP_ANALYSIS:
                    end_str = elem.get("endDate", start_str)
                    try:
                        end_dt = _parse_health_date(end_str)
                    except (ValueError, TypeError):
                        end_dt = start_dt
                    sleep_by_day[day].append(
                        {
                            "start": start_str,
                            "end": end_str,
                            "value": elem.get("value", ""),
                            "duration_seconds": (end_dt - start_dt).total_seconds(),
                        }
                    )

                elif rec_type in (_HEART_RATE, _RESTING_HEART_RATE):
                    try:
                        hr_by_day[day].append(float(elem.get("value", 0)))
                    except (ValueError, TypeError):
                        pass

                elif rec_type == _ACTIVE_ENERGY:
                    try:
                        energy_by_day[day] += float(elem.get("value", 0))
                    except (ValueError, TypeError):
                        pass

                elem.clear()

            elif tag == "Workout":
                start_str = elem.get("startDate", "")
                if not start_str:
                    elem.clear()
                    continue

                try:
                    start_dt = _parse_health_date(start_str)
                except (ValueError, TypeError):
                    elem.clear()
                    continue

                if since and start_dt.replace(tzinfo=None) < since.replace(tzinfo=None):
                    elem.clear()
                    continue

                workouts.append(
                    {
                        "activity_type": elem.get("workoutActivityType", ""),
                        "duration_seconds": float(elem.get("duration", 0)),
                        "start": start_str,
                        "end": elem.get("endDate", ""),
                        "total_distance": elem.get("totalDistance", ""),
                        "total_energy_burned": elem.get("totalEnergyBurned", ""),
                    }
                )
                elem.clear()

            else:
                # Don't clear the root or other structural elements yet
                pass

        # Yield aggregated documents
        yield from self._yield_step_docs(steps_by_day)
        yield from self._yield_sleep_docs(sleep_by_day)
        yield from self._yield_hr_docs(hr_by_day)
        yield from self._yield_energy_docs(energy_by_day)
        yield from self._yield_workout_docs(workouts)

    # ------------------------------------------------------------------
    # Document builders
    # ------------------------------------------------------------------

    @staticmethod
    def _yield_step_docs(
        steps_by_day: Dict[str, float],
    ) -> Iterator[Document]:
        for day in sorted(steps_by_day):
            total = int(steps_by_day[day])
            yield Document(
                doc_id=f"apple_health-steps-{day}",
                source="apple_health",
                doc_type="steps",
                content=json.dumps({"date": day, "steps": total}),
                title=f"{total:,} steps",
                timestamp=datetime.fromisoformat(day),
                metadata={"data_type": "steps", "day": day},
            )

    @staticmethod
    def _yield_sleep_docs(
        sleep_by_day: Dict[str, List[Dict[str, Any]]],
    ) -> Iterator[Document]:
        for day in sorted(sleep_by_day):
            entries = sleep_by_day[day]
            total_seconds = sum(e["duration_seconds"] for e in entries)
            yield Document(
                doc_id=f"apple_health-sleep-{day}",
                source="apple_health",
                doc_type="sleep",
                content=json.dumps(
                    {"date": day, "total_seconds": total_seconds, "entries": entries}
                ),
                title=f"{_format_duration(total_seconds)} sleep",
                timestamp=datetime.fromisoformat(day),
                metadata={"data_type": "sleep", "day": day},
            )

    @staticmethod
    def _yield_hr_docs(
        hr_by_day: Dict[str, List[float]],
    ) -> Iterator[Document]:
        for day in sorted(hr_by_day):
            values = hr_by_day[day]
            avg = round(sum(values) / len(values), 1) if values else 0
            yield Document(
                doc_id=f"apple_health-heart_rate-{day}",
                source="apple_health",
                doc_type="heart_rate",
                content=json.dumps(
                    {
                        "date": day,
                        "avg_bpm": avg,
                        "min_bpm": min(values),
                        "max_bpm": max(values),
                        "samples": len(values),
                    }
                ),
                title=f"Avg {avg} bpm heart rate",
                timestamp=datetime.fromisoformat(day),
                metadata={"data_type": "heart_rate", "day": day},
            )

    @staticmethod
    def _yield_energy_docs(
        energy_by_day: Dict[str, float],
    ) -> Iterator[Document]:
        for day in sorted(energy_by_day):
            total = round(energy_by_day[day], 1)
            yield Document(
                doc_id=f"apple_health-active_energy-{day}",
                source="apple_health",
                doc_type="active_energy",
                content=json.dumps({"date": day, "kcal": total}),
                title=f"{total} kcal active energy",
                timestamp=datetime.fromisoformat(day),
                metadata={"data_type": "active_energy", "day": day},
            )

    @staticmethod
    def _yield_workout_docs(
        workouts: List[Dict[str, Any]],
    ) -> Iterator[Document]:
        for w in workouts:
            # Friendly activity name
            raw = w["activity_type"]
            activity = (
                raw.replace("HKWorkoutActivityType", "")
                if raw.startswith("HKWorkoutActivityType")
                else raw
            )

            # Build a descriptive title
            parts = [activity]
            if w.get("total_distance"):
                try:
                    parts.append(f"{float(w['total_distance']):.1f} km")
                except (ValueError, TypeError):
                    pass
            duration_s = w.get("duration_seconds", 0)
            if duration_s:
                parts.append(_format_duration(float(duration_s)))

            title = " -- ".join(parts) if len(parts) > 1 else activity

            # Deterministic doc_id from workout content
            digest = hashlib.sha256(json.dumps(w, sort_keys=True).encode()).hexdigest()[
                :12
            ]
            yield Document(
                doc_id=f"apple_health-workout-{digest}",
                source="apple_health",
                doc_type="workout",
                content=json.dumps(w),
                title=title,
                timestamp=datetime.fromisoformat(
                    _day_key(_parse_health_date(w["start"]))
                ),
                metadata={"data_type": "workout", "activity": activity},
            )
