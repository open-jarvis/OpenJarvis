"""``jarvis init --preset`` must find presets in installed wheels and checkouts.

The presets are not part of the ``openjarvis`` package in the source tree, so
the wheel bundles a copy at ``openjarvis/presets/``. Before that, an installed
``jarvis init --preset <name>`` always failed with "Preset not found" because
the lookup only knew the source-tree location.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import click
import pytest
from click.testing import CliRunner

from openjarvis.cli import _presets, cli

REPO_ROOT = Path(__file__).resolve().parents[2]


def _redirect(monkeypatch: pytest.MonkeyPatch, packaged: Path, source: Path) -> None:
    monkeypatch.setattr(_presets, "PACKAGED_PRESETS_DIR", packaged)
    monkeypatch.setattr(_presets, "SOURCE_PRESETS_DIR", source)


def _write_preset(directory: Path, name: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.toml"
    path.write_text(body, encoding="utf-8")
    return path


def _preset_choices() -> list[str]:
    init_cmd = cli.commands["init"]
    for param in init_cmd.params:
        if param.name == "preset":
            assert isinstance(param.type, click.Choice)
            return list(param.type.choices)
    raise AssertionError("jarvis init has no --preset option")


def test_packaged_copy_wins_over_source_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    packaged = _write_preset(tmp_path / "pkg", "demo", "# packaged\n")
    _write_preset(tmp_path / "src", "demo", "# source\n")
    _redirect(monkeypatch, packaged.parent, tmp_path / "src")

    assert _presets.resolve_preset("demo") == packaged


def test_falls_back_to_source_tree_without_packaged_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _write_preset(tmp_path / "src", "demo", "# source\n")
    _redirect(monkeypatch, tmp_path / "missing", source.parent)

    assert _presets.resolve_preset("demo") == source


def test_unknown_preset_resolves_to_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _redirect(monkeypatch, tmp_path / "pkg", tmp_path / "src")

    assert _presets.resolve_preset("demo") is None
    assert _presets.available_presets() == []


def test_available_presets_merges_both_locations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_preset(tmp_path / "pkg", "alpha", "")
    _write_preset(tmp_path / "pkg", "shared", "")
    _write_preset(tmp_path / "src", "shared", "")
    _write_preset(tmp_path / "src", "zeta", "")
    _redirect(monkeypatch, tmp_path / "pkg", tmp_path / "src")

    assert _presets.available_presets() == ["alpha", "shared", "zeta"]


@pytest.mark.parametrize("name", _preset_choices())
def test_every_cli_preset_choice_resolves(name: str) -> None:
    """Every name ``--preset`` offers must exist, from a checkout or a wheel."""
    path = _presets.resolve_preset(name)

    assert path is not None, f"--preset {name} has no TOML file"
    assert path.is_file()


def test_init_lists_every_search_path_when_preset_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _redirect(monkeypatch, tmp_path / "pkg", tmp_path / "src")
    config_dir = tmp_path / ".openjarvis"
    with (
        mock.patch("openjarvis.cli.init_cmd.DEFAULT_CONFIG_DIR", config_dir),
        mock.patch(
            "openjarvis.cli.init_cmd.DEFAULT_CONFIG_PATH", config_dir / "config.toml"
        ),
    ):
        result = CliRunner().invoke(cli, ["init", "--preset", "chat-simple"])

    assert result.exit_code == 1
    assert "not found" in result.output
    # Rich wraps long paths at the terminal width; compare without whitespace.
    compact = "".join(result.output.split())
    assert str(tmp_path / "pkg") in compact
    assert str(tmp_path / "src") in compact
    assert not (config_dir / "config.toml").exists()


def test_wheel_bundles_presets_inside_the_package() -> None:
    """Guard the packaging rule that ships the presets with the wheel."""
    pyproject = REPO_ROOT / "pyproject.toml"
    if not pyproject.is_file():
        pytest.skip("source tree not available")
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        import tomli as tomllib  # type: ignore[import-not-found,no-redef]

    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    force_include = data["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]

    assert force_include.get("configs/openjarvis/examples") == "openjarvis/presets"
