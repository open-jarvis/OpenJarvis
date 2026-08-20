"""Tests for the code interpreter tool."""

from __future__ import annotations

from openjarvis.core.registry import ToolRegistry
from openjarvis.tools.code_interpreter import CodeInterpreterTool


class TestCodeInterpreterTool:
    def test_spec_name_and_category(self):
        tool = CodeInterpreterTool()
        assert tool.spec.name == "code_interpreter"
        assert tool.spec.category == "code"

    def test_spec_parameters_require_code(self):
        tool = CodeInterpreterTool()
        assert "code" in tool.spec.parameters["properties"]
        assert "code" in tool.spec.parameters["required"]

    def test_execute_simple_code(self):
        tool = CodeInterpreterTool()
        result = tool.execute(code="print(2 + 2)")
        assert result.success is True
        assert "4" in result.content

    def test_execute_with_imports(self):
        tool = CodeInterpreterTool()
        result = tool.execute(code="import math; print(round(math.pi, 5))")
        assert result.success is True
        assert "3.14159" in result.content

    def test_execute_multiline(self):
        tool = CodeInterpreterTool()
        code = "x = 10\ny = 20\nprint(x + y)"
        result = tool.execute(code=code)
        assert result.success is True
        assert "30" in result.content

    def test_timeout_protection(self):
        tool = CodeInterpreterTool(timeout=2)
        result = tool.execute(code="import time; time.sleep(10)")
        assert result.success is False
        assert "timed out" in result.content

    def test_syntax_error(self):
        tool = CodeInterpreterTool()
        result = tool.execute(code="def f(\n")
        assert result.success is False
        assert "SyntaxError" in result.content

    def test_runtime_error(self):
        tool = CodeInterpreterTool()
        result = tool.execute(code="print(1/0)")
        assert result.success is False
        assert "ZeroDivisionError" in result.content

    def test_dangerous_os_system_blocked(self):
        tool = CodeInterpreterTool()
        result = tool.execute(code="import os; os.system('ls')")
        assert result.success is False
        assert "Blocked" in result.content
        assert "os.system" in result.content

    def test_dangerous_subprocess_blocked(self):
        tool = CodeInterpreterTool()
        result = tool.execute(code="import subprocess; subprocess.run(['ls'])")
        assert result.success is False
        assert "Blocked" in result.content

    def test_dangerous_eval_blocked(self):
        tool = CodeInterpreterTool()
        result = tool.execute(code="eval('2+2')")
        assert result.success is False
        assert "Blocked" in result.content

    def test_dangerous_open_blocked(self):
        tool = CodeInterpreterTool()
        result = tool.execute(code="f = open('/etc/passwd')")
        assert result.success is False
        assert "Blocked" in result.content

    def test_no_code_provided(self):
        tool = CodeInterpreterTool()
        result = tool.execute(code="")
        assert result.success is False
        assert "No code" in result.content

    def test_no_code_param(self):
        tool = CodeInterpreterTool()
        result = tool.execute()
        assert result.success is False
        assert "No code" in result.content

    def test_output_truncation(self):
        tool = CodeInterpreterTool(max_output=50)
        result = tool.execute(code="print('A' * 200)")
        assert result.success is True
        assert "truncated" in result.content
        assert len(result.content) < 200

    def test_to_openai_function(self):
        tool = CodeInterpreterTool()
        fn = tool.to_openai_function()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "code_interpreter"
        assert "code" in fn["function"]["parameters"]["properties"]

    def test_returncode_in_metadata(self):
        tool = CodeInterpreterTool()
        result = tool.execute(code="print('ok')")
        assert result.success is True
        assert result.metadata["returncode"] == 0

    def test_returncode_nonzero_on_error(self):
        tool = CodeInterpreterTool()
        result = tool.execute(code="raise ValueError('boom')")
        assert result.success is False
        assert result.metadata["returncode"] != 0

    def test_no_output_produces_placeholder(self):
        tool = CodeInterpreterTool()
        result = tool.execute(code="x = 42")
        assert result.success is True
        assert result.content == "(no output)"

    def test_tool_id(self):
        tool = CodeInterpreterTool()
        assert tool.tool_id == "code_interpreter"

    def test_structured_object_text_opt_in(self):
        tool = CodeInterpreterTool()
        assert tool.spec.metadata["structured_allow_object_text"] is True

    def test_registry_registration(self):
        ToolRegistry.register_value("code_interpreter", CodeInterpreterTool)
        assert ToolRegistry.contains("code_interpreter")
