"""Exercise ARM64 sidecar staging and reject incorrectly labelled executables."""

from __future__ import annotations

import hashlib
import os
import re
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


def download(script, env, *args, pin_archive=True):
    """Run the script; by default pin the stubbed archive's digest in place."""
    if pin_archive:
        digest = hashlib.sha256(Path(env["TEST_ARCHIVE"]).read_bytes()).hexdigest()
        text = re.sub(
            r'ASSET_SHA256="[0-9a-f]{64}"',
            f'ASSET_SHA256="{digest}"',
            script.read_text(),
        )
        script.write_text(text)
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


def test_stages_x64_windows_inference_runtime(sidecar_download):
    script, archive, env = sidecar_download
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("ollama.exe", pe_executable(0x8664))
        bundle.writestr("lib/ollama/llama-server.exe", pe_executable(0x8664))
        bundle.writestr("lib/ollama/ggml-cpu.dll", b"x64 runtime")
        bundle.writestr("lib/ollama/cuda_v12/ggml-cuda.dll", b"cuda 12")
        bundle.writestr("lib/ollama/cuda_v13/ggml-cuda.dll", b"cuda 13")

    result = download(script, env, "x86_64-pc-windows-msvc")

    assert result.returncode == 0, result.stderr
    runtime = (
        script.parent.parent
        / "binaries/ollama-runtime-x86_64-pc-windows-msvc/lib/ollama"
    )
    assert (runtime / "llama-server.exe").is_file()
    assert (runtime / "ggml-cpu.dll").read_bytes() == b"x64 runtime"
    # The full runtime exceeds the NSIS and MSI payload limits.
    assert (runtime / "cuda_v12/ggml-cuda.dll").read_bytes() == b"cuda 12"
    assert not (runtime / "cuda_v13").exists()
    reused = download(script, env, "x86_64-pc-windows-msvc")
    assert "Already staged" in reused.stdout


def test_rejects_archive_with_unpinned_checksum(sidecar_download):
    script, _, env = sidecar_download
    result = download(script, env, ARM_TARGET, pin_archive=False)
    assert result.returncode != 0
    assert "Checksum mismatch" in result.stdout
    binaries = script.parent.parent / "binaries"
    assert not (binaries / f"ollama-{ARM_TARGET}.exe").exists()
    assert not (binaries / f"ollama-runtime-{ARM_TARGET}").exists()
    assert (
        Path(env["TEST_URL"])
        .read_text()
        .startswith("https://github.com/ollama/ollama/releases/download/v")
    )


def test_complete_stage_is_reused_without_download(sidecar_download):
    script, _, env = sidecar_download
    assert download(script, env, ARM_TARGET).returncode == 0
    Path(env["TEST_URL"]).unlink()
    result = download(script, env, ARM_TARGET)
    assert result.returncode == 0, result.stderr
    assert "Already staged" in result.stdout
    assert not Path(env["TEST_URL"]).exists()


@pytest.mark.parametrize(
    "damage",
    ["lib/ollama/llama-server.exe", "lib/ollama/ggml-cpu.dll", "root.dll"],
)
def test_incomplete_stage_is_restaged(sidecar_download, damage):
    script, _, env = sidecar_download
    assert download(script, env, ARM_TARGET).returncode == 0
    runtime = script.parent.parent / "binaries" / f"ollama-runtime-{ARM_TARGET}"
    (runtime / damage).unlink()
    result = download(script, env, ARM_TARGET)
    assert result.returncode == 0, result.stderr
    assert "restaging" in result.stdout
    assert (runtime / damage).is_file()


def test_unfinished_publish_is_restaged(sidecar_download):
    """A stage without the manifest written last was never fully published."""
    script, _, env = sidecar_download
    assert download(script, env, ARM_TARGET).returncode == 0
    binaries = script.parent.parent / "binaries"
    (binaries / f"ollama-runtime-{ARM_TARGET}.manifest").unlink()
    result = download(script, env, ARM_TARGET)
    assert result.returncode == 0, result.stderr
    assert "restaging" in result.stdout
    assert (binaries / f"ollama-runtime-{ARM_TARGET}.manifest").is_file()


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
