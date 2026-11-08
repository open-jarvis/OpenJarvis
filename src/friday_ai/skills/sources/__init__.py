"""Skill source resolvers — Hermes, OpenClaw, generic GitHub."""

from friday_ai.skills.sources.base import ResolvedSkill, SourceResolver
from friday_ai.skills.sources.github import GitHubResolver
from friday_ai.skills.sources.hermes import HERMES_REPO_URL, HermesResolver
from friday_ai.skills.sources.openclaw import OPENCLAW_REPO_URL, OpenClawResolver

__all__ = [
    "GitHubResolver",
    "HERMES_REPO_URL",
    "HermesResolver",
    "OPENCLAW_REPO_URL",
    "OpenClawResolver",
    "ResolvedSkill",
    "SourceResolver",
]
