"""RBAC capability system — fine-grained permission model for tool dispatch."""

from __future__ import annotations

import fnmatch
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class Capability(str, Enum):
    """Fine-grained capability labels."""

    FILE_READ = "file:read"
    FILE_WRITE = "file:write"
    NETWORK_FETCH = "network:fetch"
    CODE_EXECUTE = "code:execute"
    MEMORY_READ = "memory:read"
    MEMORY_WRITE = "memory:write"
    CHANNEL_SEND = "channel:send"
    TOOL_INVOKE = "tool:invoke"
    SCHEDULE_CREATE = "schedule:create"
    SYSTEM_ADMIN = "system:admin"


@dataclass(slots=True)
class CapabilityGrant:
    """A single capability grant for an agent."""

    capability: str  # Capability value or glob pattern
    pattern: str = "*"  # resource glob pattern


@dataclass(slots=True)
class AgentPolicy:
    """Policy for a specific agent."""

    agent_id: str
    grants: List[CapabilityGrant] = field(default_factory=list)
    deny: List[str] = field(default_factory=list)  # explicit denials


class CapabilityPolicy:
    """RBAC capability policy for tool dispatch.

    Checks whether an agent has the required capability to invoke a tool.
    Policy can be loaded from a JSON file or configured programmatically.

    Default policy: if no explicit policy exists for an agent, all
    capabilities are granted (open by default). Set ``default_deny=True``
    to flip to deny-by-default.
    """

    def __init__(
        self,
        *,
        policy_path: Optional[str] = None,
        default_deny: bool = False,
    ) -> None:
        self._policies: Dict[str, AgentPolicy] = {}
        self._default_deny = default_deny

        from openjarvis._rust_bridge import get_rust_module

        _rust = get_rust_module()
        self._rust_impl = _rust.CapabilityPolicy(default_deny=default_deny)

        if policy_path:
            self._load_file(Path(policy_path))

    def grant(self, agent_id: str, capability: str, pattern: str = "*") -> None:
        """Grant a capability to an agent."""
        policy = self._policies.setdefault(
            agent_id,
            AgentPolicy(agent_id=agent_id),
        )
        policy.grants.append(CapabilityGrant(capability=capability, pattern=pattern))
        self._rust_impl.grant(agent_id, capability, pattern)

    def deny(self, agent_id: str, capability: str) -> None:
        """Explicitly deny a capability to an agent."""
        policy = self._policies.setdefault(
            agent_id,
            AgentPolicy(agent_id=agent_id),
        )
        policy.deny.append(capability)
        self._rust_impl.deny(agent_id, capability)

    _DEFAULT_AGENT = "_default"

    def check(self, agent_id: str, capability: str, resource: str = "") -> bool:
        """Check whether *agent_id* has *capability* for *resource*.

        Falls back to the ``_default`` wildcard agent's grants only when
        *agent_id* has no explicit policy of its own. This lets a baseline be
        granted once via
        ``grant("_default", ...)`` instead of needing to know every
        dynamically-created managed-agent UUID ahead of time while preserving
        the invariant that an agent-specific denial always wins.
        """
        if agent_id == self._DEFAULT_AGENT or agent_id in self._policies:
            return self._rust_impl.check(agent_id, capability, resource)
        if self._DEFAULT_AGENT in self._policies:
            return self._rust_impl.check(self._DEFAULT_AGENT, capability, resource)
        return self._rust_impl.check(agent_id, capability, resource)

    def _check_python(self, agent_id: str, capability: str, resource: str = "") -> bool:
        """Legacy Python check — kept for reference only."""
        policy = self._policies.get(agent_id)
        if policy is None:
            # No explicit policy — use default
            return not self._default_deny

        # Explicit denials take precedence
        for denied in policy.deny:
            if fnmatch.fnmatch(capability, denied):
                return False

        # Check grants
        for grant in policy.grants:
            if fnmatch.fnmatch(capability, grant.capability):
                if resource and grant.pattern != "*":
                    if fnmatch.fnmatch(resource, grant.pattern):
                        return True
                else:
                    return True

        # No matching grant found
        return not self._default_deny

    def list_grants(self, agent_id: str) -> List[CapabilityGrant]:
        """List all grants for an agent."""
        policy = self._policies.get(agent_id)
        return list(policy.grants) if policy else []

    def list_agents(self) -> List[str]:
        """List all agents with explicit policies."""
        return list(self._policies.keys())

    def _load_file(self, path: Path) -> None:
        """Load policy from a JSON file."""
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            for agent_data in data.get("agents", []):
                agent_id = agent_data["agent_id"]
                for grant_data in agent_data.get("grants", []):
                    self.grant(
                        agent_id,
                        grant_data["capability"],
                        grant_data.get("pattern", "*"),
                    )
                for denied in agent_data.get("deny", []):
                    self.deny(agent_id, denied)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("Failed to parse capability policy: %s", exc)

    def save(self, path: Path) -> None:
        """Save policy to a JSON file."""
        agents = []
        for agent_id, policy in self._policies.items():
            agents.append(
                {
                    "agent_id": agent_id,
                    "grants": [
                        {"capability": g.capability, "pattern": g.pattern}
                        for g in policy.grants
                    ],
                    "deny": policy.deny,
                }
            )
        path.write_text(json.dumps({"agents": agents}, indent=2))


# Canonical capability requirements for every in-tree tool.  This table is a
# security floor: ToolSpec declarations may add requirements, but they may not
# weaken these.  Keep explicitly-safe tools in the table with an empty list so
# an omitted future built-in can be distinguished from a reviewed safe one.
DEFAULT_TOOL_CAPABILITIES: Dict[str, List[str]] = {
    "agent_kill": [Capability.SYSTEM_ADMIN],
    "agent_list": [Capability.SYSTEM_ADMIN],
    "agent_send": [Capability.SYSTEM_ADMIN],
    "agent_spawn": [Capability.SYSTEM_ADMIN],
    "apply_patch": [Capability.FILE_WRITE],
    "audio_transcribe": [Capability.FILE_READ, Capability.NETWORK_FETCH],
    "browser_axtree": [Capability.NETWORK_FETCH],
    "browser_click": [Capability.NETWORK_FETCH],
    "browser_extract": [Capability.NETWORK_FETCH],
    "browser_navigate": [Capability.NETWORK_FETCH],
    "browser_screenshot": [Capability.NETWORK_FETCH],
    "browser_type": [Capability.NETWORK_FETCH],
    "calculator": [],
    "calendar_search": [Capability.FILE_READ],
    "calendar_upcoming": [Capability.FILE_READ],
    "cancel_scheduled_task": [Capability.SCHEDULE_CREATE],
    "channel_list": [Capability.SYSTEM_ADMIN],
    "channel_send": [Capability.CHANNEL_SEND],
    "channel_status": [Capability.SYSTEM_ADMIN],
    "check_permission": [Capability.MEMORY_READ],
    "code_interpreter": [Capability.CODE_EXECUTE],
    "code_interpreter_docker": [Capability.CODE_EXECUTE],
    "db_query": [Capability.CODE_EXECUTE],
    "digest_collect": [Capability.MEMORY_READ, Capability.NETWORK_FETCH],
    "docker_shell_exec": [Capability.CODE_EXECUTE],
    "execute_pending_actions": [
        Capability.SYSTEM_ADMIN,
        Capability.CHANNEL_SEND,
        Capability.NETWORK_FETCH,
    ],
    "file_read": [Capability.FILE_READ],
    "file_write": [Capability.FILE_WRITE],
    "get_pending_actions": [Capability.MEMORY_READ],
    "git_commit": [Capability.FILE_WRITE],
    "git_diff": [Capability.FILE_READ],
    "git_log": [Capability.FILE_READ],
    "git_status": [Capability.FILE_READ],
    "http_request": [Capability.NETWORK_FETCH],
    "image_generate": [Capability.NETWORK_FETCH, Capability.FILE_WRITE],
    "kg_add_entity": [Capability.MEMORY_WRITE],
    "kg_add_relation": [Capability.MEMORY_WRITE],
    "kg_neighbors": [Capability.MEMORY_READ],
    "kg_query": [Capability.MEMORY_READ],
    "knowledge_search": [Capability.MEMORY_READ],
    "knowledge_sql": [Capability.MEMORY_READ],
    "list_scheduled_tasks": [Capability.SCHEDULE_CREATE],
    "llm": [Capability.NETWORK_FETCH],
    "memory_index": [Capability.MEMORY_WRITE],
    "memory_manage": [Capability.MEMORY_READ, Capability.MEMORY_WRITE],
    "memory_retrieve": [Capability.MEMORY_READ],
    "memory_search": [Capability.MEMORY_READ],
    "memory_store": [Capability.MEMORY_WRITE],
    "pause_scheduled_task": [Capability.SCHEDULE_CREATE],
    "pdf_extract": [Capability.FILE_READ],
    "queue_action": [Capability.MEMORY_WRITE],
    "record_decision": [Capability.SYSTEM_ADMIN, Capability.MEMORY_WRITE],
    "repl": [Capability.CODE_EXECUTE],
    "resume_scheduled_task": [Capability.SCHEDULE_CREATE],
    "retrieval": [Capability.MEMORY_READ],
    "scan_chunks": [Capability.MEMORY_READ],
    "schedule_task": [Capability.SCHEDULE_CREATE],
    "shell_exec": [Capability.CODE_EXECUTE],
    "skill_manage": [Capability.FILE_READ, Capability.FILE_WRITE],
    "text_to_speech": [Capability.NETWORK_FETCH, Capability.FILE_WRITE],
    "think": [],
    "user_profile_manage": [Capability.FILE_READ, Capability.FILE_WRITE],
    "web_search": [Capability.NETWORK_FETCH],
}


def canonical_tool_capabilities(tool: Any) -> List[str]:
    """Return the non-bypassable capability floor for *tool*.

    Third-party tools remain governed by their ToolSpec.  An in-tree tool that
    was newly registered without being inventoried fails closed as
    ``system:admin`` instead of silently becoming unrestricted.
    """
    name = tool.spec.name
    if name in DEFAULT_TOOL_CAPABILITIES:
        return list(DEFAULT_TOOL_CAPABILITIES[name])
    module = type(tool).__module__
    if (
        module == "openjarvis.tools"
        or module.startswith("openjarvis.tools.")
        or module == "openjarvis.scheduler.tools"
    ):
        logger.error("Built-in tool %r has no canonical capability inventory", name)
        return [Capability.SYSTEM_ADMIN]
    return []


__all__ = [
    "AgentPolicy",
    "Capability",
    "CapabilityGrant",
    "CapabilityPolicy",
    "canonical_tool_capabilities",
    "DEFAULT_TOOL_CAPABILITIES",
]
