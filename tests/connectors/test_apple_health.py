"""Tests for AppleHealthConnector -- local HealthKit DB / export XML."""

from __future__ import annotations

import json
from datetime import datetime

from openjarvis.connectors._stubs import Document
from openjarvis.core.registry import ConnectorRegistry

_SAMPLE_EXPORT_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<HealthData>
  <Record type="HKQuantityTypeIdentifierStepCount" \
startDate="2024-03-15 08:00:00 -0700" \
endDate="2024-03-15 08:30:00 -0700" \
value="1234" sourceName="iPhone" unit="count"/>
  <Record type="HKQuantityTypeIdentifierStepCount" \
startDate="2024-03-15 12:00:00 -0700" \
endDate="2024-03-15 12:15:00 -0700" \
value="500" sourceName="iPhone" unit="count"/>
  <Record type="HKCategoryTypeIdentifierSleepAnalysis" \
startDate="2024-03-15 22:00:00 -0700" \
endDate="2024-03-16 06:00:00 -0700" \
value="HKCategoryValueSleepAnalysisAsleepCore" sourceName="iPhone"/>
  <Record type="HKQuantityTypeIdentifierHeartRate" \
startDate="2024-03-15 09:00:00 -0700" \
value="65" unit="count/min" sourceName="iPhone"/>
  <Record type="HKQuantityTypeIdentifierHeartRate" \
startDate="2024-03-15 15:00:00 -0700" \
value="75" unit="count/min" sourceName="iPhone"/>
  <Record type="HKQuantityTypeIdentifierActiveEnergyBurned" \
startDate="2024-03-15 07:30:00 -0700" \
value="350" unit="kcal" sourceName="iPhone"/>
  <Workout workoutActivityType="HKWorkoutActivityTypeRunning" \
duration="1800" \
startDate="2024-03-15 07:00:00 -0700" \
endDate="2024-03-15 07:30:00 -0700" \
totalDistance="5.2" totalEnergyBurned="300"/>
</HealthData>
"""


def test_apple_health_registered():
    """AppleHealthConnector is discoverable via ConnectorRegistry."""
    from openjarvis.connectors.apple_health import AppleHealthConnector

    ConnectorRegistry.register_value("apple_health", AppleHealthConnector)
    assert ConnectorRegistry.contains("apple_health")
    cls = ConnectorRegistry.get("apple_health")
    assert cls.connector_id == "apple_health"
    assert cls.display_name == "Apple Health"
    assert cls.auth_type == "local"


def test_not_connected_no_files(tmp_path):
    """is_connected() returns False when neither data source exists."""
    from openjarvis.connectors.apple_health import AppleHealthConnector

    connector = AppleHealthConnector(
        export_path=str(tmp_path / "nope.xml"),
        healthkit_db_path=str(tmp_path / "nope.sqlite"),
    )
    assert connector.is_connected() is False


def test_connected_with_export(tmp_path):
    """is_connected() returns True when the export XML exists."""
    from openjarvis.connectors.apple_health import AppleHealthConnector

    export_file = tmp_path / "export.xml"
    export_file.write_text(_SAMPLE_EXPORT_XML, encoding="utf-8")

    connector = AppleHealthConnector(
        export_path=str(export_file),
        healthkit_db_path=str(tmp_path / "nope.sqlite"),
    )
    assert connector.is_connected() is True


def test_sync_export_xml(tmp_path):
    """Sync from export XML yields correct Documents for each data type."""
    from openjarvis.connectors.apple_health import AppleHealthConnector

    export_file = tmp_path / "export.xml"
    export_file.write_text(_SAMPLE_EXPORT_XML, encoding="utf-8")

    connector = AppleHealthConnector(
        export_path=str(export_file),
        healthkit_db_path=str(tmp_path / "nope.sqlite"),
    )
    docs = list(connector.sync())
    assert all(isinstance(d, Document) for d in docs)

    by_type = {}
    for d in docs:
        by_type.setdefault(d.doc_type, []).append(d)

    # Steps: two records on 2024-03-15 should be summed (1234 + 500 = 1734)
    assert "steps" in by_type
    step_doc = by_type["steps"][0]
    assert step_doc.source == "apple_health"
    step_data = json.loads(step_doc.content)
    assert step_data["steps"] == 1734
    assert "1,734" in step_doc.title

    # Sleep
    assert "sleep" in by_type
    sleep_doc = by_type["sleep"][0]
    sleep_data = json.loads(sleep_doc.content)
    assert sleep_data["total_seconds"] == 28800.0  # 8 hours
    assert "8h" in sleep_doc.title

    # Heart rate: avg of 65 and 75 = 70
    assert "heart_rate" in by_type
    hr_doc = by_type["heart_rate"][0]
    hr_data = json.loads(hr_doc.content)
    assert hr_data["avg_bpm"] == 70.0
    assert hr_data["min_bpm"] == 65.0
    assert hr_data["max_bpm"] == 75.0

    # Active energy
    assert "active_energy" in by_type
    energy_doc = by_type["active_energy"][0]
    energy_data = json.loads(energy_doc.content)
    assert energy_data["kcal"] == 350.0

    # Workout
    assert "workout" in by_type
    workout_doc = by_type["workout"][0]
    assert "Running" in workout_doc.title
    assert "5.2" in workout_doc.title
    workout_data = json.loads(workout_doc.content)
    assert workout_data["duration_seconds"] == 1800.0


def test_sync_with_since_filter(tmp_path):
    """Only records after the ``since`` date are included."""
    from openjarvis.connectors.apple_health import AppleHealthConnector

    export_file = tmp_path / "export.xml"
    export_file.write_text(_SAMPLE_EXPORT_XML, encoding="utf-8")

    connector = AppleHealthConnector(
        export_path=str(export_file),
        healthkit_db_path=str(tmp_path / "nope.sqlite"),
    )
    # All sample data is from 2024-03-15; filtering after that should yield nothing
    docs = list(connector.sync(since=datetime(2025, 1, 1)))
    assert len(docs) == 0


def test_disconnect_is_noop(tmp_path):
    """disconnect() does not raise for a local connector."""
    from openjarvis.connectors.apple_health import AppleHealthConnector

    connector = AppleHealthConnector(
        export_path=str(tmp_path / "nope.xml"),
        healthkit_db_path=str(tmp_path / "nope.sqlite"),
    )
    connector.disconnect()  # should not raise
