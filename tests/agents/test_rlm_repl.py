"""Tests for the RLM REPL environment."""

from __future__ import annotations

from openjarvis.agents.rlm_repl import RLMRepl


class TestRLMReplBasics:
    """Basic execution and variable persistence."""

    def test_variable_persistence(self):
        repl = RLMRepl()
        repl.execute("x = 42")
        repl.execute("y = x + 1")
        assert repl.get_variable("x") == 42
        assert repl.get_variable("y") == 43

    def test_code_execution_stdout(self):
        repl = RLMRepl()
        output = repl.execute("print('hello')")
        assert "hello" in output

    def test_function_definition(self):
        repl = RLMRepl()
        repl.execute("def double(n): return n * 2")
        repl.execute("result = double(5)")
        assert repl.get_variable("result") == 10

    def test_multiline_code(self):
        repl = RLMRepl()
        code = "for i in range(3):\n    print(i)"
        output = repl.execute(code)
        assert "0" in output
        assert "1" in output
        assert "2" in output

    def test_set_and_get_variable(self):
        repl = RLMRepl()
        repl.set_variable("x", 99)
        assert repl.get_variable("x") == 99

    def test_get_missing_variable(self):
        repl = RLMRepl()
        assert repl.get_variable("missing") is None


class TestRLMReplSecurity:
    """Security: blocked patterns and safe modules."""

    def test_blocked_os_system(self):
        repl = RLMRepl()
        output = repl.execute("os.system('ls')")
        assert "Blocked" in output

    def test_blocked_subprocess(self):
        repl = RLMRepl()
        output = repl.execute("import subprocess")
        assert "Blocked" in output

    def test_blocked_open(self):
        repl = RLMRepl()
        output = repl.execute("f = open('/etc/passwd')")
        assert "Blocked" in output

    def test_blocked_dunder_import(self):
        repl = RLMRepl()
        output = repl.execute("__import__('os')")
        assert "Blocked" in output

    def test_blocked_socket(self):
        repl = RLMRepl()
        output = repl.execute("import socket")
        assert "Blocked" in output

    def test_safe_modules_available(self):
        repl = RLMRepl()
        # json, re, math should be pre-injected
        assert repl.get_variable("json") is not None
        assert repl.get_variable("re") is not None
        assert repl.get_variable("math") is not None

    def test_safe_module_usage(self):
        repl = RLMRepl()
        repl.execute("result = json.dumps({'a': 1})")
        assert repl.get_variable("result") == '{"a": 1}'

    def test_math_module_usage(self):
        repl = RLMRepl()
        repl.execute("result = math.sqrt(16)")
        assert repl.get_variable("result") == 4.0

    def test_security_check_returns_none_for_safe_code(self):
        repl = RLMRepl()
        assert repl.security_check("x = 1 + 2") is None

    def test_security_check_returns_error_for_blocked(self):
        repl = RLMRepl()
        result = repl.security_check("os.system('rm -rf /')")
        assert result is not None
        assert "Blocked" in result


class TestRLMReplTermination:
    """FINAL, FINAL_VAR, and answer dict termination."""

    def test_final_terminates(self):
        repl = RLMRepl()
        assert not repl.is_terminated
        repl.execute("FINAL('done')")
        assert repl.is_terminated
        assert repl.final_answer == "done"

    def test_final_var_terminates(self):
        repl = RLMRepl()
        repl.execute("result = 42")
        repl.execute("FINAL_VAR('result')")
        assert repl.is_terminated
        assert repl.final_answer == 42

    def test_answer_dict_terminates(self):
        repl = RLMRepl()
        repl.execute("answer['value'] = 'hello'")
        repl.execute("answer['ready'] = True")
        assert repl.is_terminated
        assert repl.final_answer == "hello"

    def test_answer_dict_not_ready(self):
        repl = RLMRepl()
        repl.execute("answer['value'] = 'hello'")
        assert not repl.is_terminated

    def test_final_with_complex_value(self):
        repl = RLMRepl()
        repl.execute("FINAL([1, 2, 3])")
        assert repl.is_terminated
        assert repl.final_answer == [1, 2, 3]


class TestRLMReplCallbacks:
    """llm_query and llm_batch callbacks."""

    def test_llm_query_callback(self):
        calls = []

        def mock_query(prompt):
            calls.append(prompt)
            return f"answer: {prompt}"

        repl = RLMRepl(llm_query_fn=mock_query)
        repl.execute("result = llm_query('What is 2+2?')")
        assert len(calls) == 1
        assert calls[0] == "What is 2+2?"
        assert repl.get_variable("result") == "answer: What is 2+2?"

    def test_llm_batch_callback(self):
        def mock_batch(prompts):
            return [f"answer: {p}" for p in prompts]

        repl = RLMRepl(llm_batch_fn=mock_batch)
        repl.execute("results = llm_batch(['q1', 'q2'])")
        results = repl.get_variable("results")
        assert len(results) == 2
        assert results[0] == "answer: q1"
        assert results[1] == "answer: q2"

    def test_no_callback_raises(self):
        """If llm_query not injected, calling it raises NameError."""
        repl = RLMRepl()
        output = repl.execute("llm_query('test')")
        assert "NameError" in output

    def test_tool_call_callback(self):
        calls = []

        def mock_tool(tool_name, params):
            calls.append((tool_name, params))
            return "tool-output"

        repl = RLMRepl(tool_call_fn=mock_tool)
        out = repl.execute("result = tool_call('calculator', {'expression': '2+2'})")
        assert out == ""
        assert calls == [("calculator", {"expression": "2+2"})]
        assert repl.get_variable("result") == "tool-output"

    def test_direct_tool_wrapper_with_kwargs(self):
        calls = []

        def mock_tool(tool_name, params):
            calls.append((tool_name, params))
            return "file contents"

        repl = RLMRepl(
            tool_call_fn=mock_tool,
            tool_arg_names={"file_read": "path"},
        )
        out = repl.execute('result = file_read(path="README.md")')
        assert out == ""
        assert calls == [("file_read", {"path": "README.md"})]
        assert repl.get_variable("result") == "file contents"

    def test_direct_tool_wrapper_with_positional_arg(self):
        calls = []

        def mock_tool(tool_name, params):
            calls.append((tool_name, params))
            return "cargo toml"

        repl = RLMRepl(
            tool_call_fn=mock_tool,
            tool_arg_names={"file_read": "path"},
        )
        out = repl.execute('result = file_read("rust/Cargo.toml")')
        assert out == ""
        assert calls == [("file_read", {"path": "rust/Cargo.toml"})]
        assert repl.get_variable("result") == "cargo toml"


class TestRLMReplOutput:
    """Output truncation and error handling."""

    def test_output_truncation(self):
        repl = RLMRepl(max_output_chars=50)
        repl.execute("print('x' * 200)")
        output = repl.execute("print('y' * 200)")
        assert "truncated" in output

    def test_syntax_error(self):
        repl = RLMRepl()
        output = repl.execute("def foo(")
        assert "SyntaxError" in output

    def test_runtime_error(self):
        repl = RLMRepl()
        output = repl.execute("1 / 0")
        assert "ZeroDivisionError" in output

    def test_name_error(self):
        repl = RLMRepl()
        output = repl.execute("print(undefined_var)")
        assert "NameError" in output

    def test_error_doesnt_corrupt_state(self):
        repl = RLMRepl()
        repl.execute("x = 10")
        repl.execute("1 / 0")  # Error
        assert repl.get_variable("x") == 10

    def test_no_output_returns_empty(self):
        repl = RLMRepl()
        output = repl.execute("x = 1")
        assert output == ""
