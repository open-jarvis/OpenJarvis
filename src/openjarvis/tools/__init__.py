"""Tools primitive — tool system with ABC interface and built-in tools."""

from __future__ import annotations

from openjarvis.tools._stubs import BaseTool, ToolExecutor, ToolSpec

# Import built-in tools to trigger @ToolRegistry.register() decorators.
# Each is wrapped in try/except so the package loads even before the
# individual tool modules are created.
try:
    import openjarvis.tools.calculator  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.tools.think  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.tools.retrieval  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.tools.llm_tool  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.tools.file_read  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.tools.web_search  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.tools.code_interpreter  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.tools.code_interpreter_docker  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.tools.repl  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.tools.storage_tools  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.tools.mcp_adapter  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.tools.channel_tools  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.tools.http_request  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.tools.shell_exec  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.tools.memory_manage  # noqa: F401
except ImportError:
    pass
try:
    import openjarvis.tools.user_profile_manage  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.tools.skill_manage  # noqa: F401
except ImportError:
    pass

__all__ = ["BaseTool", "ToolExecutor", "ToolSpec"]
