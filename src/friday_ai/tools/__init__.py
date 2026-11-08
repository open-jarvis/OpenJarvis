"""Tools primitive — tool system with ABC interface and built-in tools."""

from __future__ import annotations

from friday_ai.tools._stubs import BaseTool, ToolExecutor, ToolSpec

# Import built-in tools to trigger @ToolRegistry.register() decorators.
# Each is wrapped in try/except so the package loads even before the
# individual tool modules are created.
try:
    import friday_ai.tools.calculator  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.think  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.retrieval  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.llm_tool  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.file_read  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.web_search  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.weather  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.fx_macro  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.code_interpreter  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.code_interpreter_docker  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.repl  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.storage_tools  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.mcp_adapter  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.channel_tools  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.http_request  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.docker_shell_exec  # noqa: F401
    import friday_ai.tools.shell_exec  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.memory_manage  # noqa: F401
except ImportError:
    pass
try:
    import friday_ai.tools.user_profile_manage  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.skill_manage  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.file_write  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.apply_patch  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.git_tool  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.db_query  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.pdf_tool  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.image_tool  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.audio_tool  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.knowledge_tools  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.text_to_speech  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.digest_collect  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.scan_chunks  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.knowledge_sql  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.apple_calendar  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.knowledge_search  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.browser  # noqa: F401
    import friday_ai.tools.browser_axtree  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.tools.proactive_tools  # noqa: F401
except ImportError:
    pass

__all__ = ["BaseTool", "ToolExecutor", "ToolSpec"]
