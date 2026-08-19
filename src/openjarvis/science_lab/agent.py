"""ScienceLabAgent — the Science Lab reasoning pipeline.

Pipeline stages (each recorded into ``AgentResult.metadata["reasoning_summary"]``
as required): OBJETIVO -> PROPRIEDADES -> CANDIDATOS -> MODELO -> SIMULAÇÃO ->
RESULTADO -> LIMITAÇÕES. A safety gate runs before any of this, per the
project's explicit safety requirement.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple

from openjarvis.agents._stubs import AgentContext, AgentResult, ToolUsingAgent
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import Message, Role
from openjarvis.science_lab import calculations, safety_classifier
from openjarvis.science_lab.confidence import render_confidence_bar, score_confidence
from openjarvis.science_lab.hypothesis_engine import (
    generate_hypotheses,
    rank_hypotheses,
)
from openjarvis.science_lab.models import (
    Hypothesis,
    PropertyAnalysis,
    ScienceProject,
    SimulationResult,
)
from openjarvis.science_lab.property_analyzer import analyze_objective
from openjarvis.science_lab.store import ScienceProjectStore

NO_DATA_MESSAGE = "Não há dados suficientes para uma previsão confiável."

# Very small heuristic extractor: "100g" / "100 g" and "50ml" / "50 cm3" /
# "50cm³" style tokens in the raw request. Anything more sophisticated is
# out of scope — when nothing is found, SIMULAÇÃO honestly states
# NO_DATA_MESSAGE rather than guessing.
_MASS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*g\b", re.IGNORECASE)
_VOLUME_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:ml|cm3|cm³)\b", re.IGNORECASE)


def _extract_mass_volume(text: str) -> Optional[Tuple[float, float]]:
    mass_match = _MASS_RE.search(text)
    volume_match = _VOLUME_RE.search(text)
    if mass_match and volume_match:
        return float(mass_match.group(1)), float(volume_match.group(1))
    return None


@AgentRegistry.register("science_lab")
class ScienceLabAgent(ToolUsingAgent):
    """Chemistry/materials-science reasoning agent."""

    agent_id = "science_lab"

    def __init__(
        self,
        engine: Any,
        model: str,
        *,
        min_hypotheses: int = 2,
        max_hypotheses: int = 3,
        safety_llm_fallback: bool = True,
        db_path: str = "",
        store: Optional[ScienceProjectStore] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(engine, model, **kwargs)
        self._min_hypotheses = min_hypotheses
        self._max_hypotheses = max_hypotheses
        self._safety_llm_fallback = safety_llm_fallback
        self._db_path = db_path
        self._store = store  # lazily constructed on first save

    def _get_store(self) -> ScienceProjectStore:
        if self._store is None:
            self._store = ScienceProjectStore(db_path=self._db_path)
        return self._store

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        self._emit_turn_start(input)
        reasoning_summary: List[Tuple[str, str]] = []

        # --- Safety gate (first, before any hypothesis generation) --------
        classification = safety_classifier.classify(
            input,
            engine=self._engine,
            model=self._model,
            llm_fallback_enabled=self._safety_llm_fallback,
        )
        if classification.should_refuse:
            category = (
                classification.findings[0].category
                if classification.findings
                else "conteúdo perigoso"
            )
            explanation = safety_classifier.explain_safely(
                self._engine, self._model, category, input
            )
            content = f"{classification.refusal_text}\n\n{explanation}"
            reasoning_summary = [
                ("OBJETIVO", input),
                (
                    "LIMITAÇÕES",
                    "Solicitação recusada: conteúdo operacional perigoso detectado.",
                ),
            ]
            metadata = {
                "refused": True,
                "refusal_category": category,
                "reasoning_summary": reasoning_summary,
            }
            self._emit_turn_end(turns=1, refused=True)
            return AgentResult(
                content=content, tool_results=[], turns=1, metadata=metadata
            )

        limitations: List[str] = []

        # --- OBJETIVO -------------------------------------------------------
        try:
            analysis = analyze_objective(self._engine, self._model, input)
        except (ValueError, Exception) as exc:  # noqa: BLE001 - soft failure
            analysis = PropertyAnalysis(objective=input, target_properties=[])
            limitations.append(f"Análise de propriedades falhou: {exc}")
        reasoning_summary.append(("OBJETIVO", analysis.objective or input))

        # --- PROPRIEDADES -----------------------------------------------------
        if analysis.target_properties:
            props_text = "; ".join(
                f"{p.name}"
                + (f": {p.target_value}" if p.target_value else "")
                + (f" {p.unit}" if p.unit else "")
                for p in analysis.target_properties
            )
        else:
            props_text = "Nenhuma propriedade específica identificada."
        reasoning_summary.append(("PROPRIEDADES", props_text))

        # --- CANDIDATOS -------------------------------------------------------
        hypotheses: List[Hypothesis] = []
        try:
            hypotheses = generate_hypotheses(
                self._engine, self._model, analysis, k=self._max_hypotheses
            )
        except ValueError as exc:
            limitations.append(f"Não foi possível gerar hipóteses estruturadas: {exc}")

        chosen_idx = 0
        if hypotheses:
            try:
                chosen_idx, _ranker_reasoning = rank_hypotheses(
                    self._engine, self._model, hypotheses
                )
            except Exception as exc:  # noqa: BLE001 - soft failure, keep index 0
                limitations.append(f"Ranqueamento de hipóteses falhou: {exc}")
                chosen_idx = 0

        cand_text = (
            "\n".join(f"{h.id}: {h.mechanism}" for h in hypotheses)
            if hypotheses
            else "Nenhuma hipótese gerada."
        )
        reasoning_summary.append(("CANDIDATOS", cand_text))

        chosen_hypothesis = hypotheses[chosen_idx] if hypotheses else None

        # --- MODELO -------------------------------------------------------
        if chosen_hypothesis is not None:
            model_desc = f"Hipótese selecionada: {chosen_hypothesis.mechanism}"
        else:
            model_desc = "Nenhum modelo teórico aplicável — hipóteses insuficientes."
        reasoning_summary.append(("MODELO", model_desc))

        # --- SIMULAÇÃO ------------------------------------------------------
        simulations: List[SimulationResult] = []
        extracted = _extract_mass_volume(input)
        if extracted is not None:
            mass_g, volume_cm3 = extracted
            try:
                simulations.append(
                    calculations.estimate_density(mass_g=mass_g, volume_cm3=volume_cm3)
                )
            except ValueError as exc:
                limitations.append(f"Cálculo de densidade falhou: {exc}")
        if simulations:
            sim_text = "\n".join(
                f"{s.quantity} = {s.value:.4g} {s.unit} [{s.basis}]"
                for s in simulations
            )
        else:
            sim_text = NO_DATA_MESSAGE
        reasoning_summary.append(("SIMULAÇÃO", sim_text))

        # --- RESULTADO --------------------------------------------------------
        result_text = self._synthesize_result(
            input, analysis, chosen_hypothesis, simulations
        )
        reasoning_summary.append(("RESULTADO", result_text))

        # --- LIMITAÇÕES (always present) --------------------------------------
        base_limitation = (
            "Este resultado é baseado em modelos teóricos simplificados e "
            "hipóteses geradas por IA; não substitui validação experimental."
        )
        limitations_text = base_limitation
        if limitations:
            limitations_text += "\n" + "\n".join(limitations)
        reasoning_summary.append(("LIMITAÇÕES", limitations_text))

        confidence = score_confidence(analysis, hypotheses, simulations)
        confidence_bar = render_confidence_bar(confidence.value)

        metadata = {
            "refused": False,
            "reasoning_summary": reasoning_summary,
            "confidence": {**confidence.to_dict(), "rendered": confidence_bar},
            "hypotheses": [h.to_dict() for h in hypotheses],
            "simulations": [s.to_dict() for s in simulations],
            "comparison": [],
        }

        project_name = kwargs.get("project_name") or (
            context.metadata.get("project_name") if context else None
        )
        if project_name:
            project = ScienceProject(
                name=project_name,
                objective=analysis.objective,
                target_properties=analysis.target_properties,
                hypotheses=hypotheses,
                simulations=simulations,
                comparison=[],
                confidence=confidence,
                notes=result_text,
            )
            self._get_store().save(project)
            metadata["saved_project"] = project_name

        self._emit_turn_end(turns=1)
        return AgentResult(
            content=result_text, tool_results=[], turns=1, metadata=metadata
        )

    def _synthesize_result(
        self,
        input: str,
        analysis: PropertyAnalysis,
        chosen_hypothesis: Optional[Hypothesis],
        simulations: List[SimulationResult],
    ) -> str:
        """One final LLM call synthesizing the natural-language RESULTADO."""
        sim_lines = (
            "\n".join(
                f"- {s.quantity}: {s.value:.4g} {s.unit} ({s.basis})"
                for s in simulations
            )
            if simulations
            else f"- {NO_DATA_MESSAGE}"
        )
        hyp_line = (
            f"Mecanismo escolhido: {chosen_hypothesis.mechanism}"
            if chosen_hypothesis
            else "Nenhuma hipótese disponível."
        )
        user_content = (
            f"Pedido original: {input}\n\n"
            f"Objetivo: {analysis.objective}\n\n"
            f"{hyp_line}\n\n"
            f"Cálculos/estimativas:\n{sim_lines}\n\n"
            "Escreva uma resposta final curta e clara em português, citando os "
            "valores calculados junto com sua base (DADO EXPERIMENTAL / VALOR "
            "CALCULADO / ESTIMATIVA / HIPÓTESE) quando existirem."
        )
        messages = [
            Message(
                role=Role.SYSTEM,
                content=(
                    "Você é um assistente científico que resume resultados de "
                    "forma honesta, citando sempre a base de cada valor numérico."
                ),
            ),
            Message(role=Role.USER, content=user_content),
        ]
        try:
            result = self._engine.generate(
                messages, model=self._model, temperature=0.3, max_tokens=768
            )
            text = (result.get("content", "") or "").strip()
            return text or hyp_line
        except Exception:  # noqa: BLE001 - soft failure, never crash on synthesis
            return hyp_line


__all__ = ["NO_DATA_MESSAGE", "ScienceLabAgent"]
