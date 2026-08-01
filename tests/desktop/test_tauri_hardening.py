"""Static regression tests for the bounded Phase 6 desktop surface."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_tauri_capabilities_do_not_expose_shell_or_broad_process() -> None:
    capability = json.loads(
        (ROOT / "frontend/src-tauri/capabilities/default.json").read_text(
            encoding="utf-8"
        )
    )
    permissions = capability["permissions"]
    assert "process:default" not in permissions
    assert not any(
        isinstance(item, str) and item.startswith("shell:") for item in permissions
    )
    assert "process:allow-restart" in permissions


def test_arbitrary_jarvis_command_is_not_registered() -> None:
    source = (ROOT / "frontend/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    handler = source.split("tauri::generate_handler![", 1)[1].split("]", 1)[0]
    assert "run_jarvis_command" not in handler
    assert ".plugin(tauri_plugin_shell::init())" not in source


def test_desktop_close_dialog_offers_explicit_task_choices() -> None:
    source = (
        ROOT / "frontend/src/components/Desktop/DesktopCloseGuard.tsx"
    ).read_text(encoding="utf-8")
    for label in (
        "Continue in background",
        "Pause active task, then hide",
        "Cancel active task, then hide",
        "Keep window open",
    ):
        assert label in source
    assert 'role="dialog"' in source
    assert 'aria-modal="true"' in source


def test_final_attach_branch_returns_before_every_legacy_bootstrap() -> None:
    source = (ROOT / "frontend/src-tauri/src/lib.rs").read_text(encoding="utf-8")
    start = source.index("async fn boot_backend")
    end = source.index("\nfn api_base", start)
    boot = source[start:end]
    legacy_start = boot.index("let cfg = read_inference_config();")
    attach = boot[:legacy_start]

    assert "if final_attach_only()" in attach
    assert "attach_final_backend(status.clone()).await" in attach
    assert "return;" in attach
    for forbidden in (
        'resolve_bin("uv")',
        "launch_ollama",
        "ollama_has_model",
        "uv sync",
    ):
        assert forbidden not in attach
    assert "OpenJarvis Codex Runtime ist nicht erreichbar." in source


def test_final_attach_forces_the_owned_loopback_api_base() -> None:
    source = (ROOT / "frontend/src/lib/api.ts").read_text(encoding="utf-8")
    start = source.index("export const getBase")
    end = source.index("\n};", start)
    get_base = source[start:end]

    assert "isTauri() && _tauriFinalAttachOnly" in get_base
    assert get_base.index("_tauriFinalAttachOnly") < get_base.index("getSettingsApiUrl")
    assert "http://127.0.0.1:8000" in source


def test_final_launcher_passes_attach_only_and_tracks_only_managed_pids() -> None:
    source = (ROOT / "scripts/windows/openjarvis-final.ps1").read_text(
        encoding="utf-8"
    )

    attach = source.index("$env:OPENJARVIS_FINAL_ATTACH_ONLY = '1'")
    desktop_start = source.index("$ui = Start-Process -FilePath $desktop", attach)
    restore = source.index(
        "$env:OPENJARVIS_FINAL_ATTACH_ONLY = $priorAttach", desktop_start
    )
    assert attach < desktop_start < restore
    assert "$uiPid = $ui.Id" in source
    assert "ui_pid = $uiPid" in source
    assert "ui_executable = $uiExecutable" in source
    assert "ui_started_at_utc = $uiStartedAtUtc" in source
    assert "Get-OwnedUi" in source
    assert "status = if ($owned -and $uiOwned)" in source
    assert "-RedirectStandardOutput $ServerOutputPath" in source
    assert "-RedirectStandardError $ServerErrorPath" in source
    assert "([int]$state.ui_pid)" in source
    assert "([string]$state.ui_started_at_utc)" in source
    assert "([string]$state.ui_executable)" in source
    assert "'Restart' { Stop-FinalRuntime; Start-FinalRuntime }" in source
    assert "Stop-Process -Name" not in source
    assert "taskkill" not in source.lower()


def test_final_launcher_defaults_to_the_repository_release_desktop() -> None:
    source = (ROOT / "scripts/windows/openjarvis-final.ps1").read_text(
        encoding="utf-8"
    )

    assert "if ([string]::IsNullOrWhiteSpace($DesktopExecutable))" in source
    assert (
        "$DesktopExecutable = Join-Path $RepoRoot "
        "'frontend\\src-tauri\\target\\release\\openjarvis-desktop.exe'"
    ) in source
    assert 'throw "Desktop UI exited early with code $($ui.ExitCode)."' in source


def test_tauri_final_attach_does_not_reuse_pwa_service_worker_cache() -> None:
    vite = (ROOT / "frontend/vite.config.ts").read_text(encoding="utf-8")
    package = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    native = (ROOT / "frontend/src-tauri/src/lib.rs").read_text(encoding="utf-8")

    assert "disable: mode === 'tauri'" in vite
    assert "vite build --mode tauri --outDir dist" in package["scripts"]["build:tauri"]
    assert "FINAL_ATTACH_SERVICE_WORKER_RECOVERY" in native
    assert "navigator.serviceWorker.getRegistrations()" in native
    assert "registration.unregister()" in native
    assert "window.location.reload()" in native
    assert "caches.delete" not in native
