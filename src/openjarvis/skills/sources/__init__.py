"""Skill source resolvers — Hermes, OpenClaw, generic GitHub."""

from openjarvis.skills.sources.base import ResolvedSkill, SourceResolver
from openjarvis.skills.sources.github import GitHubResolver
from openjarvis.skills.sources.hermes import HERMES_REPO_URL, HermesResolver
from openjarvis.skills.sources.openclaw import OPENCLAW_REPO_URL, OpenClawResolver

__all__ = [
    "GitHubResolver",
    "HERMES_REPO_URL",
    "HermesResolver",
    "OPENCLAW_REPO_URL",
    "OpenClawResolver",
    "ResolvedSkill",
    "SourceResolver",
]
