"""Stable releases must stay private until every updater artifact is checked."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_stable_publication_waits_for_every_build_and_manifest():
    jobs = yaml.safe_load((ROOT / ".github/workflows/desktop.yml").read_text())["jobs"]
    build = jobs["build-and-release"]
    platforms = {item["platform"] for item in build["strategy"]["matrix"]["include"]}
    assert platforms == {"ubuntu-22.04", "macos-15", "windows-latest", "windows-11-arm"}
    action = next(step for step in build["steps"] if step.get("id") == "tauri-build")
    stable_only = "startsWith(github.ref, 'refs/tags/desktop-v')"
    assert action["with"]["releaseDraft"] == "${{ " + stable_only + " }}"
    assert jobs["verify-release"]["needs"] == ["build-and-release"]
    publish = jobs["publish-stable-release"]
    assert publish["needs"] == ["verify-release"]
    assert publish["if"] == stable_only
    assert "always()" not in publish["if"]
    assert jobs["refresh-stable-channel"]["needs"] == ["publish-stable-release"]
