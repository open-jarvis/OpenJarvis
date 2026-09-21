"""Verify that importing openjarvis.tools registers all built-in tools."""

from __future__ import annotations

import importlib
import subprocess
import sys

from openjarvis.core.registry import ToolRegistry

# Every tool name that should be registered after importing the package.
EXPECTED_TOOLS = {
    # calculator.py
    "calculator",
    # think.py
    "think",
    # retrieval.py
    "retrieval",
    # llm_tool.py
    "llm",
    # file_read.py
    "file_read",
    # file_write.py
    "file_write",
    # web_search.py
    "web_search",
    # weather.py
    "get_weather",
    # code_interpreter.py
    "code_interpreter",
    # code_interpreter_docker.py
    "code_interpreter_docker",
    # repl.py
    "repl",
    # storage_tools.py
    "memory_store",
    "memory_retrieve",
    "memory_search",
    "memory_index",
    # channel_tools.py
    "channel_send",
    "channel_list",
    "channel_status",
    # http_request.py
    "http_request",
    # shell_exec.py
    "shell_exec",
    # memory_manage.py
    "memory_manage",
    # user_profile_manage.py
    "user_profile_manage",
    # skill_manage.py
    "skill_manage",
    # apply_patch.py
    "apply_patch",
    # git_tool.py
    "git_status",
    "git_diff",
    "git_commit",
    "git_log",
    # db_query.py
    "db_query",
    # pdf_tool.py
    "pdf_extract",
    # image_tool.py
    "image_generate",
    # audio_tool.py
    "audio_transcribe",
    # text_to_speech.py
    "text_to_speech",
    # knowledge_tools.py
    "kg_add_entity",
    "kg_add_relation",
    "kg_query",
    "kg_neighbors",
    # knowledge_sql.py
    "knowledge_sql",
    # scan_chunks.py
    "scan_chunks",
    # apple_calendar.py
    "calendar_upcoming",
    "calendar_search",
}


def _reload_tool_modules() -> None:
    """Reload all openjarvis.tools.* submodules to re-trigger @register decorators.

    The autouse ``_clean_registries`` fixture clears all registries before each
    test.  A plain ``import openjarvis.tools`` won't re-register because the
    submodules are already cached in ``sys.modules``.  We must reload the
    individual submodules so their class-level ``@ToolRegistry.register``
    decorators execute again.
    """
    for mod_name in list(sys.modules):
        if (
            mod_name.startswith("openjarvis.tools.")
            and not mod_name.endswith("_stubs")
            and not mod_name.endswith("agent_tools")
        ):
            try:
                importlib.reload(sys.modules[mod_name])
            except Exception:
                pass


def test_all_builtin_tools_registered():
    _reload_tool_modules()

    registered = set(ToolRegistry.keys())
    missing = EXPECTED_TOOLS - registered
    assert not missing, (
        f"Tools not registered (missing import in __init__.py?): {sorted(missing)}"
    )


def test_package_import_registers_deep_research_tools():
    """Registration must not depend on another module being imported first."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import openjarvis.tools; "
                "from openjarvis.core.registry import ToolRegistry; "
                "expected = {'knowledge_sql', 'scan_chunks'}; "
                "missing = expected - set(ToolRegistry.keys()); "
                "assert not missing, f'Missing tools: {sorted(missing)}'"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_calendar_tools_register_when_connector_is_imported_first():
    """Connector imports must not suppress calendar tool registration."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import openjarvis.connectors.apple_calendar; "
                "from openjarvis.core.registry import ToolRegistry; "
                "expected = {'calendar_upcoming', 'calendar_search'}; "
                "missing = expected - set(ToolRegistry.keys()); "
                "assert not missing, f'Missing tools: {sorted(missing)}'"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
