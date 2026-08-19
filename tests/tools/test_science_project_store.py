"""Tests for the science_project tool."""

from __future__ import annotations

from openjarvis.science_lab.models import ConfidenceScore, ScienceProject
from openjarvis.science_lab.store import ScienceProjectStore
from openjarvis.tools.science_project_store import ScienceProjectTool


class TestScienceProjectTool:
    def test_spec(self):
        tool = ScienceProjectTool()
        assert tool.spec.name == "science_project"
        assert tool.spec.category == "science"

    def test_list_empty(self, tmp_path):
        tool = ScienceProjectTool(db_path=str(tmp_path / "science_lab.db"))
        result = tool.execute(action="list")
        assert result.success is True
        assert result.metadata["projects"] == []

    def test_get_and_list_round_trip(self, tmp_path):
        db_path = str(tmp_path / "science_lab.db")
        store = ScienceProjectStore(db_path=db_path)
        store.save(
            ScienceProject(
                name="test-project",
                objective="test objective",
                confidence=ConfidenceScore(0.5),
            )
        )
        store.close()

        tool = ScienceProjectTool(db_path=db_path)
        get_result = tool.execute(action="get", name="test-project")
        assert get_result.success is True
        assert get_result.metadata["objective"] == "test objective"

        list_result = tool.execute(action="list")
        assert len(list_result.metadata["projects"]) == 1

    def test_get_missing_project(self, tmp_path):
        tool = ScienceProjectTool(db_path=str(tmp_path / "science_lab.db"))
        result = tool.execute(action="get", name="nope")
        assert result.success is False

    def test_unknown_action(self, tmp_path):
        tool = ScienceProjectTool(db_path=str(tmp_path / "science_lab.db"))
        result = tool.execute(action="delete_everything")
        assert result.success is False
