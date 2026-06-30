"""Integration tests for tools."""
import pytest


class TestToolIntegration:
    """Test tool integration."""

    @pytest.mark.asyncio
    async def test_tool_registry(self):
        """Test that tools can be registered and retrieved."""
        try:
            from openjarvis.tools import ToolRegistry
            registry = ToolRegistry()
            assert registry is not None
            tools = registry.list_tools()
            assert isinstance(tools, (list, dict))
        except Exception as e:
            pytest.fail(f"Tool registry integration failed: {e}")
