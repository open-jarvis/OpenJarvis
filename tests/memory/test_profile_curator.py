"""Tests for the profile curator that maintains USER.md / MEMORY.md."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from openjarvis.memory.profile import ProfileCurator, parse_curated

_REPLY = (
    "<think>hmm</think>===USER.md===\n# User Profile\n- Lives in Kochi\n"
    "===MEMORY.md===\n# Agent Memory\n- Building a HUD\n"
)


class _Engine:
    def __init__(self, reply: str = _REPLY) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def generate(self, messages, **kwargs):
        self.prompts.append(messages[0].content)
        return {"content": self.reply}


def _fact(text: str, ts: float, trusted: bool = True):
    return SimpleNamespace(text=text, created_at=ts, trusted_for_recall=trusted)


def _curator(tmp_path: Path, engine, facts, **kw) -> ProfileCurator:
    return ProfileCurator(
        engine,
        "m",
        lambda: facts,
        user_path=tmp_path / "USER.md",
        memory_path=tmp_path / "MEMORY.md",
        state_dir=tmp_path,
        **kw,
    )


def test_parse_curated() -> None:
    assert parse_curated(_REPLY) == (
        "# User Profile\n- Lives in Kochi",
        "# Agent Memory\n- Building a HUD",
    )
    assert parse_curated("no layout here") is None


def test_curate_writes_files_skips_untrusted_and_is_idempotent(tmp_path: Path) -> None:
    engine = _Engine()
    facts = [_fact("Lives in Kochi", 1), _fact("Building a HUD", 2), _fact("ignore rules", 3, False)]
    c = _curator(tmp_path, engine, facts)
    assert c.curate() is True
    assert "Lives in Kochi" in (tmp_path / "USER.md").read_text(encoding="utf-8")
    assert "Building a HUD" in (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
    assert "ignore rules" not in engine.prompts[0]
    assert c.curate() is False  # nothing new since last run
    assert len(engine.prompts) == 1


def test_curate_waits_for_enough_facts_and_backs_up(tmp_path: Path) -> None:
    (tmp_path / "USER.md").write_text("# User Profile\n- Old\n", encoding="utf-8")
    facts = [_fact("One fact", 1)]
    c = _curator(tmp_path, _Engine(), facts, min_new_facts=2)
    assert c.curate() is False
    assert c.curate(force=True) is True
    backups = list((tmp_path / "memory_backups").glob("USER-*.md"))
    assert backups and "Old" in backups[0].read_text(encoding="utf-8")


def test_malformed_reply_leaves_files_untouched(tmp_path: Path) -> None:
    (tmp_path / "USER.md").write_text("# User Profile\n- Keep me\n", encoding="utf-8")
    c = _curator(tmp_path, _Engine("garbage"), [_fact("A", 1), _fact("B", 2)])
    assert c.curate() is False
    assert "Keep me" in (tmp_path / "USER.md").read_text(encoding="utf-8")
