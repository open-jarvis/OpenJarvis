from __future__ import annotations

from pathlib import Path


def test_windows_native_build_entry_point_is_process_local() -> None:
    repository = Path(__file__).resolve().parents[2]
    script = repository / "scripts" / "windows" / "build-native.ps1"
    content = script.read_text(encoding="utf-8")

    assert "vswhere.exe" in content
    assert "VsDevCmd.bat" in content
    assert "cl.exe" in content
    assert "link.exe" in content
    assert '$env:AWS_LC_SYS_PREBUILT_NASM = "1"' in content
    assert '$env:AWS_LC_SYS_NO_JITTER_ENTROPY = "1"' in content
    assert "run maturin develop --uv --manifest-path" in content
    assert "import openjarvis_rust" in content
    assert "Set-Item -LiteralPath \"Env:$name\"" in content
    assert '$env:Path = "$resolvedUvDirectory;$env:Path"' in content
    assert "-RustBinPath" in content
    assert '$env:Path = "$resolvedRustBinPath;$env:Path"' in content
    assert "-CargoHome" in content
    assert "-RustupHome" in content
    assert "$env:CARGO_HOME = $resolvedCargoHome" in content
    assert "$env:RUSTUP_HOME = $resolvedRustupHome" in content
    assert "setx" not in content.lower()
    assert "runas" not in content.lower()
