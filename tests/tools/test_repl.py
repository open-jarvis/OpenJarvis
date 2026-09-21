"""Tests for the persistent REPL tool."""

from __future__ import annotations

import time

from openjarvis.core.registry import ToolRegistry
from openjarvis.tools.repl import ReplTool


class TestReplSpec:
    def test_spec_name(self):
        tool = ReplTool()
        assert tool.spec.name == "repl"

    def test_spec_category(self):
        tool = ReplTool()
        assert tool.spec.category == "code"

    def test_structured_object_text_opt_in(self):
        tool = ReplTool()
        assert tool.spec.metadata["structured_allow_object_text"] is True

    def test_spec_parameters(self):
        tool = ReplTool()
        params = tool.spec.parameters
        assert params["type"] == "object"
        assert "code" in params["properties"]
        assert "session_id" in params["properties"]
        assert "reset" in params["properties"]
        assert params["required"] == ["code"]

    def test_tool_id(self):
        tool = ReplTool()
        assert tool.tool_id == "repl"

    def test_to_openai_function(self):
        tool = ReplTool()
        fn = tool.to_openai_function()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "repl"


class TestReplBasicExecution:
    def test_expression(self):
        tool = ReplTool()
        result = tool.execute(code="2 + 2")
        assert result.success
        assert "4" in result.content

    def test_print(self):
        tool = ReplTool()
        result = tool.execute(code="print('hello')")
        assert result.success
        assert "hello" in result.content

    def test_multiline(self):
        tool = ReplTool()
        result = tool.execute(code="x = 5\nprint(x * 2)")
        assert result.success
        assert "10" in result.content

    def test_no_output(self):
        tool = ReplTool()
        result = tool.execute(code="x = 42")
        assert result.success
        assert result.content == "(no output)"


class TestReplStatePersistence:
    def test_variable_persists(self):
        tool = ReplTool()
        r1 = tool.execute(code="x = 42")
        sid = r1.metadata["session_id"]
        r2 = tool.execute(code="print(x)", session_id=sid)
        assert r2.success
        assert "42" in r2.content

    def test_function_persists(self):
        tool = ReplTool()
        r1 = tool.execute(code="def square(n): return n * n")
        sid = r1.metadata["session_id"]
        r2 = tool.execute(code="square(7)", session_id=sid)
        assert r2.success
        assert "49" in r2.content

    def test_import_persists(self):
        tool = ReplTool()
        r1 = tool.execute(code="import math")
        sid = r1.metadata["session_id"]
        r2 = tool.execute(code="math.sqrt(16)", session_id=sid)
        assert r2.success
        assert "4.0" in r2.content

    def test_class_persists(self):
        tool = ReplTool()
        r1 = tool.execute(code="class Foo:\n    val = 99")
        sid = r1.metadata["session_id"]
        r2 = tool.execute(code="Foo.val", session_id=sid)
        assert r2.success
        assert "99" in r2.content

    def test_mutable_state_across_calls(self):
        tool = ReplTool()
        r1 = tool.execute(code="data = []")
        sid = r1.metadata["session_id"]
        tool.execute(code="data.append(1)", session_id=sid)
        tool.execute(code="data.append(2)", session_id=sid)
        r4 = tool.execute(code="print(data)", session_id=sid)
        assert "[1, 2]" in r4.content


class TestReplSessionManagement:
    def test_auto_create_session(self):
        tool = ReplTool()
        result = tool.execute(code="x = 1")
        assert "session_id" in result.metadata
        assert result.metadata["session_id"]

    def test_explicit_session_id(self):
        tool = ReplTool()
        result = tool.execute(code="x = 1", session_id="my-session")
        assert result.metadata["session_id"] == "my-session"

    def test_session_isolation(self):
        tool = ReplTool()
        tool.execute(code="x = 'session_a'", session_id="a")
        tool.execute(code="x = 'session_b'", session_id="b")
        r3 = tool.execute(code="print(x)", session_id="a")
        assert "session_a" in r3.content

    def test_session_reset(self):
        tool = ReplTool()
        tool.execute(code="x = 42", session_id="s1")
        tool.execute(code="print('reset')", session_id="s1", reset=True)
        result = tool.execute(code="print(x)", session_id="s1")
        assert not result.success
        assert "NameError" in result.content

    def test_execution_count(self):
        tool = ReplTool()
        r1 = tool.execute(code="x = 1", session_id="cnt")
        assert r1.metadata["execution_count"] == 1
        r2 = tool.execute(code="x += 1", session_id="cnt")
        assert r2.metadata["execution_count"] == 2

    def test_lru_eviction(self):
        tool = ReplTool(max_sessions=2)
        tool.execute(code="x = 'first'", session_id="s1")
        time.sleep(0.01)
        tool.execute(code="x = 'second'", session_id="s2")
        time.sleep(0.01)
        # s1 is oldest; creating s3 should evict s1
        tool.execute(code="x = 'third'", session_id="s3")
        # s1 should be gone — new session with no x
        result = tool.execute(code="print(x)", session_id="s1")
        assert "NameError" in result.content


class TestReplErrorHandling:
    def test_syntax_error(self):
        tool = ReplTool()
        result = tool.execute(code="def foo(")
        assert not result.success
        assert "SyntaxError" in result.content

    def test_runtime_error(self):
        tool = ReplTool()
        result = tool.execute(code="1 / 0")
        assert not result.success
        assert "ZeroDivisionError" in result.content

    def test_name_error(self):
        tool = ReplTool()
        result = tool.execute(code="print(undefined)")
        assert not result.success
        assert "NameError" in result.content

    def test_error_doesnt_corrupt_session(self):
        tool = ReplTool()
        tool.execute(code="x = 10", session_id="err")
        tool.execute(code="1 / 0", session_id="err")  # Error
        r3 = tool.execute(code="print(x)", session_id="err")
        assert r3.success
        assert "10" in r3.content

    def test_no_code(self):
        tool = ReplTool()
        result = tool.execute(code="")
        assert not result.success
        assert "No code" in result.content


class TestReplSecurity:
    def test_blocked_os_system(self):
        tool = ReplTool()
        result = tool.execute(code="os.system('ls')")
        assert not result.success
        assert "Blocked" in result.content

    def test_blocked_subprocess(self):
        tool = ReplTool()
        result = tool.execute(code="import subprocess")
        assert not result.success
        assert "Blocked" in result.content

    def test_blocked_open(self):
        tool = ReplTool()
        result = tool.execute(code="f = open('file.txt')")
        assert not result.success
        assert "Blocked" in result.content

    def test_safe_imports_allowed(self):
        tool = ReplTool()
        result = tool.execute(code="import math\nprint(math.pi)")
        assert result.success
        assert "3.14" in result.content

    def test_safe_json_import(self):
        tool = ReplTool()
        result = tool.execute(code="import json\nprint(json.dumps({'a': 1}))")
        assert result.success
        assert '"a"' in result.content

    def test_unsafe_import_blocked(self):
        tool = ReplTool()
        result = tool.execute(code="import os")
        assert not result.success
        assert "not allowed" in result.content


class TestReplTimeout:
    def test_sleep_timeout(self):
        tool = ReplTool(timeout=1)
        result = tool.execute(code="import time\ntime.sleep(10)")
        assert not result.success
        assert "timed out" in result.content

    def test_infinite_loop_timeout(self):
        tool = ReplTool(timeout=1)
        result = tool.execute(code="while True: pass")
        assert not result.success
        assert "timed out" in result.content


class TestReplOutput:
    def test_truncation(self):
        tool = ReplTool(max_output=50)
        result = tool.execute(code="print('x' * 200)")
        assert "truncated" in result.content

    def test_expression_display(self):
        """Expressions should show their repr (REPL-like behavior)."""
        tool = ReplTool()
        result = tool.execute(code="2 + 2")
        assert "4" in result.content

    def test_string_expression_display(self):
        tool = ReplTool()
        result = tool.execute(code="'hello'")
        assert "hello" in result.content


class TestReplRegistration:
    def test_registered(self):
        # Re-register after conftest clears all registries
        ToolRegistry.register_value("repl", ReplTool)
        assert ToolRegistry.contains("repl")
