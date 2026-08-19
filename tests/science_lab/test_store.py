"""Tests for ScienceProjectStore — copies DigestStore's test shape."""

from __future__ import annotations

from openjarvis.science_lab.models import (
    ConfidenceScore,
    Hypothesis,
    ScienceProject,
    SimulationResult,
    TargetProperty,
)
from openjarvis.science_lab.store import ScienceProjectStore


def _make_project(name: str = "spider-fluid") -> ScienceProject:
    return ScienceProject(
        name=name,
        objective="Fluido com comportamento de teia",
        target_properties=[TargetProperty(name="elasticity", target_value="high")],
        hypotheses=[Hypothesis(id="h1", mechanism="polymer chain entanglement")],
        simulations=[
            SimulationResult(
                quantity="density", value=1.1, unit="g/cm^3", basis="VALOR CALCULADO"
            )
        ],
        comparison=[],
        confidence=ConfidenceScore(value=0.6, basis="test"),
        notes="test notes",
    )


class TestScienceProjectStore:
    def test_save_and_get_round_trip(self, tmp_path):
        store = ScienceProjectStore(db_path=str(tmp_path / "science_lab.db"))
        project = _make_project()
        store.save(project)
        loaded = store.get("spider-fluid")
        assert loaded is not None
        assert loaded.name == "spider-fluid"
        assert loaded.objective == project.objective
        assert loaded.target_properties[0].name == "elasticity"
        assert loaded.hypotheses[0].mechanism == "polymer chain entanglement"
        assert loaded.simulations[0].value == 1.1
        assert loaded.confidence.value == 0.6
        store.close()

    def test_get_missing_returns_none(self, tmp_path):
        store = ScienceProjectStore(db_path=str(tmp_path / "science_lab.db"))
        assert store.get("does-not-exist") is None
        store.close()

    def test_save_upserts_on_name(self, tmp_path):
        store = ScienceProjectStore(db_path=str(tmp_path / "science_lab.db"))
        project = _make_project()
        store.save(project)
        project.notes = "updated notes"
        store.save(project)
        loaded = store.get("spider-fluid")
        assert loaded.notes == "updated notes"
        assert len(store.list_projects()) == 1
        store.close()

    def test_list_projects_orders_newest_first(self, tmp_path):
        store = ScienceProjectStore(db_path=str(tmp_path / "science_lab.db"))
        store.save(_make_project("first"))
        store.save(_make_project("second"))
        projects = store.list_projects()
        assert [p.name for p in projects] == ["second", "first"]
        store.close()

    def test_delete(self, tmp_path):
        store = ScienceProjectStore(db_path=str(tmp_path / "science_lab.db"))
        store.save(_make_project())
        assert store.delete("spider-fluid") is True
        assert store.get("spider-fluid") is None
        assert store.delete("spider-fluid") is False
        store.close()

    def test_migrate_idempotent(self, tmp_path):
        db_path = str(tmp_path / "science_lab.db")
        store1 = ScienceProjectStore(db_path=db_path)
        store1.save(_make_project())
        store1.close()
        # Re-opening the same db must not error.
        store2 = ScienceProjectStore(db_path=db_path)
        assert store2.get("spider-fluid") is not None
        store2.close()
