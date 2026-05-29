"""
Core data types for SkillOrchestra.

- Skill
- AgentProfile
- BetaCompetence
- ModeMetadata
- RoutingInsight
- CostStats
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# BetaCompetence
# ---------------------------------------------------------------------------

@dataclass
class BetaCompetence:
    """Bayesian competence estimate for an agent on a specific skill.

    skill_scores / get_competence use empirical_rate (successes/attempts)
    """

    alpha: float = 1.0
    beta: float = 1.0

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def empirical_rate(self) -> float:
        """Empirical success rate: successes/attempts."""
        n = self.total_observations
        if n <= 0:
            return 0.0
        successes = max(0, int(self.alpha - 1))
        return successes / n

    @property
    def variance(self) -> float:
        """Posterior variance."""
        total = self.alpha + self.beta
        return (self.alpha * self.beta) / (total * total * (total + 1))

    @property
    def std(self) -> float:
        return math.sqrt(self.variance)

    @property
    def total_observations(self) -> int:
        """Total observations (excluding prior)"""
        return max(0, int(self.alpha + self.beta - 2))

    def update(self, success: bool) -> None:
        if success:
            self.alpha += 1.0
        else:
            self.beta += 1.0

    def update_batch(self, successes: int, failures: int) -> None:
        self.alpha += successes
        self.beta += failures

    def to_dict(self) -> Dict[str, float]:
        return {"alpha": self.alpha, "beta": self.beta}

    @classmethod
    def from_dict(cls, d: Dict[str, float]) -> BetaCompetence:
        return cls(alpha=d["alpha"], beta=d["beta"])


# ---------------------------------------------------------------------------
# CostStats
# ---------------------------------------------------------------------------

@dataclass
class CostStats:
    """Execution cost statistics for an agent under a specific mode.

    Tracks both total cost (prompt + completion) and completion-only cost
    separately, since completion cost is the variable component that
    differs most between models (prompt cost is roughly constant for the
    same query).
    """

    avg_prompt_tokens: float = 0.0
    avg_completion_tokens: float = 0.0
    avg_latency_s: float = 0.0
    avg_cost_usd: float = 0.0
    avg_completion_cost_usd: float = 0.0
    avg_prompt_cost_usd: float = 0.0
    total_executions: int = 0

    def update(
        self,
        prompt_tokens: float,
        completion_tokens: float,
        latency_s: float,
        cost_usd: float,
        completion_cost_usd: float = 0.0,
        prompt_cost_usd: float = 0.0,
    ) -> None:
        """Incremental running-average update."""
        n = self.total_executions
        self.avg_prompt_tokens = (self.avg_prompt_tokens * n + prompt_tokens) / (n + 1)
        self.avg_completion_tokens = (self.avg_completion_tokens * n + completion_tokens) / (n + 1)
        self.avg_latency_s = (self.avg_latency_s * n + latency_s) / (n + 1)
        self.avg_cost_usd = (self.avg_cost_usd * n + cost_usd) / (n + 1)
        self.avg_completion_cost_usd = (self.avg_completion_cost_usd * n + completion_cost_usd) / (n + 1)
        self.avg_prompt_cost_usd = (self.avg_prompt_cost_usd * n + prompt_cost_usd) / (n + 1)
        self.total_executions = n + 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "avg_prompt_tokens": self.avg_prompt_tokens,
            "avg_completion_tokens": self.avg_completion_tokens,
            "avg_latency_s": self.avg_latency_s,
            "avg_cost_usd": self.avg_cost_usd,
            "avg_completion_cost_usd": self.avg_completion_cost_usd,
            "avg_prompt_cost_usd": self.avg_prompt_cost_usd,
            "total_executions": self.total_executions,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> CostStats:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


# ---------------------------------------------------------------------------
# RoutingInsight
# ---------------------------------------------------------------------------

@dataclass
class RoutingInsight:
    """A single routing insight learned from execution traces"""

    insight_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    content: str = ""
    insight_type: str = ""  # "transition", "usage", "constraint", "agent_preference"
    evidence_query_ids: List[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "insight_id": self.insight_id,
            "content": self.content,
            "insight_type": self.insight_type,
            "evidence_query_ids": self.evidence_query_ids,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> RoutingInsight:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


# ---------------------------------------------------------------------------
# ModeMetadata
# ---------------------------------------------------------------------------

@dataclass
class ModeMetadata:
    """Mode-level routing metadata."""

    mode: str = ""
    description: str = ""
    insights: List[RoutingInsight] = field(default_factory=list)

    def add_insight(self, insight: RoutingInsight) -> None:
        self.insights.append(insight)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "description": self.description,
            "insights": [i.to_dict() for i in self.insights],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ModeMetadata:
        insights = [RoutingInsight.from_dict(i) for i in d.get("insights", [])]
        return cls(
            mode=d.get("mode", ""),
            description=d.get("description", ""),
            insights=insights,
        )


# ---------------------------------------------------------------------------
# Skill
# ---------------------------------------------------------------------------

@dataclass
class SkillProvenance:
    """Tracks how and why a skill was discovered."""

    discovered_from_queries: List[str] = field(default_factory=list)
    positive_trajectories: List[str] = field(default_factory=list)
    negative_trajectories: List[str] = field(default_factory=list)
    discovery_round: int = 0
    refinement_history: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "discovered_from_queries": self.discovered_from_queries,
            "positive_trajectories": self.positive_trajectories,
            "negative_trajectories": self.negative_trajectories,
            "discovery_round": self.discovery_round,
            "refinement_history": self.refinement_history,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> SkillProvenance:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class Skill:
    """A reusable capability abstraction."""

    skill_id: str = ""
    name: str = ""
    description: str = ""
    indicators: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    mode: str = ""
    parent_skill_id: Optional[str] = None # for hierarchical skills
    provenance: SkillProvenance = field(default_factory=SkillProvenance)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "indicators": self.indicators,
            "examples": self.examples,
            "mode": self.mode,
            "parent_skill_id": self.parent_skill_id,
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Skill:
        provenance = SkillProvenance.from_dict(d.get("provenance", {}))
        return cls(
            skill_id=d.get("skill_id", ""),
            name=d.get("name", ""),
            description=d.get("description", ""),
            indicators=d.get("indicators", []),
            examples=d.get("examples", []),
            mode=d.get("mode", ""),
            parent_skill_id=d.get("parent_skill_id"),
            provenance=provenance,
        )

    def get_children(self, all_skills: Dict[str, Skill]) -> List[Skill]:
        """Get child skills in the hierarchy."""
        return [s for s in all_skills.values() if s.parent_skill_id == self.skill_id]

    def is_leaf(self, all_skills: Dict[str, Skill]) -> bool:
        """True if this skill has no children."""
        return len(self.get_children(all_skills)) == 0


# ---------------------------------------------------------------------------
# AgentProfile
# ---------------------------------------------------------------------------

@dataclass
class AgentProfile:
    """Agent profile for skill-aware orchestration."""

    agent_id: str = ""
    mode: str = ""
    model_name: str = ""
    tools: List[str] = field(default_factory=list)

    skill_competence: Dict[str, BetaCompetence] = field(default_factory=dict)

    total_attempts: int = 0
    total_successes: int = 0

    cost_stats: CostStats = field(default_factory=CostStats)

    routing_signals: List[str] = field(default_factory=list)
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)

    def get_competence(self, skill_id: str) -> float:
        """Get empirical success rate for a skill. Returns 0 if unseen."""
        if skill_id in self.skill_competence:
            return self.skill_competence[skill_id].empirical_rate
        return 0.0

    def get_competence_dist(self, skill_id: str) -> BetaCompetence:
        """Get full Beta distribution for a skill, creating with prior if unseen."""
        if skill_id not in self.skill_competence:
            self.skill_competence[skill_id] = BetaCompetence()
        return self.skill_competence[skill_id]

    def update_competence(self, skill_id: str, success: bool) -> None:
        """Update competence estimate for a skill."""
        self.get_competence_dist(skill_id).update(success)

    def weighted_competence(
        self, skill_weights: Dict[str, float]
    ) -> float:
        """Compute weighted competence: sum w_{t,sigma} * alpha/(alpha+beta)."""
        if not skill_weights:
            return 0.5
        total = 0.0
        for skill_id, weight in skill_weights.items():
            total += weight * self.get_competence(skill_id)
        return total

    def category_competence(self, category_prefix: str) -> float:
        """Aggregate competence on all skills under a category (skill_id prefix).

        E.g. category_competence('entertainment_knowledge') = avg of
        get_competence(s) for all s where s.startswith('entertainment_knowledge.').
        """
        prefix = category_prefix.rstrip(".") + "."
        scores = [
            self.get_competence(sid)
            for sid in self.skill_competence
            if sid.startswith(prefix)
        ]
        return sum(scores) / len(scores) if scores else 0.0

    def category_competence_for_skills(
        self, active_skill_ids: List[str]
    ) -> float:
        """Category-level competence for hierarchical tie-breaking.

        Extracts parent categories from active_skill_ids (e.g. 'entertainment_knowledge'
        from 'entertainment_knowledge.episodic_competition_outcome'), computes
        category_competence for each, returns average.
        """
        categories: set = set()
        for sid in active_skill_ids:
            cat = sid.rsplit(".", 1)[0] if "." in sid else sid
            categories.add(cat)
        if not categories:
            return 0.0
        return sum(self.category_competence(cat) for cat in categories) / len(categories)

    @property
    def overall_success_rate(self) -> float:
        """Overall success rate (trajectory-level when available, else skill-level)."""
        if self.total_attempts > 0:
            return self.total_successes / self.total_attempts
        total_attempts = 0
        total_successes = 0
        for bc in self.skill_competence.values():
            n = bc.total_observations
            s = max(0, int(bc.alpha - 1))
            total_attempts += n
            total_successes += s
        return total_successes / total_attempts if total_attempts > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        skill_scores = {}
        skill_attempts = {}
        skill_successes = {}
        for sid, bc in self.skill_competence.items():
            obs = bc.total_observations
            successes = max(0, int(bc.alpha - 1))
            skill_attempts[sid] = obs
            skill_successes[sid] = successes
            skill_scores[sid] = round(successes / obs, 4) if obs > 0 else 0.0

        skill_total_attempts = sum(skill_attempts.values())
        skill_total_successes = sum(skill_successes.values())

        return {
            "agent_id": self.agent_id,
            "mode": self.mode,
            "model_name": self.model_name,
            "tools": self.tools,
            "skill_competence": {
                sid: bc.to_dict() for sid, bc in self.skill_competence.items()
            },
            "skill_scores": skill_scores,
            "skill_attempts": skill_attempts,
            "skill_successes": skill_successes,
            "total_attempts": self.total_attempts if self.total_attempts > 0 else skill_total_attempts,
            "total_successes": self.total_successes if self.total_attempts > 0 else skill_total_successes,
            "cost_stats": self.cost_stats.to_dict(),
            "routing_signals": self.routing_signals,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> AgentProfile:
        skill_competence = {
            sid: BetaCompetence.from_dict(bc)
            for sid, bc in d.get("skill_competence", {}).items()
        }
        cost_stats = CostStats.from_dict(d.get("cost_stats", {}))
        return cls(
            agent_id=d.get("agent_id", ""),
            mode=d.get("mode", ""),
            model_name=d.get("model_name", ""),
            tools=d.get("tools", []),
            skill_competence=skill_competence,
            total_attempts=d.get("total_attempts", 0),
            total_successes=d.get("total_successes", 0),
            cost_stats=cost_stats,
            routing_signals=d.get("routing_signals", []),
            strengths=d.get("strengths", []),
            weaknesses=d.get("weaknesses", []),
        )
