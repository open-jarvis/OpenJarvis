"""Exercise quickstart preflight with local command stubs, without installing."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from packaging.markers import default_environment
from packaging.requirements import Requirement

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX quickstart")
_SCRIPT = Path(__file__).parents[2] / "scripts" / "quickstart.sh"


def _executable(path: Path, content: str) -> None:
    path.write_text("#!/bin/sh\n" + content)
    path.chmod(0o755)


@pytest.fixture
def preflight(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "frontend").mkdir()
    (repo / "rust").mkdir()
    (repo / "rust" / "rust-toolchain.toml").write_text(
        '[toolchain]\nchannel = "1.89.0"\n'
    )
    (repo / "frontend" / "package.json").write_text(
        json.dumps({"engines": {"node": ">=22.22"}, "packageManager": "npm@11.19.0"})
    )
    (repo / "frontend" / "package-lock.json").write_text(
        json.dumps(
            {
                "packages": {
                    "node_modules/vitest": {
                        "engines": {"node": "^22.12.0 || ^24.0.0 || >=26.0.0"}
                    }
                }
            }
        )
    )
    script = repo / "scripts" / "quickstart.sh"
    # Stop before service setup: run the real preflight and its EXIT trap.
    script.write_text(_SCRIPT.read_text().split("# ── 4. Check / install Ollama")[0])
    bindir = tmp_path / "bin"
    bindir.mkdir()
    # Preflight uses only the standard library; avoid unrelated site hooks in
    # the developer's test environment on each subprocess invocation.
    _executable(bindir / "python3", f'exec {shlex.quote(sys.executable)} -S "$@"\n')
    _executable(bindir / "uv", "echo 'uv 0.13.0'\n")
    _executable(bindir / "node", 'echo "v$TEST_NODE_VERSION"\n')
    for command in ("rustc", "cargo"):
        _executable(
            bindir / command,
            'if [ "$TEST_RUST_BROKEN" = 1 ]; then exit 1; fi\n'
            f'echo "{command} $TEST_RUST_VERSION"\n',
        )
    _executable(
        bindir / "npm",
        'if [ "$1" = --version ]; then cat "$TEST_NPM_VERSION_FILE"; exit; fi\n'
        'echo "$*" >> "$TEST_COMMAND_LOG"\n'
        'if [ "$TEST_NPM_UPGRADE_FAIL" = 1 ]; then exit 1; fi\n'
        'if [ "$TEST_NPM_NO_UPDATE" != 1 ]; then\n'
        '  echo "${3#npm@}" > "$TEST_NPM_VERSION_FILE"\n'
        "fi\n",
    )
    _executable(
        bindir / "curl",
        "cat <<'INSTALL'\n"
        'echo rustup >> "$TEST_COMMAND_LOG"\n'
        'mkdir -p "$HOME/.cargo/bin"\n'
        "for command in rustc cargo; do\n"
        "  printf '#!/bin/sh\\necho %s 1.89.0\\n' \"$command\" "
        '> "$HOME/.cargo/bin/$command"\n'
        '  chmod +x "$HOME/.cargo/bin/$command"\n'
        "done\n"
        "INSTALL\n",
    )
    home = tmp_path / "home"
    home.mkdir()
    version_file = tmp_path / "npm-version"
    log = tmp_path / "commands"

    def run(node="22.22.0", npm="11.19.0", **settings):
        version_file.write_text(npm)
        env = {
            **os.environ,
            "HOME": str(home),
            "PATH": f"{bindir}:/usr/bin:/bin",
            "TEST_NODE_VERSION": node,
            "TEST_NPM_VERSION_FILE": str(version_file),
            "TEST_COMMAND_LOG": str(log),
            "TEST_RUST_BROKEN": "0",
            "TEST_RUST_VERSION": "1.89.0",
            "TEST_NPM_UPGRADE_FAIL": "0",
            "TEST_NPM_NO_UPDATE": "0",
            **settings,
        }
        result = subprocess.run(
            [shutil.which("bash") or "/bin/bash", str(script)],
            env=env,
            text=True,
            capture_output=True,
            timeout=45,
        )
        return result, log.read_text() if log.exists() else ""

    return run


@pytest.mark.parametrize("node", ["18.20.0", "20.19.0", "22.21.9", "23.10.0", "25.0.0"])
def test_unsupported_node_is_rejected_before_npm_changes(preflight, node):
    result, commands = preflight(node=node, npm="10.0.0")
    assert result.returncode == 1
    assert "Node.js 22.22 or newer" in result.stdout
    assert commands == ""
    assert "unbound variable" not in result.stderr


@pytest.mark.parametrize("node", ["22.22.0", "24.0.0", "26.0.0", "27.0.0"])
def test_node_satisfies_both_frontend_and_locked_toolchain(preflight, node):
    result, commands = preflight(node=node)
    assert result.returncode == 0, result.stderr
    assert commands == ""


@pytest.mark.parametrize("npm", ["11.19.0", "11.19.1", "11.20.0"])
def test_compatible_npm_does_not_trigger_an_install(preflight, npm):
    result, commands = preflight(npm=npm)
    assert result.returncode == 0, result.stderr
    assert commands == ""
    assert "unbound variable" not in result.stderr


@pytest.mark.parametrize("npm", ["10.9.0", "11.18.9", "12.0.0"])
def test_incompatible_npm_is_replaced_by_frontend_pin(preflight, npm):
    result, commands = preflight(npm=npm)
    assert result.returncode == 0, result.stderr
    assert commands == "install -g npm@11.19.0\n"
    assert "npm 11.19.0" in result.stdout


def test_npm_install_that_does_not_update_path_is_not_reported_as_ready(preflight):
    result, _ = preflight(npm="11.12.0", TEST_NPM_NO_UPDATE="1")
    assert result.returncode == 1
    assert "still on PATH" in result.stdout


def test_broken_rustup_shims_trigger_toolchain_install(preflight):
    result, commands = preflight(TEST_RUST_BROKEN="1")
    assert result.returncode == 0, result.stderr
    assert commands == "rustup\n"


def test_working_but_old_rust_is_upgraded_before_native_build(preflight):
    result, commands = preflight(TEST_RUST_VERSION="1.88.0")
    assert result.returncode == 0, result.stderr
    assert commands == "rustup\n"


def test_script_parses_with_bash():
    result = subprocess.run(
        [shutil.which("bash") or "/bin/bash", "-n", str(_SCRIPT)],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


def test_native_build_runs_under_the_pinned_workspace_toolchain(tmp_path):
    (tmp_path / "rust").mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    calls = tmp_path / "uv-calls"
    _executable(bindir / "uv", f'printf "%s\\n" "$PWD" "$*" >> "{calls}"\n')
    block = _SCRIPT.read_text().split("# ── 7b. Build Rust extension")[1]
    block = block.split("# ── 8. Install frontend dependencies")[0]
    # The section heading's remaining decoration belongs to its comment.
    block = block.split("\n", 1)[1]
    result = subprocess.run(
        [
            shutil.which("bash") or "/bin/bash",
            "-c",
            "set -euo pipefail\ninfo() { :; }\nok() { :; }\n" + block,
        ],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{bindir}:/usr/bin:/bin"},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert calls.read_text().splitlines() == [
        str(tmp_path / "rust"),
        "run maturin develop -m crates/openjarvis-python/Cargo.toml --quiet",
    ]


@pytest.mark.parametrize(
    "platform,machine,python_version,capped",
    [
        ("darwin", "x86_64", "3.13", True),
        ("darwin", "arm64", "3.13", False),
        ("linux", "x86_64", "3.13", False),
        ("darwin", "arm64", "3.10", True),
    ],
)
def test_onnxruntime_cap_only_applies_to_platforms_without_new_wheels(
    platform, machine, python_version, capped
):
    project = tomllib.loads((_SCRIPT.parents[1] / "pyproject.toml").read_text())
    environment = {
        **default_environment(),
        "sys_platform": platform,
        "platform_machine": machine,
        "python_version": python_version,
        "python_full_version": python_version + ".0",
    }
    for extra in ("desktop", "speech"):
        requirements = [
            Requirement(value)
            for value in project["project"]["optional-dependencies"][extra]
        ]
        active = [
            requirement
            for requirement in requirements
            if requirement.name == "onnxruntime"
            and (requirement.marker is None or requirement.marker.evaluate(environment))
        ]
        assert bool(active) is capped
        if capped:
            assert all("1.23.2" in requirement.specifier for requirement in active)
            assert all("1.24.2" not in requirement.specifier for requirement in active)
