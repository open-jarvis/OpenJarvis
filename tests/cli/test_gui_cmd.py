"""Launch behavior for the source-checkout graphical command."""

from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from openjarvis.cli import gui_cmd


def test_gui_custom_ports_use_project_root_and_same_origin_proxy(
    tmp_path: Path,
) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    process = mock.Mock(spec=subprocess.Popen)
    process.pid = 4321
    process.poll.return_value = None
    process.wait.return_value = 0

    with (
        mock.patch.object(gui_cmd, "_frontend_dir", return_value=frontend),
        mock.patch.object(gui_cmd, "_check_frontend_port") as check_port,
        mock.patch.object(gui_cmd, "_ensure_frontend_dependencies") as ensure_deps,
        mock.patch.object(
            gui_cmd.shutil, "which", side_effect=lambda name: f"/bin/{name}"
        ),
        mock.patch.object(
            gui_cmd.subprocess, "run", return_value=mock.Mock(returncode=0)
        ) as run,
        mock.patch.object(gui_cmd.subprocess, "Popen", return_value=process) as popen,
        mock.patch.object(gui_cmd, "_FrontendOwner") as owner_type,
        mock.patch.object(gui_cmd, "_api_healthy", return_value=False),
        mock.patch.object(
            gui_cmd, "_wait_for_port", return_value=True
        ) as wait_for_port,
        mock.patch.object(gui_cmd.webbrowser, "open") as open_browser,
        mock.patch.dict(os.environ, {"VITE_API_URL": "http://stale.example"}),
    ):
        result = CliRunner().invoke(
            gui_cmd.gui,
            ["--frontend-port", "5180", "--api-port", "8123", "--no-browser"],
        )

    assert result.exit_code == 0, result.output
    check_port.assert_called_once_with(5180)
    ensure_deps.assert_called_once_with(frontend, "/bin/npm")
    run.assert_called_once_with(
        [
            "/bin/uv",
            "run",
            "--extra",
            "desktop",
            "jarvis",
            "start",
            "--port",
            "8123",
        ],
        cwd=tmp_path,
        check=False,
    )
    args, kwargs = popen.call_args
    assert args[0] == [
        "/bin/npm",
        "run",
        "dev",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        "5180",
        "--strictPort",
    ]
    assert kwargs["cwd"] == frontend
    assert kwargs["env"]["OPENJARVIS_VITE_PROXY_TARGET"] == "http://127.0.0.1:8123"
    assert kwargs["env"]["VITE_API_URL"] == ""
    wait_for_port.assert_called_once_with(
        process, "127.0.0.1", 5180, on_poll=owner_type.return_value.refresh
    )
    open_browser.assert_not_called()
    process.wait.assert_called_once_with(timeout=gui_cmd._API_POLL_SECONDS)
    owner_type.return_value.shutdown.assert_called_once_with()


def test_gui_rejects_occupied_frontend_port_before_launch(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        with (
            mock.patch.object(gui_cmd, "_frontend_dir", return_value=frontend),
            mock.patch.object(gui_cmd.shutil, "which", return_value="/bin/npm"),
            mock.patch.object(gui_cmd, "_port_owner_pid", return_value=None),
            mock.patch.object(gui_cmd, "_ensure_frontend_dependencies") as ensure_deps,
            mock.patch.object(gui_cmd.subprocess, "Popen") as popen,
            mock.patch.object(gui_cmd.subprocess, "run") as run,
        ):
            result = CliRunner().invoke(
                gui_cmd.gui,
                ["--frontend-port", str(port), "--no-server", "--no-browser"],
            )

    assert result.exit_code != 0
    assert f"Frontend port {port} is unavailable" in result.output
    ensure_deps.assert_not_called()
    run.assert_not_called()
    popen.assert_not_called()


def test_wait_for_port_stops_when_vite_exits() -> None:
    process = mock.Mock(spec=subprocess.Popen)
    process.poll.return_value = 1
    with mock.patch.object(gui_cmd.socket, "create_connection") as connect:
        assert not gui_cmd._wait_for_port(process, "127.0.0.1", 5173)
    connect.assert_not_called()
