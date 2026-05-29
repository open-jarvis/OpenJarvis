"""
Adapter for orchestration eval script.

Provides: StageSkillHandbook (load from JSON), parse_skill_analysis,
get_routing_strategy. Compatible with JSON produced by to_stage_router.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# =============================================================================
# Handbook dataclasses (compatible with stage_router JSON)
# =============================================================================


@dataclass
class Skill:
    """A skill that models can have."""

    skill_id: str
    name: str
    description: str
    stage: str
    examples: List[str] = field(default_factory=list)
    discovered_from_problems: List[Dict[str, str]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Skill":
        return cls(
            skill_id=data.get("skill_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            stage=data.get("stage", ""),
            examples=data.get("examples", []),
            discovered_from_problems=data.get("discovered_from_problems", []),
        )


@dataclass
class ModelProfile:
    """Performance profile for a model alias."""

    model_alias: str
    actual_model: str
    stage: str
    skill_scores: Dict[str, float] = field(default_factory=dict)
    skill_attempts: Dict[str, int] = field(default_factory=dict)
    skill_successes: Dict[str, int] = field(default_factory=dict)
    overall_success_rate: float = 0.5
    total_attempts: int = 0
    total_successes: int = 0
    avg_prompt_tokens: float = 0.0
    avg_completion_tokens: float = 0.0
    avg_cost_usd: float = 0.0
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelProfile":
        return cls(
            model_alias=data.get("model_alias", ""),
            actual_model=data.get("actual_model", ""),
            stage=data.get("stage", ""),
            skill_scores=data.get("skill_scores", {}),
            skill_attempts=data.get("skill_attempts", {}),
            skill_successes=data.get("skill_successes", {}),
            overall_success_rate=data.get("overall_success_rate", 0.5),
            total_attempts=data.get("total_attempts", 0),
            total_successes=data.get("total_successes", 0),
            avg_prompt_tokens=data.get("avg_prompt_tokens", 0.0),
            avg_completion_tokens=data.get("avg_completion_tokens", 0.0),
            avg_cost_usd=data.get("avg_cost_usd", 0.0),
            strengths=data.get("strengths", []),
            weaknesses=data.get("weaknesses", []),
        )


# =============================================================================
# StageSkillHandbook
# =============================================================================


class StageSkillHandbook:
    """Handbook for eval routing. Load from JSON produced by to_stage_router."""

    def __init__(self, load_defaults: bool = True):
        self.skills: Dict[str, Dict[str, Skill]] = {
            "search": {},
            "code": {},
            "answer": {},
        }
        self.model_profiles: Dict[str, ModelProfile] = {}
        self.usage_patterns: Dict[str, Any] = {"stages": {}, "guidelines": {}, "models": {}, "raw": {}}
        self.routing_insights: List[str] = []
        self.learning_history: List[Dict[str, Any]] = []
        self.version = "1.0.0"
        self.created_at = ""
        self.updated_at = ""

    def get_model_skill_scores(self) -> Dict[str, Dict[str, float]]:
        return {alias: profile.skill_scores for alias, profile in self.model_profiles.items()}

    def get_models_for_stage(self, stage: str) -> List[ModelProfile]:
        return [p for p in self.model_profiles.values() if p.stage == stage]

    def format_skills(self, stage: str) -> str:
        catalog_skills = self.skills.get(stage, {})
        models = self.get_models_for_stage(stage)
        skills_with_performance = set()
        for model in models:
            skills_with_performance.update(model.skill_scores.keys())

        lines = []
        shown_skills = set()
        for skill_id, skill in catalog_skills.items():
            if skill_id in skills_with_performance:
                shown_skills.add(skill_id)
                lines.append(f"- {skill_id}: {skill.description}")
                if skill.examples:
                    lines.append(f"  Examples: {', '.join(skill.examples[:2])}")

        orphaned = skills_with_performance - set(catalog_skills.keys())
        if orphaned:
            if shown_skills:
                lines.append("")
                lines.append("# Additional skills with performance data available:")
            for skill_id in sorted(orphaned):
                lines.append(f"- {skill_id}")

        return "\n".join(lines) if lines else "No skills defined"

    def format_model_performance(self, stage: str) -> str:
        profiles = self.get_models_for_stage(stage)
        valid_prefixes = {"search": ["search-"], "code": ["reasoner-", "code-"], "answer": ["answer-"]}
        prefixes = valid_prefixes.get(stage, [])

        lines = []
        for p in profiles:
            if not any(p.model_alias.startswith(prefix) for prefix in prefixes):
                continue
            has_data = (p.skill_scores and len(p.skill_scores) > 0) or p.strengths or p.weaknesses
            if p.total_attempts > 0 or has_data:
                lines.append(f"\n### {p.model_alias} ({p.actual_model})")
                if p.total_attempts > 0:
                    rate = p.total_successes / p.total_attempts
                    lines.append(f"Overall: {rate:.0%} success ({p.total_successes}/{p.total_attempts})")
                else:
                    lines.append("Overall: 0% overall")
                if p.skill_scores:
                    lines.append("Skill scores:")
                    stage_skill_scores = {
                        sid: s
                        for sid, s in p.skill_scores.items()
                        if (sid.split(".")[0] if "." in sid else sid) in ("code", stage)
                    }
                    for skill_id, score in sorted(stage_skill_scores.items(), key=lambda x: x[1], reverse=True):
                        lines.append(f"  - {skill_id}: {score:.0%}")
                if p.strengths:
                    lines.append(f"Strengths: {', '.join(p.strengths[:3])}")
                if p.weaknesses:
                    lines.append(f"Weaknesses: {', '.join(p.weaknesses[:3])}")

        return "\n".join(lines) if lines else "No model performance data learned yet."

    @classmethod
    def load(cls, path: str) -> "StageSkillHandbook":
        with open(path) as f:
            data = json.load(f)
        handbook = cls(load_defaults=False)
        handbook.version = data.get("version", "1.0.0")
        handbook.created_at = data.get("created_at", "")
        handbook.updated_at = data.get("updated_at", "")
        for stage, skills in data.get("skills", {}).items():
            if stage not in handbook.skills:
                handbook.skills[stage] = {}
            for sid, sdata in skills.items():
                handbook.skills[stage][sid] = Skill.from_dict(sdata)
        for alias, pdata in data.get("model_profiles", {}).items():
            handbook.model_profiles[alias] = ModelProfile.from_dict(pdata)
        raw_usage = data.get("usage_patterns", {})
        handbook.usage_patterns = {
            "stages": raw_usage.get("stages", {}),
            "guidelines": raw_usage.get("guidelines", {}),
            "models": raw_usage.get("models", {}),
            "raw": raw_usage.get("raw", {}),
        }
        handbook.learning_history = data.get("learning_history", [])
        handbook.routing_insights = data.get("routing_insights", [])
        return handbook


# =============================================================================
# Skill analysis parsing
# =============================================================================


@dataclass
class SkillWeight:
    skill_id: str
    percentage: float


@dataclass
class SkillAnalysis:
    stage: str
    required_skills: List[SkillWeight] = field(default_factory=list)
    reasoning: str = ""
    raw_json: Dict[str, Any] = field(default_factory=dict)


def parse_skill_analysis(output: str) -> Optional[SkillAnalysis]:
    pattern = r"<skill_analysis>\s*(.*?)\s*</skill_analysis>"
    match = re.search(pattern, output, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(1).strip())
        required_skills = [
            SkillWeight(skill_id=s.get("skill_id", ""), percentage=float(s.get("percentage", 0)))
            for s in data.get("required_skills", [])
        ]
        return SkillAnalysis(
            stage=data.get("stage", ""),
            required_skills=required_skills,
            reasoning=data.get("reasoning", ""),
            raw_json=data,
        )
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


# =============================================================================
# Routing strategies
# =============================================================================


@dataclass
class ModelRoutingResult:
    model_alias: str
    decision_logic: str
    confidence: float = 0.0
    all_scores: Dict[str, float] = field(default_factory=dict)


class RoutingStrategy:
    def __init__(self, handbook: Optional[StageSkillHandbook] = None):
        self.handbook = handbook
        self._model_skill_scores: Dict[str, Dict[str, float]] = {}
        if handbook:
            self._model_skill_scores = handbook.get_model_skill_scores()

    def _find_skill_id(self, stage: str, skill_id_or_name: str) -> Optional[str]:
        if not self.handbook:
            return None
        handbook_stage = "code" if stage == "reasoning" else stage
        stage_skills = self.handbook.skills.get(handbook_stage, {})
        if skill_id_or_name in stage_skills:
            return skill_id_or_name
        lower = skill_id_or_name.lower()
        for sid, skill in stage_skills.items():
            if skill.name.lower() == lower or lower in skill.name.lower():
                return sid
        return None

    def _get_models_for_stage(self, stage: str) -> List[str]:
        if stage == "search":
            return ["search-1", "search-2", "search-3"]
        if stage == "reasoning":
            return ["reasoner-1", "reasoner-2", "reasoner-3"]
        if stage == "answer":
            return ["answer-1", "answer-2", "answer-3", "answer-4", "answer-math-1", "answer-math-2"]
        return []

    def select_model(
        self,
        stage: str,
        skill_analysis: Optional[SkillAnalysis] = None,
        tool_call_model: Optional[str] = None,
    ) -> ModelRoutingResult:
        raise NotImplementedError


class RouterDecidesStrategy(RoutingStrategy):
    def select_model(
        self,
        stage: str,
        skill_analysis: Optional[SkillAnalysis] = None,
        tool_call_model: Optional[str] = None,
    ) -> ModelRoutingResult:
        if tool_call_model:
            return ModelRoutingResult(tool_call_model, "router_decides_from_tool_call", 1.0)
        defaults = {"search": "search-1", "reasoning": "reasoner-1", "answer": "answer-1"}
        return ModelRoutingResult(defaults.get(stage, "answer-1"), "router_decides_fallback", 0.5)


class AnalyzeModelDecideStrategy(RoutingStrategy):
    def select_model(
        self,
        stage: str,
        skill_analysis: Optional[SkillAnalysis] = None,
        tool_call_model: Optional[str] = None,
    ) -> ModelRoutingResult:
        if tool_call_model:
            return ModelRoutingResult(tool_call_model, "analyze_model_decide_with_skill_analysis", 1.0)
        defaults = {"search": "search-1", "reasoning": "reasoner-1", "answer": "answer-1"}
        return ModelRoutingResult(defaults.get(stage, "answer-1"), "analyze_model_decide_fallback", 0.5)


class WeightedAverageStrategy(RoutingStrategy):
    COST_TIERS = {
        "search-3": 1, "search-2": 2, "search-1": 3,
        "reasoner-3": 1, "reasoner-2": 2, "reasoner-1": 3,
        "answer-math-2": 1, "answer-4": 1, "answer-3": 2,
        "answer-math-1": 2, "answer-2": 3, "answer-1": 4,
    }

    def select_model(
        self,
        stage: str,
        skill_analysis: Optional[SkillAnalysis] = None,
        tool_call_model: Optional[str] = None,
    ) -> ModelRoutingResult:
        if not skill_analysis or not skill_analysis.required_skills:
            if tool_call_model:
                return ModelRoutingResult(tool_call_model, "weighted_avg_no_skills_use_tool_call", 0.7)
            defaults = {"search": "search-1", "reasoning": "reasoner-1", "answer": "answer-1"}
            return ModelRoutingResult(defaults.get(stage, "answer-1"), "weighted_avg_no_skills_fallback", 0.5)

        models = self._get_models_for_stage(stage)
        model_scores = {}
        for model in models:
            scores = self._model_skill_scores.get(model, {})
            weighted_sum = total_weight = 0.0
            for sw in skill_analysis.required_skills:
                weight = sw.percentage / 100.0
                sid = self._find_skill_id(stage, sw.skill_id) or sw.skill_id
                score = scores.get(sid, 0.0)
                weighted_sum += weight * score
                total_weight += weight
            model_scores[model] = weighted_sum / total_weight if total_weight > 0 else 0.5

        if not model_scores:
            defaults = {"search": "search-1", "reasoning": "reasoner-1", "answer": "answer-1"}
            return ModelRoutingResult(defaults.get(stage, "answer-1"), "weighted_avg_no_model_scores", 0.5)
        max_score = max(model_scores.values())
        best = [m for m, s in model_scores.items() if abs(s - max_score) < 0.001]
        best.sort(key=lambda m: self.COST_TIERS.get(m, 999))
        return ModelRoutingResult(best[0], "weighted_avg_from_skill_analysis", max_score, model_scores)


class WeakestSkillStrategy(RoutingStrategy):
    def select_model(
        self,
        stage: str,
        skill_analysis: Optional[SkillAnalysis] = None,
        tool_call_model: Optional[str] = None,
    ) -> ModelRoutingResult:
        if not skill_analysis or not skill_analysis.required_skills:
            if tool_call_model:
                return ModelRoutingResult(tool_call_model, "weakest_skill_no_skills_use_tool_call", 0.7)
            defaults = {"search": "search-1", "reasoning": "reasoner-1", "answer": "answer-1"}
            return ModelRoutingResult(defaults.get(stage, "answer-1"), "weakest_skill_no_skills_fallback", 0.5)
        weakest = min(skill_analysis.required_skills, key=lambda s: s.percentage)
        sid = self._find_skill_id(stage, weakest.skill_id) or weakest.skill_id
        models = self._get_models_for_stage(stage)
        model_scores = {m: self._model_skill_scores.get(m, {}).get(sid, 0.5) for m in models}
        if not model_scores:
            defaults = {"search": "search-1", "reasoning": "reasoner-1", "answer": "answer-1"}
            return ModelRoutingResult(defaults.get(stage, "answer-1"), "weakest_skill_no_model_scores", 0.5)
        best = max(model_scores, key=model_scores.get)
        return ModelRoutingResult(best, f"weakest_skill_{weakest.skill_id}", model_scores[best], model_scores)


class StrongestSkillStrategy(RoutingStrategy):
    def select_model(
        self,
        stage: str,
        skill_analysis: Optional[SkillAnalysis] = None,
        tool_call_model: Optional[str] = None,
    ) -> ModelRoutingResult:
        if not skill_analysis or not skill_analysis.required_skills:
            if tool_call_model:
                return ModelRoutingResult(tool_call_model, "strongest_skill_no_skills_use_tool_call", 0.7)
            defaults = {"search": "search-1", "reasoning": "reasoner-1", "answer": "answer-1"}
            return ModelRoutingResult(defaults.get(stage, "answer-1"), "strongest_skill_no_skills_fallback", 0.5)
        strongest = max(skill_analysis.required_skills, key=lambda s: s.percentage)
        sid = self._find_skill_id(stage, strongest.skill_id) or strongest.skill_id
        models = self._get_models_for_stage(stage)
        model_scores = {m: self._model_skill_scores.get(m, {}).get(sid, 0.5) for m in models}
        if not model_scores:
            defaults = {"search": "search-1", "reasoning": "reasoner-1", "answer": "answer-1"}
            return ModelRoutingResult(defaults.get(stage, "answer-1"), "strongest_skill_no_model_scores", 0.5)
        best = max(model_scores, key=model_scores.get)
        return ModelRoutingResult(best, f"strongest_skill_{strongest.skill_id}", model_scores[best], model_scores)


ROUTING_STRATEGIES = {
    "router_decides": RouterDecidesStrategy,
    "analyze_model_decide": AnalyzeModelDecideStrategy,
    "weighted_avg": WeightedAverageStrategy,
    "weakest_skill": WeakestSkillStrategy,
    "strongest_skill": StrongestSkillStrategy,
}


def get_routing_strategy(
    strategy_name: str, handbook: Optional[StageSkillHandbook] = None
) -> RoutingStrategy:
    if strategy_name not in ROUTING_STRATEGIES:
        raise ValueError(
            f"Unknown routing strategy: {strategy_name}. "
            f"Available: {list(ROUTING_STRATEGIES.keys())}"
        )
    return ROUTING_STRATEGIES[strategy_name](handbook)
