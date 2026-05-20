"""Tests for UserProfile dataclass + USER.md I/O."""

from __future__ import annotations

from openjarvis.personalization.profile import UserProfile


def test_add_routes_by_key_prefix() -> None:
    p = UserProfile()
    p.add("user.name", "Mac")
    p.add("pref.coffee", "黑咖啡")
    p.add("fact.work", "賈維斯維護者")
    p.add("relation.wife_birthday", "1990-08-12")
    p.add("random.unknown", "fallback")

    assert p.section("Identity").entries[0].key == "user.name"
    assert p.section("Preferences").entries[0].key == "pref.coffee"
    assert p.section("Facts").entries[0].key == "fact.work"
    assert p.section("Relations").entries[0].key == "relation.wife_birthday"
    # unknown prefix lands in Notes
    assert p.section("Notes").entries[0].key == "random.unknown"


def test_render_round_trip() -> None:
    p = UserProfile()
    p.add("user.name", "Mac")
    p.add("pref.language", "台灣繁體中文")
    raw = p.render()
    assert "# USER PROFILE" in raw
    assert "## Identity" in raw
    assert "- user.name: Mac" in raw

    parsed = UserProfile.parse(raw)
    assert parsed.get("user.name") == "Mac"
    assert parsed.get("pref.language") == "台灣繁體中文"


def test_save_load_round_trip(tmp_path) -> None:
    path = tmp_path / "USER.md"
    p = UserProfile()
    p.add("user.locale", "zh-TW")
    p.save(path)
    assert path.exists()

    loaded = UserProfile.load(path)
    assert loaded.get("user.locale") == "zh-TW"
    assert loaded.updated_at is not None


def test_load_missing_path_returns_empty_profile(tmp_path) -> None:
    p = UserProfile.load(tmp_path / "missing.md")
    assert p.is_empty()


def test_parser_preserves_unknown_sections() -> None:
    raw = "# USER PROFILE\n\n## Custom\n- note: from user\n"
    p = UserProfile.parse(raw)
    assert "Custom" in p.sections
    assert p.section("Custom").entries[0].value == "from user"


def test_render_skips_empty_sections() -> None:
    p = UserProfile()
    p.section("Identity")  # empty section created
    p.add("pref.x", "y")
    rendered = p.render()
    assert "## Identity" not in rendered
    assert "## Preferences" in rendered
