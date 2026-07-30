"""Fully local Phase-5 filesystem/Git, browser, and desktop smoke tests."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from openjarvis.browser import (
    BrowserArtifactStore,
    BrowserNetworkPolicy,
    BrowserOpenError,
    BrowserProcessManager,
    BrowserProfilePolicy,
    BrowserRecoveryController,
    BrowserToolAdapter,
    BrowserTransferPolicy,
    CdpBrowserAdapter,
)
from openjarvis.desktop import Win32SemanticBackend, WindowsDesktopSession
from openjarvis.tools.git_secure import SecureGitService
from openjarvis.tools.safe_filesystem import SafeFileWriteTool, SecurePathPolicy
from openjarvis.tools.safe_shell import SafeShellTool, StructuredCommandPolicy

ROOT = Path(__file__).resolve().parents[1]


def _git(cwd: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=True,
        shell=False,
    )
    return result.stdout.strip()


def filesystem_git_smoke(root: Path) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    integration = root / "integration"
    integration.mkdir()
    _git(integration, "init", "-b", "feature/integration")
    _git(integration, "config", "user.name", "OpenJarvis Phase 5 Smoke")
    _git(integration, "config", "user.email", "phase5@example.invalid")
    (integration / "value.txt").write_text("baseline\n", encoding="utf-8")
    _git(integration, "add", "value.txt")
    _git(integration, "commit", "-m", "baseline")
    _git(
        integration,
        "remote",
        "add",
        "upstream",
        "https://example.invalid/openjarvis.git",
    )
    _git(integration, "remote", "set-url", "--push", "upstream", "DISABLED")

    service = SecureGitService(
        integration_repo=integration,
        worktree_root=root / "worktrees",
        artifact_root=root / "git-artifacts",
    )
    remote = service.verify_remote_safety()
    created = service.create_worktree(
        destination=service.worktree_root / "phase5-smoke",
        branch="task/phase5-smoke",
    )
    worktree = Path(created["worktree"])
    filesystem = SecurePathPolicy((worktree,), root / "filesystem-restore")
    write = SafeFileWriteTool(filesystem).execute(
        path=str(worktree / "value.txt"),
        content="phase5 verified\n",
    )
    if not write.success or "phase5 verified" not in service.diff(worktree):
        raise RuntimeError("filesystem write or Git diff verification failed")

    shell = SafeShellTool(
        StructuredCommandPolicy(
            allowed_executables=(sys.executable,),
            path_policy=filesystem,
        )
    )
    test = shell.execute(
        executable=sys.executable,
        arguments=[
            "-c",
            (
                "from pathlib import Path;"
                "assert Path('value.txt').read_text(encoding='utf-8')"
                " == 'phase5 verified\\n'"
            ),
        ],
        working_dir=str(worktree),
        timeout=10,
        environment=[],
        expected_exit_codes=[0],
    )
    if not test.success:
        raise RuntimeError(f"isolated test failed: {test.content}")
    committed = service.commit(
        worktree=worktree,
        files=["value.txt"],
        message="test: Phase 5 local smoke",
    )
    second = SafeFileWriteTool(filesystem).execute(
        path=str(worktree / "value.txt"),
        content="uncommitted change\n",
    )
    if not second.success:
        raise RuntimeError("restore preparation write failed")
    restored = service.restore(
        worktree=worktree,
        files=["value.txt"],
        artifact_name="phase5-smoke-before-restore",
    )
    if (worktree / "value.txt").read_text(encoding="utf-8") != "phase5 verified\n":
        raise RuntimeError("Git restore state mismatch")
    bundle = service.create_bundle(
        ref="task/phase5-smoke",
        artifact_name="phase5-smoke",
    )
    verified_bundle = service.verify_bundle(bundle["bundle"])
    removed = service.remove_worktree(worktree)
    return {
        "status": "passed",
        "upstream_push": remote["upstream_push"],
        "write_before_sha256": write.metadata["before_sha256"],
        "write_after_sha256": write.metadata["after_sha256"],
        "test_exit_code": test.metadata["returncode"],
        "commit": committed["new_head"],
        "restore_sha256": restored["sha256"],
        "bundle_sha256": bundle["sha256"],
        "bundle_heads": verified_bundle["heads"],
        "worktree_removed": removed["removed"] == "true",
        "push_attempted": False,
    }


_PAGE = b"""<!doctype html>
<html><head><title>OpenJarvis Phase 5 Local</title></head>
<body style='min-height:1600px'>
<h1>Local synthetic form</h1>
<form id='form'>
  <input id='name' name='name'>
  <select id='role'>
    <option value='reader'>Reader</option>
    <option value='tester'>Tester</option>
  </select>
  <input id='upload' type='file'>
  <button id='prepare' type='button'>Prepare</button>
  <button id='submit' type='submit'>Submit</button>
</form>
<a id='download' href='/download' download='fake-report.txt'>Download</a>
<div id='review'>Ready</div><div id='result'>Not submitted</div>
<script>
document.querySelector('#prepare').onclick=()=>{
  document.querySelector('#review').textContent='Prepared for review'
};
document.querySelector('#form').onsubmit=(event)=>{
  event.preventDefault();
  document.querySelector('#result').textContent='Submitted locally'
};
</script></body></html>"""


class _LocalHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/download":
            body = b"synthetic download\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header(
                "Content-Disposition",
                'attachment; filename="fake-report.txt"',
            )
        else:
            body = _PAGE
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *args: object) -> None:
        del args


class _InterruptedHealthManager:
    def __init__(self, manager: BrowserProcessManager) -> None:
        self.manager = manager
        self.calls = 0

    def health(self, session):
        observed = self.manager.health(session)
        self.calls += 1
        if self.calls == 1:
            return replace(
                observed,
                connection_ok=False,
                cause="synthetic_control_interruption",
            )
        return observed

    def restart_control_service(self, session):
        return self.manager.restart_control_service(session)


def _edge_executable() -> Path:
    candidates = (
        Path(os.environ.get("PROGRAMFILES(X86)", ""))
        / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", ""))
        / "Microsoft/Edge/Application/msedge.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    located = shutil.which("msedge.exe") or shutil.which("chrome.exe")
    if located:
        return Path(located)
    raise BrowserOpenError("no Chromium browser was found for the local smoke")


def browser_smoke(root: Path) -> dict[str, object]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _LocalHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    manager = BrowserProcessManager(
        executable=_edge_executable(),
        profile_policy=BrowserProfilePolicy(root / "browser-profiles"),
        visible=False,
    )
    session = manager.create_session()
    control = CdpBrowserAdapter()
    events: list[tuple[str, dict]] = []
    try:
        manager.start(session, timeout=30)
        if not control.connect(session):
            raise BrowserOpenError("CDP connection failed")
        upload_root = root / "uploads"
        upload_root.mkdir()
        restore_root = root / "upload-restore"
        upload = upload_root / "fake-upload.txt"
        upload.write_text("synthetic upload\n", encoding="utf-8")
        adapter = BrowserToolAdapter(
            session=session,
            control=control,
            network_policy=BrowserNetworkPolicy(frozenset({port})),
            transfer_policy=BrowserTransferPolicy(
                download_root=root / "downloads",
                upload_policy=SecurePathPolicy((upload_root,), restore_root),
            ),
            artifact_store=BrowserArtifactStore(root / "browser-artifacts"),
        )
        url = f"http://127.0.0.1:{port}/"
        navigation = adapter.navigate(
            url,
            expected_title="OpenJarvis Phase 5 Local",
        )
        filled = adapter.fill("#name", "Fake Browser User")
        selected = control.select("#role", "tester")
        if control.value("#role") != "tester":
            raise RuntimeError("select verification failed")
        control.scroll(400)
        prepared = adapter.click("#prepare", expected_text="Prepared for review")
        upload_result = adapter.prepare_upload("#upload", upload)
        download_setup = adapter.prepare_downloads()
        control.click("#download")
        downloaded = Path(download_setup["download_root"]) / "fake-report.txt"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not downloaded.exists():
            time.sleep(0.05)
        download = adapter.transfers.verify_download(downloaded)
        screenshot = adapter.screenshot()
        blocked_before_approval = False
        try:
            adapter.click("#submit", expected_text="Submitted locally")
        except PermissionError:
            blocked_before_approval = True
        if not blocked_before_approval:
            raise RuntimeError("submit was not blocked before allow-once")
        submitted = adapter.click(
            "#submit",
            expected_text="Submitted locally",
            approved_submit=True,
        )

        # Simulate a broken control connection without touching another process.
        control.close()
        interrupted = _InterruptedHealthManager(manager)
        recovery = BrowserRecoveryController(
            interrupted,
            control,
            event_sink=lambda name, payload: events.append((name, payload)),
        ).recover(session)
        if recovery.attempt != 1 or recovery.result != "reconnected":
            raise RuntimeError("bounded browser recovery did not reconnect once")
        return {
            "status": "passed",
            "profile_is_temporary": str(session.profile_path).startswith(str(root)),
            "browser_pid": session.browser_pid,
            "control_port": session.control_port,
            "navigation_verified": navigation.verified,
            "input_verified": filled.verified,
            "select_ready_state": selected.ready_state,
            "click_verified": prepared.verified,
            "upload_prepared_not_submitted": bool(
                upload_result["prepared"] and not upload_result["submitted"]
            ),
            "download_sha256": download.sha256,
            "screenshot_sha256": screenshot.artifact.sha256
            if screenshot.artifact
            else None,
            "submit_blocked_before_allow_once": blocked_before_approval,
            "local_submit_verified": submitted.verified,
            "recovery": asdict(recovery),
            "recovery_event_types": [name for name, _payload in events],
            "external_network_used": False,
        }
    finally:
        control.close()
        manager.close(session)
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def desktop_smoke(root: Path) -> dict[str, object]:
    if os.name != "nt":
        return {"status": "skipped", "reason": "Windows only"}
    fixture = ROOT / "tests" / "fixtures" / "phase5_desktop_app.py"
    events: list[tuple[str, dict]] = []
    session = WindowsDesktopSession(
        backend=Win32SemanticBackend(),
        artifact_root=root / "desktop-artifacts",
        event_sink=lambda name, payload: events.append((name, payload)),
    )
    try:
        window = session.start_test_application(
            executable=getattr(sys, "_base_executable", sys.executable),
            script=fixture,
            expected_title="OpenJarvis Phase 5 Synthetic Desktop",
            allowed_root=fixture.parent,
        )
        edit = session.element(automation_id=1001, role="edit")
        button = session.element(automation_id=1002, role="button")
        observed = session.set_text(edit, "Fake Desktop User")
        session.click(
            button,
            verifier=lambda: session.element(
                automation_id=1003,
                role="static",
            ).name
            == "Verified: clicked",
        )
        artifact = session.screenshot()
        return {
            "status": "passed",
            "owned_process": session.backend.is_owned_process(
                window.process_id,
                session.process.pid,
            ),
            "semantic_text_verified": observed == "Fake Desktop User",
            "semantic_click_verified": True,
            "screenshot_sha256": artifact.sha256,
            "screenshot_window_handle": artifact.window_handle,
            "event_types": [name for name, _payload in events],
        }
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "suite",
        choices=("all", "filesystem-git", "browser", "desktop"),
        default="all",
        nargs="?",
    )
    args = parser.parse_args()
    selected = (
        ("filesystem-git", "browser", "desktop")
        if args.suite == "all"
        else (args.suite,)
    )
    results: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="openjarvis-phase5-smoke-") as raw:
        root = Path(raw).resolve(strict=True)
        if "filesystem-git" in selected:
            results["filesystem_git"] = filesystem_git_smoke(root / "filesystem-git")
        if "browser" in selected:
            browser_root = root / "browser"
            browser_root.mkdir()
            results["browser"] = browser_smoke(browser_root)
        if "desktop" in selected:
            desktop_root = root / "desktop"
            desktop_root.mkdir()
            results["desktop"] = desktop_smoke(desktop_root)
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
