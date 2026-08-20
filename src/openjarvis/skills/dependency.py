"""Dependency graph: cycle detection, topological sort, capability union."""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Dict, List, Set

if TYPE_CHECKING:
    from openjarvis.skills.types import SkillManifest


class DependencyCycleError(Exception):
    """Raised when a cycle is detected in the skill dependency graph."""


class DepthExceededError(Exception):
    """Raised when the dependency depth exceeds the configured maximum."""


def build_dependency_graph(skills: Dict[str, "SkillManifest"]) -> Dict[str, Set[str]]:
    """Build a directed graph of skill dependencies.

    Each key maps to the set of skill names it directly depends on, drawn from
    both the ``depends`` field and any ``skill_name`` references in steps.
    Only edges pointing to skills that are present in the *skills* dict are
    included (unknown refs are silently dropped so that the graph stays clean
    for topological analysis).

    Args:
        skills: Mapping of skill name → SkillManifest.

    Returns:
        Dict mapping each skill name to the set of its direct dependencies.
    """
    graph: Dict[str, Set[str]] = {name: set() for name in skills}

    for name, manifest in skills.items():
        # Explicit depends list
        for dep in manifest.depends:
            if dep in skills:
                graph[name].add(dep)

        # Implicit deps via step skill_name references
        for step in manifest.steps:
            if step.skill_name and step.skill_name in skills:
                graph[name].add(step.skill_name)

    return graph


def validate_dependencies(
    skills: Dict[str, "SkillManifest"],
    *,
    max_depth: int = 5,
) -> List[str]:
    """Validate the skill dependency graph and return a topological ordering.

    Uses Kahn's algorithm for topological sort and cycle detection.  After a
    valid ordering is found, a DFS checks that no skill's transitive dependency
    chain exceeds *max_depth*.  Dependencies that reference unknown skills are
    silently skipped.

    Args:
        skills: Mapping of skill name → SkillManifest.
        max_depth: Maximum allowed dependency chain depth (default 5).

    Returns:
        List of skill names in valid topological order (dependencies first).

    Raises:
        DependencyCycleError: If the graph contains a cycle.
        DepthExceededError: If any skill's dependency chain depth exceeds max_depth.
    """
    graph = build_dependency_graph(skills)

    # --- Kahn's algorithm ---
    in_degree: Dict[str, int] = {name: 0 for name in graph}
    for name in graph:
        for dep in graph[name]:
            in_degree[dep]  # ensure present (already is, but be explicit)

    # Count how many skills depend on each node
    reverse: Dict[str, Set[str]] = {name: set() for name in graph}
    for name, deps in graph.items():
        for dep in deps:
            reverse[dep].add(name)
        # re-compute in_degree from scratch below

    # Compute in-degree: number of dependencies each skill has (within the graph)
    in_degree = {name: len(deps) for name, deps in graph.items()}

    queue: deque[str] = deque(name for name, deg in in_degree.items() if deg == 0)
    order: List[str] = []

    while queue:
        node = queue.popleft()
        order.append(node)
        for dependent in reverse[node]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(order) != len(graph):
        raise DependencyCycleError(
            "Cycle detected in skill dependency graph. "
            f"Skills involved: {set(graph) - set(order)}"
        )

    # --- Depth enforcement via DFS ---
    depth_cache: Dict[str, int] = {}

    def _depth(name: str, visiting: Set[str]) -> int:
        if name in depth_cache:
            return depth_cache[name]
        deps = graph.get(name, set())
        if not deps:
            depth_cache[name] = 1
            return 1
        visiting.add(name)
        max_child = max(_depth(d, visiting) for d in deps)
        visiting.discard(name)
        result = max_child + 1
        depth_cache[name] = result
        return result

    for name in graph:
        d = _depth(name, set())
        if d > max_depth:
            raise DepthExceededError(
                f"Skill '{name}' depth {d} exceeds max_depth={max_depth}"
            )

    return order


def compute_capability_union(
    skill_name: str,
    skills: Dict[str, "SkillManifest"],
) -> List[str]:
    """Compute the union of all required_capabilities transitively needed by a skill.

    Performs a DFS over the dependency graph, collecting ``required_capabilities``
    from the skill itself and all of its transitive dependencies.  Duplicates are
    removed while preserving a deterministic order (first-seen wins).

    Args:
        skill_name: Name of the root skill to start from.
        skills: Mapping of skill name → SkillManifest.

    Returns:
        Deduplicated list of capability strings.  Returns an empty list if the
        skill is not found.
    """
    if skill_name not in skills:
        return []

    graph = build_dependency_graph(skills)
    seen_skills: Set[str] = set()
    seen_caps: Set[str] = set()
    caps_ordered: List[str] = []

    def _dfs(name: str) -> None:
        if name in seen_skills:
            return
        seen_skills.add(name)
        manifest = skills.get(name)
        if manifest is None:
            return
        for cap in manifest.required_capabilities:
            if cap not in seen_caps:
                seen_caps.add(cap)
                caps_ordered.append(cap)
        for dep in graph.get(name, set()):
            _dfs(dep)

    _dfs(skill_name)
    return caps_ordered


__all__ = [
    "DependencyCycleError",
    "DepthExceededError",
    "build_dependency_graph",
    "validate_dependencies",
    "compute_capability_union",
]
