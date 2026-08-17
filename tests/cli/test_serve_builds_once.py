"""serve() must compose through SystemBuilder, not by hand.

Hand-assembling JarvisSystem was how serve.py dodged a double build() (#263),
and it cost 10-18 of the 25 wiring arguments: scheduler, workflow_engine,
skill_manager, speech_backend, audit_logger, container_runner, agent_scheduler,
channel_backend, gpu_monitor, scheduler_store -- plus _learning_orchestrator
and _skill_few_shot_examples, which build() attaches after construction.
"""

from __future__ import annotations

import ast
import importlib
import inspect


def _serve_source() -> str:
    # importlib, not ``import openjarvis.cli.serve as m``: the package exports a
    # click Command under the same attribute name, which would shadow the module.
    serve_module = importlib.import_module("openjarvis.cli.serve")

    return inspect.getsource(serve_module)


def test_serve_does_not_hand_assemble_jarvis_system():
    tree = ast.parse(_serve_source())
    direct = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", None) == "JarvisSystem"
    ]
    assert not direct, "serve.py must build through SystemBuilder"


def test_serve_calls_build_exactly_once():
    source = _serve_source()
    assert source.count(".build()") == 1


def test_serve_enables_every_subsystem_the_runtime_needs():
    source = _serve_source()
    for seam in (
        ".scheduler(True)",
        ".workflow(True)",
        ".sessions(True)",
        ".operators(True)",
        ".telemetry(",
        ".traces(",
        ".event_bus(",
        ".engine_instance(",
    ):
        assert seam in source, f"missing {seam}"
