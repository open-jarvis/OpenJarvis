"""Skill source resolvers — Hermes, OpenClaw, generic GitHub, local Claude."""

from openjarvis.skills.sources.base import ResolvedSkill, SourceResolver
from openjarvis.skills.sources.claude import ClaudeResolver
from openjarvis.skills.sources.github import GitHubResolver
from openjarvis.skills.sources.hermes import HERMES_REPO_URL, HermesResolver
from openjarvis.skills.sources.openclaw import OPENCLAW_REPO_URL, OpenClawResolver

__all__ = [
    "ClaudeResolver",
    "GitHubResolver",
    "HERMES_REPO_URL",
    "HermesResolver",
    "OPENCLAW_REPO_URL",
    "OpenClawResolver",
    "ResolvedSkill",
    "SourceResolver",
]
