"""SkillOrchestra — faithful port of the eval-orchestrator (arXiv:2602.19672).

Importing this package registers the ``skillorchestra`` agent. Layout
mirrors the upstream repo (``external/SkillOrchestra``):

* :mod:`.prompts`       — verbatim ``eval_orchestrator`` / ``model_routing``
                          / ``learning`` prompt templates.
* :mod:`.stage_router`  — verbatim ``StageSkillHandbook``,
                          ``parse_skill_analysis``, the 5 routing strategies.
* :mod:`.types`         — verbatim learning-time data types (BetaCompetence,
                          Skill, AgentProfile, ...).
* :mod:`.pool`          — model-alias -> local/cloud resolution.
* :mod:`.tools`         — search / enhance_reasoning / answer executors.
* :mod:`.orchestrator`  — the multi-round search->code->answer loop.
* :mod:`.agent`         — :class:`SkillOrchestraAgent`, the harness entry.
"""

from __future__ import annotations

from .agent import SkillOrchestraAgent

__all__ = ["SkillOrchestraAgent"]
