"""Tests for dependency graph and cycle detection (Task 3)."""

from __future__ import annotations

import pytest

from openjarvis.skills.types import SkillManifest, SkillStep


def _manifest(name, depends=None, capabilities=None, steps=None):
    return SkillManifest(
        name=name,
        depends=depends or [],
        required_capabilities=capabilities or [],
        steps=steps or [],
    )


class TestBuildDependencyGraph:
    def test_no_dependencies(self):
        from openjarvis.skills.dependency import build_dependency_graph

        skills = {"a": _manifest("a")}
        graph = build_dependency_graph(skills)
        assert graph == {"a": set()}

    def test_simple_dependency(self):
        from openjarvis.skills.dependency import build_dependency_graph

        skills = {
            "a": _manifest("a"),
            "b": _manifest("b", depends=["a"]),
        }
        graph = build_dependency_graph(skills)
        assert "a" in graph["b"]
        assert graph["a"] == set()

    def test_step_skill_name_edges(self):
        from openjarvis.skills.dependency import build_dependency_graph

        steps = [SkillStep(skill_name="base_skill", output_key="r")]
        skills = {
            "base_skill": _manifest("base_skill"),
            "composite": _manifest("composite", steps=steps),
        }
        graph = build_dependency_graph(skills)
        assert "base_skill" in graph["composite"]

    def test_combined_depends_and_steps(self):
        from openjarvis.skills.dependency import build_dependency_graph

        steps = [SkillStep(skill_name="step_dep", output_key="r")]
        skills = {
            "explicit_dep": _manifest("explicit_dep"),
            "step_dep": _manifest("step_dep"),
            "main": _manifest("main", depends=["explicit_dep"], steps=steps),
        }
        graph = build_dependency_graph(skills)
        assert "explicit_dep" in graph["main"]
        assert "step_dep" in graph["main"]

    def test_multiple_skills_no_overlap(self):
        from openjarvis.skills.dependency import build_dependency_graph

        skills = {
            "x": _manifest("x"),
            "y": _manifest("y"),
        }
        graph = build_dependency_graph(skills)
        assert graph["x"] == set()
        assert graph["y"] == set()


class TestValidateDependencies:
    def test_valid_topological_sort_simple(self):
        from openjarvis.skills.dependency import validate_dependencies

        skills = {
            "a": _manifest("a"),
            "b": _manifest("b", depends=["a"]),
        }
        order = validate_dependencies(skills)
        assert order.index("a") < order.index("b")

    def test_valid_topological_sort_chain(self):
        from openjarvis.skills.dependency import validate_dependencies

        skills = {
            "a": _manifest("a"),
            "b": _manifest("b", depends=["a"]),
            "c": _manifest("c", depends=["b"]),
        }
        order = validate_dependencies(skills)
        assert order.index("a") < order.index("b")
        assert order.index("b") < order.index("c")

    def test_no_dependencies_returns_all_skills(self):
        from openjarvis.skills.dependency import validate_dependencies

        skills = {
            "x": _manifest("x"),
            "y": _manifest("y"),
        }
        order = validate_dependencies(skills)
        assert set(order) == {"x", "y"}

    def test_cycle_detection_raises(self):
        from openjarvis.skills.dependency import (
            DependencyCycleError,
            validate_dependencies,
        )

        skills = {
            "a": _manifest("a", depends=["b"]),
            "b": _manifest("b", depends=["a"]),
        }
        with pytest.raises(DependencyCycleError):
            validate_dependencies(skills)

    def test_cycle_detection_three_nodes(self):
        from openjarvis.skills.dependency import (
            DependencyCycleError,
            validate_dependencies,
        )

        skills = {
            "a": _manifest("a", depends=["c"]),
            "b": _manifest("b", depends=["a"]),
            "c": _manifest("c", depends=["b"]),
        }
        with pytest.raises(DependencyCycleError):
            validate_dependencies(skills)

    def test_depth_exceeded_raises(self):
        from openjarvis.skills.dependency import (
            DepthExceededError,
            validate_dependencies,
        )

        # Chain of depth 6 exceeds default max_depth=5
        skills = {
            "a": _manifest("a"),
            "b": _manifest("b", depends=["a"]),
            "c": _manifest("c", depends=["b"]),
            "d": _manifest("d", depends=["c"]),
            "e": _manifest("e", depends=["d"]),
            "f": _manifest("f", depends=["e"]),
        }
        with pytest.raises(DepthExceededError):
            validate_dependencies(skills, max_depth=5)

    def test_depth_within_limit_passes(self):
        from openjarvis.skills.dependency import validate_dependencies

        # Chain of depth 3 is within max_depth=5
        skills = {
            "a": _manifest("a"),
            "b": _manifest("b", depends=["a"]),
            "c": _manifest("c", depends=["b"]),
        }
        order = validate_dependencies(skills, max_depth=5)
        assert len(order) == 3

    def test_missing_dependency_silently_skipped(self):
        from openjarvis.skills.dependency import validate_dependencies

        # "missing" is not in skills — should not raise
        skills = {
            "a": _manifest("a", depends=["missing"]),
        }
        order = validate_dependencies(skills)
        assert "a" in order

    def test_custom_max_depth(self):
        from openjarvis.skills.dependency import (
            DepthExceededError,
            validate_dependencies,
        )

        skills = {
            "a": _manifest("a"),
            "b": _manifest("b", depends=["a"]),
            "c": _manifest("c", depends=["b"]),
        }
        # Chain depth 2 exceeds max_depth=1
        with pytest.raises(DepthExceededError):
            validate_dependencies(skills, max_depth=1)


class TestComputeCapabilityUnion:
    def test_single_skill_no_deps(self):
        from openjarvis.skills.dependency import compute_capability_union

        skills = {
            "a": _manifest("a", capabilities=["read_files"]),
        }
        caps = compute_capability_union("a", skills)
        assert "read_files" in caps

    def test_transitive_capabilities(self):
        from openjarvis.skills.dependency import compute_capability_union

        skills = {
            "a": _manifest("a", capabilities=["network"]),
            "b": _manifest("b", depends=["a"], capabilities=["disk_write"]),
        }
        caps = compute_capability_union("b", skills)
        assert "network" in caps
        assert "disk_write" in caps

    def test_deep_transitive_capabilities(self):
        from openjarvis.skills.dependency import compute_capability_union

        skills = {
            "a": _manifest("a", capabilities=["cap_a"]),
            "b": _manifest("b", depends=["a"], capabilities=["cap_b"]),
            "c": _manifest("c", depends=["b"], capabilities=["cap_c"]),
        }
        caps = compute_capability_union("c", skills)
        assert "cap_a" in caps
        assert "cap_b" in caps
        assert "cap_c" in caps

    def test_no_capabilities(self):
        from openjarvis.skills.dependency import compute_capability_union

        skills = {
            "a": _manifest("a"),
            "b": _manifest("b", depends=["a"]),
        }
        caps = compute_capability_union("b", skills)
        assert caps == []

    def test_dedup_capabilities(self):
        from openjarvis.skills.dependency import compute_capability_union

        # Both a and b claim "network"
        skills = {
            "a": _manifest("a", capabilities=["network"]),
            "b": _manifest("b", depends=["a"], capabilities=["network", "disk"]),
        }
        caps = compute_capability_union("b", skills)
        assert caps.count("network") == 1
        assert "disk" in caps

    def test_missing_skill_returns_empty(self):
        from openjarvis.skills.dependency import compute_capability_union

        skills = {}
        caps = compute_capability_union("nonexistent", skills)
        assert caps == []
