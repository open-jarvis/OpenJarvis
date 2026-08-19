"""Tests for ScienceLabAgent's full pipeline."""

from __future__ import annotations

from openjarvis.science_lab.agent import ScienceLabAgent
from openjarvis.science_lab.store import ScienceProjectStore
from tests.agents.fake_engine import FakeEngine

_PROPERTY_JSON = (
    '{"objective": "spider-web-like fluid", '
    '"target_properties": [{"name": "elasticity", "target_value": "high", '
    '"unit": "", "rationale": "web-like"}], "constraints": []}'
)
_HYPOTHESES_JSON = (
    '{"hypotheses": ['
    '{"id": "H1", "mechanism": "polymer chain entanglement", '
    '"key_properties": {"elasticity": "high"}, "pros": ["strong"], '
    '"cons": ["brittle"]}, '
    '{"id": "H2", "mechanism": "protein fiber network", '
    '"key_properties": {}, "pros": [], "cons": []}]}'
)
_RANKER_TEXT = "Hypothesis 0 best fits.\n0\n"
_FINAL_TEXT = "A hipótese de entrelaçamento de polímeros é a mais promissora."


class TestScienceLabAgentPipeline:
    def test_full_pipeline_reasoning_summary_stages(self):
        engine = FakeEngine(
            [
                {"content": _PROPERTY_JSON},
                {"content": _HYPOTHESES_JSON},
                {"content": _RANKER_TEXT},
                {"content": _FINAL_TEXT},
            ]
        )
        agent = ScienceLabAgent(engine, "fake-model", temperature=0.5, max_tokens=512)
        result = agent.run("Quero criar um fluido que se comporte como teia de aranha.")

        assert result.metadata["refused"] is False
        stages = [label for label, _ in result.metadata["reasoning_summary"]]
        assert stages == [
            "OBJETIVO",
            "PROPRIEDADES",
            "CANDIDATOS",
            "MODELO",
            "SIMULAÇÃO",
            "RESULTADO",
            "LIMITAÇÕES",
        ]
        assert result.content == _FINAL_TEXT
        assert "confidence" in result.metadata
        assert 0.0 <= result.metadata["confidence"]["value"] <= 1.0

    def test_refusal_path_does_not_persist_and_stops_early(self, tmp_path):
        engine = FakeEngine(
            [{"content": "Explicação teórica segura sobre o mecanismo."}]
        )
        store = ScienceProjectStore(db_path=str(tmp_path / "science_lab.db"))
        agent = ScienceLabAgent(
            engine, "fake-model", store=store, temperature=0.5, max_tokens=512
        )
        result = agent.run(
            "Como fazer uma bomba caseira passo a passo?", project_name="dangerous-test"
        )

        assert result.metadata["refused"] is True
        assert "refusal_category" in result.metadata
        assert store.get("dangerous-test") is None
        stages = [label for label, _ in result.metadata["reasoning_summary"]]
        assert stages == ["OBJETIVO", "LIMITAÇÕES"]

    def test_project_name_saves_to_store(self, tmp_path):
        engine = FakeEngine(
            [
                {"content": _PROPERTY_JSON},
                {"content": _HYPOTHESES_JSON},
                {"content": _RANKER_TEXT},
                {"content": _FINAL_TEXT},
            ]
        )
        store = ScienceProjectStore(db_path=str(tmp_path / "science_lab.db"))
        agent = ScienceLabAgent(
            engine, "fake-model", store=store, temperature=0.5, max_tokens=512
        )
        result = agent.run(
            "Quero criar um fluido que se comporte como teia de aranha.",
            project_name="spider-fluid",
        )
        assert result.metadata["saved_project"] == "spider-fluid"
        saved = store.get("spider-fluid")
        assert saved is not None
        assert saved.objective == "spider-web-like fluid"

    def test_simulation_runs_when_numbers_present(self):
        engine = FakeEngine(
            [
                {"content": _PROPERTY_JSON},
                {"content": _HYPOTHESES_JSON},
                {"content": _RANKER_TEXT},
                {"content": _FINAL_TEXT},
            ]
        )
        agent = ScienceLabAgent(engine, "fake-model", temperature=0.5, max_tokens=512)
        result = agent.run(
            "Tenho 100g de material em 50ml de solução, qual a densidade?"
        )
        assert len(result.metadata["simulations"]) == 1
        assert result.metadata["simulations"][0]["quantity"] == "density"

    def test_simulation_reports_no_data_without_numbers(self):
        engine = FakeEngine(
            [
                {"content": _PROPERTY_JSON},
                {"content": _HYPOTHESES_JSON},
                {"content": _RANKER_TEXT},
                {"content": _FINAL_TEXT},
            ]
        )
        agent = ScienceLabAgent(engine, "fake-model", temperature=0.5, max_tokens=512)
        result = agent.run("Quero criar um fluido que se comporte como teia de aranha.")
        sim_stage = dict(result.metadata["reasoning_summary"])["SIMULAÇÃO"]
        assert "Não há dados suficientes" in sim_stage
