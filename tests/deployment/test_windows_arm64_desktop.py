"""Exercise ARM64 sidecar staging and reject incorrectly labelled executables."""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "frontend/src-tauri/scripts"
ARM_TARGET = "aarch64-pc-windows-msvc"


def pe_executable(machine: int) -> bytes:
    header = bytearray(128)
    header[:2] = b"MZ"
    struct.pack_into("<I", header, 0x3C, 64)
    header[64:68] = b"PE\0\0"
    struct.pack_into("<H", header, 68, machine)
    return bytes(header)


@pytest.fixture
def sidecar_download(tmp_path):
    """Use a real ZIP with a stubbed network, preserving extraction behavior."""
    scripts = tmp_path / "src-tauri/scripts"
    scripts.mkdir(parents=True)
    script = scripts / "download-ollama.sh"
    shutil.copy2(SCRIPTS / script.name, script)
    archive = tmp_path / "ollama.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("ollama.exe", pe_executable(0xAA64))
        bundle.writestr("root.dll", b"root runtime")
        bundle.writestr("LICENSE", b"license notice")
        bundle.writestr("lib/ollama/llama-server.exe", pe_executable(0xAA64))
        bundle.writestr("lib/ollama/ggml-cpu.dll", b"CPU runtime")
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    curl = stubs / "curl"
    curl.write_text(
        '#!/bin/bash\nfor arg in "$@"; do\n'
        '  case "$arg" in https:*) printf "%s" "$arg" > "$TEST_URL";; esac\n'
        'done\nwhile [ "$1" != "-o" ]; do shift; done\n'
        'cp "$TEST_ARCHIVE" "$2"\n'
    )
    curl.chmod(0o755)
    uname = stubs / "uname"
    uname.write_text(
        '#!/bin/bash\ncase "$1" in -m) echo x86_64;; -s) echo MINGW64_NT;; esac\n'
    )
    uname.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}",
        "TEST_ARCHIVE": str(archive),
        "TEST_URL": str(tmp_path / "url"),
        "PROCESSOR_ARCHITECTURE": "AMD64",
        "PROCESSOR_ARCHITEW6432": "ARM64",
    }
    return script, archive, env


def download(script, env, *args):
    return subprocess.run(
        ["bash", str(script), *args], env=env, capture_output=True, text=True
    )


@pytest.mark.parametrize("explicit_target", [True, False])
def test_stages_arm64_runtime_even_from_emulated_git_bash(
    sidecar_download, explicit_target
):
    script, _, env = sidecar_download
    result = download(script, env, *([ARM_TARGET] if explicit_target else []))
    assert result.returncode == 0, result.stderr
    assert Path(env["TEST_URL"]).read_text().endswith("/ollama-windows-arm64.zip")
    binaries = script.parent.parent / "binaries"
    runtime = binaries / f"ollama-runtime-{ARM_TARGET}"
    assert (binaries / f"ollama-{ARM_TARGET}.exe").read_bytes() == pe_executable(0xAA64)
    assert (runtime / "root.dll").read_bytes() == b"root runtime"
    assert (runtime / "LICENSE").read_bytes() == b"license notice"
    assert (runtime / "lib/ollama/ggml-cpu.dll").read_bytes() == b"CPU runtime"
    assert not (runtime / "ollama.exe").exists()


def test_rejects_arm64_archive_without_inference_runtime(sidecar_download):
    script, archive, env = sidecar_download
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("ollama.exe", pe_executable(0xAA64))
    result = download(script, env, ARM_TARGET)
    assert result.returncode != 0
    assert "missing its lib/ollama" in result.stdout
    assert not (script.parent.parent / "binaries" / f"ollama-{ARM_TARGET}.exe").exists()


def test_old_binary_only_cache_is_restaged(sidecar_download):
    script, _, env = sidecar_download
    binaries = script.parent.parent / "binaries"
    binaries.mkdir()
    binary = binaries / f"ollama-{ARM_TARGET}.exe"
    binary.write_bytes(b"old incomplete cache")
    result = download(script, env, ARM_TARGET)
    assert result.returncode == 0, result.stderr
    assert binary.read_bytes() == pe_executable(0xAA64)
    assert (
        binaries / f"ollama-runtime-{ARM_TARGET}/lib/ollama/llama-server.exe"
    ).is_file()


def test_explicit_x64_target_wins_over_arm_host(sidecar_download):
    script, _, env = sidecar_download
    result = download(script, env, "x86_64-pc-windows-msvc")
    assert result.returncode == 0, result.stderr
    assert Path(env["TEST_URL"]).read_text().endswith("/ollama-windows-amd64.zip")


@pytest.mark.parametrize(
    ("payload", "valid"),
    [
        (pe_executable(0xAA64), True),
        (pe_executable(0x8664), False),
        (b"not a PE", False),
    ],
)
def test_arm64_check_reads_machine_type(tmp_path, payload, valid):
    executable = tmp_path / "ollama.exe"
    executable.write_bytes(payload)
    result = subprocess.run(
        ["node", str(SCRIPTS / "verify-arm64-pe.mjs"), str(executable)],
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) is valid, result.stderr
