"""Stable releases must stay private until every updater artifact is checked."""

import json
import os
import subprocess
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


def test_download_aliases_copy_the_verified_versioned_files(tmp_path):
    jobs = yaml.safe_load((ROOT / ".github/workflows/desktop.yml").read_text())["jobs"]
    script = next(
        step["run"]
        for step in jobs["publish-stable-release"]["steps"]
        if step["name"] == "Add stable download aliases"
    )
    gh = tmp_path / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "if args[:2] == ['release', 'download']:\n"
        "    source = args[args.index('--pattern') + 1]\n"
        "    folder = Path(args[args.index('--dir') + 1])\n"
        "    (folder / source).write_text(source)\n"
        "elif args[:2] == ['release', 'upload']:\n"
        "    artifact = Path(args[3])\n"
        "    with open(os.environ['UPLOAD_LOG'], 'a') as log:\n"
        "        log.write(json.dumps([artifact.name, artifact.read_text()]) + '\\n')\n"
        "else:\n"
        "    sys.exit(2)\n"
    )
    gh.chmod(0o755)
    log = tmp_path / "uploads.jsonl"
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", script],
        env={
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            "STABLE_TAG": "desktop-v1.0.5",
            "GITHUB_REPOSITORY": "open-jarvis/OpenJarvis",
            "RUNNER_TEMP": str(tmp_path / "runner temp"),
            "UPLOAD_LOG": str(log),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    uploads = dict(json.loads(line) for line in log.read_text().splitlines())
    assert uploads == {
        "OpenJarvis_universal.dmg": "OpenJarvis_1.0.5_universal.dmg",
        "OpenJarvis_x64-setup.exe": "OpenJarvis_1.0.5_x64-setup.exe",
        "OpenJarvis_arm64-setup.exe": "OpenJarvis_1.0.5_arm64-setup.exe",
        "OpenJarvis_amd64.deb": "OpenJarvis_1.0.5_amd64.deb",
        "OpenJarvis_x86_64.rpm": "OpenJarvis-1.0.5-1.x86_64.rpm",
        "OpenJarvis_amd64.AppImage": "OpenJarvis_1.0.5_amd64.AppImage",
    }
