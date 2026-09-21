"""Safety contract for the POSIX uninstaller."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX shell script")


def _run_uninstaller(
    tmp_path: Path,
    *args: str,
    answer: str = "",
    openjarvis_home: Path | None = None,
    user_home: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    script = Path(__file__).parents[2] / "scripts" / "install" / "jarvis-uninstall.sh"
    fake_home = user_home or tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    data_home = openjarvis_home or fake_home / ".openjarvis"
    env = {
        **os.environ,
        "HOME": str(fake_home),
        "OPENJARVIS_HOME": str(data_home),
        "PATH": "/usr/bin:/bin",
    }
    return subprocess.run(
        ["bash", str(script), *args],
        input=answer,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def _populate_install(tmp_path: Path) -> tuple[Path, Path]:
    fake_home = tmp_path / "home"
    data_home = fake_home / ".openjarvis"
    (data_home / "connectors").mkdir(parents=True)
    (data_home / ".state").mkdir()
    (data_home / ".state" / "install-state.json").write_text(
        '{"copy_scripts": true}\n', encoding="utf-8"
    )
    (data_home / "config.toml").write_text("[engine]\n", encoding="utf-8")
    (data_home / "MEMORY.md").write_text("remember this", encoding="utf-8")
    (data_home / "connectors" / "oauth.json").write_text("{}", encoding="utf-8")
    shim_dir = fake_home / ".local" / "bin"
    shim_dir.mkdir(parents=True)
    shim = shim_dir / "jarvis"
    shim.write_text("shim", encoding="utf-8")
    return data_home, shim


def test_declining_confirmation_preserves_data_and_shims(tmp_path: Path) -> None:
    data_home, shim = _populate_install(tmp_path)

    result = _run_uninstaller(tmp_path, answer="no\n")

    assert result.returncode == 0
    assert 'Type "yes"' in result.stdout
    assert "was not removed" in result.stdout
    assert (data_home / "MEMORY.md").read_text(encoding="utf-8") == "remember this"
    assert shim.exists()


@pytest.mark.parametrize("args,answer", [((), "yes\n"), (("--yes",), "")])
def test_explicit_confirmation_removes_data_and_shims(
    tmp_path: Path,
    args: tuple[str, ...],
    answer: str,
) -> None:
    data_home, shim = _populate_install(tmp_path)

    result = _run_uninstaller(tmp_path, *args, answer=answer)

    assert result.returncode == 0
    assert not data_home.exists()
    assert not shim.exists()


def test_unsafe_install_root_is_rejected(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    result = _run_uninstaller(
        tmp_path,
        "--yes",
        openjarvis_home=fake_home,
    )

    assert result.returncode == 2
    assert "Refusing unsafe OPENJARVIS_HOME" in result.stderr
    assert fake_home.exists()


def test_home_ancestor_is_rejected_without_deleting_siblings(tmp_path: Path) -> None:
    users_root = tmp_path / "users"
    fake_home = users_root / "alice"
    sibling_data = users_root / "bob" / "keep.txt"
    sibling_data.parent.mkdir(parents=True)
    sibling_data.write_text("keep", encoding="utf-8")
    (users_root / ".state").mkdir()
    (users_root / ".state" / "install-state.json").write_text(
        '{"copy_scripts": true}\n', encoding="utf-8"
    )

    result = _run_uninstaller(
        tmp_path,
        "--yes",
        openjarvis_home=users_root,
        user_home=fake_home,
    )

    assert result.returncode == 2
    assert "Refusing unsafe OPENJARVIS_HOME" in result.stderr
    assert sibling_data.read_text(encoding="utf-8") == "keep"
    assert fake_home.exists()


def test_unowned_custom_root_is_rejected_with_yes(tmp_path: Path) -> None:
    unrelated = tmp_path / "unrelated-project"
    unrelated.mkdir()
    sentinel = unrelated / "user-data.txt"
    sentinel.write_text("keep", encoding="utf-8")

    result = _run_uninstaller(
        tmp_path,
        "--yes",
        openjarvis_home=unrelated,
    )

    assert result.returncode == 2
    assert "Refusing unsafe OPENJARVIS_HOME" in result.stderr
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_owned_custom_root_can_be_removed_with_yes(tmp_path: Path) -> None:
    custom_root = tmp_path / "apps" / "openjarvis-data"
    (custom_root / ".state").mkdir(parents=True)
    (custom_root / ".state" / "install-state.json").write_text(
        '{"clone_repo": true}\n', encoding="utf-8"
    )
    (custom_root / "MEMORY.md").write_text("owned data", encoding="utf-8")

    result = _run_uninstaller(
        tmp_path,
        "--yes",
        openjarvis_home=custom_root,
    )

    assert result.returncode == 0
    assert not custom_root.exists()
    assert (tmp_path / "home").exists()


def test_fake_or_symlinked_ownership_marker_is_rejected(tmp_path: Path) -> None:
    custom_root = tmp_path / "custom-root"
    marker_dir = custom_root / ".state"
    marker_dir.mkdir(parents=True)
    external_marker = tmp_path / "external-state.json"
    external_marker.write_text('{"copy_scripts": true}\n', encoding="utf-8")
    (marker_dir / "install-state.json").symlink_to(external_marker)
    sentinel = custom_root / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")

    result = _run_uninstaller(
        tmp_path,
        "--yes",
        openjarvis_home=custom_root,
    )

    assert result.returncode == 2
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_help_does_not_touch_existing_install(tmp_path: Path) -> None:
    data_home, shim = _populate_install(tmp_path)

    result = _run_uninstaller(tmp_path, "--help")

    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert data_home.exists()
    assert shim.exists()
