"""Tests for the LLM-backed fact extractor (openjarvis.memory.extractor)."""

from __future__ import annotations

from openjarvis.memory.extractor import FactExtractor


class FakeEngine:
    """Engine stub returning a canned completion (or raising)."""

    def __init__(self, content="", *, raises=None):
        self._content = content
        self._raises = raises
        self.calls = []

    def generate(self, messages, *, model, temperature=0.7, max_tokens=1024, **kwargs):
        self.calls.append((messages, model, temperature, max_tokens))
        if self._raises is not None:
            raise self._raises
        return {"content": self._content}


def test_parses_json_array():
    engine = FakeEngine('["User likes coffee", "User lives in Berlin"]')
    extractor = FactExtractor(engine, "qwen3:14b")
    facts = extractor.extract("I like coffee and live in Berlin", "Noted.")
    assert facts == ["User likes coffee", "User lives in Berlin"]


def test_parses_json_array_wrapped_in_prose():
    engine = FakeEngine('Sure! Here are the facts:\n["Fact A", "Fact B"]\nDone.')
    extractor = FactExtractor(engine, "m")
    assert extractor.extract("hi", "hello") == ["Fact A", "Fact B"]


def test_empty_array_returns_no_facts():
    engine = FakeEngine("[]")
    extractor = FactExtractor(engine, "m")
    assert extractor.extract("just chatting", "ok") == []


def test_line_fallback_for_bullets():
    engine = FakeEngine("- User is a teacher\n- User has two kids\n")
    extractor = FactExtractor(engine, "m")
    assert extractor.extract("about me", "noted") == [
        "User is a teacher",
        "User has two kids",
    ]


def test_dedupe_within_turn():
    engine = FakeEngine('["likes tea", "Likes Tea", "likes tea"]')
    extractor = FactExtractor(engine, "m")
    assert extractor.extract("x", "y") == ["likes tea"]


def test_cap_facts_per_turn():
    items = [f'"fact {i}"' for i in range(20)]
    engine = FakeEngine("[" + ", ".join(items) + "]")
    extractor = FactExtractor(engine, "m", max_facts_per_turn=3)
    assert len(extractor.extract("x", "y")) == 3


def test_truncates_long_facts():
    long_fact = "z" * 500
    engine = FakeEngine(f'["{long_fact}"]')
    extractor = FactExtractor(engine, "m", max_fact_chars=50)
    facts = extractor.extract("x", "y")
    assert len(facts) == 1
    assert len(facts[0]) == 50


def test_empty_user_text_skips_engine():
    engine = FakeEngine('["should not be called"]')
    extractor = FactExtractor(engine, "m")
    assert extractor.extract("   ", "y") == []
    assert engine.calls == []


def test_broken_pipe_returns_empty():
    engine = FakeEngine(raises=BrokenPipeError("client gone"))
    extractor = FactExtractor(engine, "m")
    # Must not raise — extraction is best-effort.
    assert extractor.extract("hi", "hello") == []


def test_generic_exception_returns_empty():
    engine = FakeEngine(raises=RuntimeError("ollama exploded"))
    extractor = FactExtractor(engine, "m")
    assert extractor.extract("hi", "hello") == []


def test_handles_non_dict_result():
    class StrEngine:
        def generate(self, *a, **k):
            return '["plain string result"]'

    extractor = FactExtractor(StrEngine(), "m")
    assert extractor.extract("x", "y") == ["plain string result"]


def test_filters_non_fact_tokens():
    engine = FakeEngine('["none", "N/A", "Real fact"]')
    extractor = FactExtractor(engine, "m")
    assert extractor.extract("x", "y") == ["Real fact"]
