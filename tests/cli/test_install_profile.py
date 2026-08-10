"""Tests for editable-install profile persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openjarvis.cli._install_profile import (
    PROFILE_FILENAME,
    InstallProfile,
    load_install_profile,
    main,
    profile_sync_args,
    write_install_profile,
)


def test_profile_round_trips_sorted_unique_options(tmp_path: Path) -> None:
    path = write_install_profile(
        tmp_path,
        extras=["tools-search", "desktop", "desktop"],
        groups=["desktop-native"],
    )

    profile, warning = load_install_profile(tmp_path)

    assert path == tmp_path / PROFILE_FILENAME
    assert warning is None
    assert profile == InstallProfile(
        version=1,
        extras=("desktop", "tools-search"),
        groups=("desktop-native",),
    )
    assert profile_sync_args(profile) == (
        "--extra",
        "desktop",
        "--extra",
        "tools-search",
        "--group",
        "desktop-native",
    )


@pytest.mark.parametrize("name", ["--all-extras", "bad name", "", "../dev"])
def test_profile_rejects_option_injection(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError, match="invalid install profile option"):
        write_install_profile(tmp_path, extras=[name], groups=[])


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"version": 2, "extras": [], "groups": []}, "unsupported"),
        ({"version": 1, "extras": "desktop", "groups": []}, "invalid"),
        ({"version": 1, "extras": ["--all-extras"], "groups": []}, "invalid"),
    ],
)
def test_invalid_profile_returns_warning(
    tmp_path: Path,
    payload: dict[str, object],
    message: str,
) -> None:
    (tmp_path / PROFILE_FILENAME).write_text(json.dumps(payload), encoding="utf-8")

    profile, warning = load_install_profile(tmp_path)

    assert profile is None
    assert message in (warning or "").lower()


def test_malformed_profile_returns_warning(tmp_path: Path) -> None:
    (tmp_path / PROFILE_FILENAME).write_text("{", encoding="utf-8")

    profile, warning = load_install_profile(tmp_path)

    assert profile is None
    assert "invalid" in (warning or "").lower()


def test_non_utf8_profile_returns_warning(tmp_path: Path) -> None:
    (tmp_path / PROFILE_FILENAME).write_bytes(b"\xff")

    profile, warning = load_install_profile(tmp_path)

    assert profile is None
    assert "invalid" in (warning or "").lower()


def test_missing_profile_is_not_an_error(tmp_path: Path) -> None:
    assert load_install_profile(tmp_path) == (None, None)


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (
            ["--extra", "desktop", "--group", "desktop-native"],
            {
                "version": 1,
                "extras": ["desktop"],
                "groups": ["desktop-native"],
            },
        ),
        (
            [
                "--extra",
                "desktop",
                "--extra",
                "tools-search",
                "--group",
                "desktop-native",
            ],
            {
                "version": 1,
                "extras": ["desktop", "tools-search"],
                "groups": ["desktop-native"],
            },
        ),
    ],
)
def test_record_cli_writes_official_installer_profiles(
    tmp_path: Path,
    args: list[str],
    expected: dict[str, object],
) -> None:
    exit_code = main(["record", "--repo-root", str(tmp_path), *args])

    assert exit_code == 0
    assert (
        json.loads((tmp_path / PROFILE_FILENAME).read_text(encoding="utf-8"))
        == expected
    )
