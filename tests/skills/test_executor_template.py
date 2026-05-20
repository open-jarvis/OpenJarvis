"""Regression tests for SkillExecutor._render_template.

Templates wrap string placeholders in quotes; we must escape quotes/newlines
inside the rendered value so the resulting string is still valid JSON.
"""

from __future__ import annotations

import json

from openjarvis.skills.executor import SkillExecutor


def test_render_template_escapes_double_quotes_in_value() -> None:
    tpl = '{"query": "{query}"}'
    out = SkillExecutor._render_template(tpl, {"query": 'He said "hi"'})
    parsed = json.loads(out)
    assert parsed == {"query": 'He said "hi"'}


def test_render_template_escapes_newlines_in_value() -> None:
    tpl = '{"text": "{text}"}'
    out = SkillExecutor._render_template(tpl, {"text": "line1\nline2"})
    parsed = json.loads(out)
    assert parsed == {"text": "line1\nline2"}


def test_render_template_emits_numbers_without_quotes() -> None:
    tpl = '{"count": {n}}'
    out = SkillExecutor._render_template(tpl, {"n": 42})
    parsed = json.loads(out)
    assert parsed == {"count": 42}


def test_render_template_lists_dump_to_array() -> None:
    tpl = '{"items": {xs}}'
    out = SkillExecutor._render_template(tpl, {"xs": ["a", "b"]})
    parsed = json.loads(out)
    assert parsed == {"items": ["a", "b"]}


def test_render_template_missing_key_leaves_placeholder() -> None:
    tpl = '{"q": "{missing}"}'
    out = SkillExecutor._render_template(tpl, {})
    # Missing keys keep the original placeholder so callers can detect them.
    assert "{missing}" in out
