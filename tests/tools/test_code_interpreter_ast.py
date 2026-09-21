"""code_interpreter: AST validation blocks the old substring bypasses."""

from __future__ import annotations

import pytest

from openjarvis.tools.code_interpreter import _validate_ast


class TestCodeInterpreterValidation:
    @pytest.mark.parametrize(
        "code",
        [
            "import os",
            "import subprocess as s",
            "from os import system",
            "import io",
            "from io import open as reader",
            "import platform",
            "getattr(__builtins__, 'system')",
            "eval ('1+1')",  # a space defeated the old substring check
            "().__class__.__base__.__subclasses__()",
            "open('/etc/passwd')",
            "__import__('os')",
        ],
    )
    def test_dangerous_code_blocked(self, code):
        # The tools package is reloaded in parts of the full suite to restore
        # registry decorators, so catch the stable public base rather than a
        # pre-reload UnsafeCodeError class object.
        with pytest.raises((ValueError, SyntaxError)):
            _validate_ast(code)

    @pytest.mark.parametrize(
        "code",
        [
            "print(sum(range(10)))",
            "import math\nprint(math.sqrt(2))",
            "import json\nprint(json.dumps({'a': 1}))",
            "xs = [i * 2 for i in range(5)]\nprint(xs)",
        ],
    )
    def test_safe_code_allowed(self, code):
        _validate_ast(code)  # must not raise

    def test_limit_failure_does_not_skip_later_hardening(self, monkeypatch):
        import sys
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from openjarvis.tools.code_interpreter import _child_limits

        fake_resource = SimpleNamespace(RLIMIT_CPU=1, RLIMIT_AS=2, RLIMIT_FSIZE=3)
        fake_resource.setrlimit = MagicMock(
            side_effect=[None, ValueError("unsupported"), None]
        )
        monkeypatch.setitem(sys.modules, "resource", fake_resource)
        setsid = MagicMock()
        monkeypatch.setattr("openjarvis.tools.code_interpreter.os.setsid", setsid)

        _child_limits()

        setsid.assert_called_once_with()
        assert [call.args[0] for call in fake_resource.setrlimit.call_args_list] == [
            fake_resource.RLIMIT_CPU,
            fake_resource.RLIMIT_AS,
            fake_resource.RLIMIT_FSIZE,
        ]
