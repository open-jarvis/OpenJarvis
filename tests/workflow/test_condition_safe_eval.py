"""Workflow condition evaluation uses the allowlist AST interpreter, not eval()."""

from __future__ import annotations

import pytest

from openjarvis.tools.templates.loader import safe_eval_expr


class TestWorkflowSafeEval:
    def test_subclasses_escape_rejected(self):
        with pytest.raises(Exception):
            safe_eval_expr("().__class__.__base__.__subclasses__()", {"outputs": {}})

    def test_ordinary_condition_works(self):
        assert safe_eval_expr("'a' in outputs", {"outputs": {"a": "x"}}) is True
        assert safe_eval_expr("'b' in outputs", {"outputs": {"a": "x"}}) is False
