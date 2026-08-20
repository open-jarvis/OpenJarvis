"""Deployment configs must not ship an unauthenticated public server (#221).

Every shipped deployment method must either bind loopback (no network
exposure) or require an API key, so that following the docs never yields an
open `0.0.0.0:8000` server. `check_bind_safety` is the runtime backstop;
these tests guard the static config files that drive it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY = REPO_ROOT / "deploy"


def _read(rel: str) -> str:
    return (DEPLOY / rel).read_text()


def test_docker_compose_requires_api_key():
    text = _read("docker/docker-compose.yml")
    # The container binds 0.0.0.0, so the key must be a *required* variable
    # (compose's ${VAR:?...} fails fast when unset).
    assert "OPENJARVIS_API_KEY" in text
    assert "OPENJARVIS_API_KEY:?" in text


def test_docker_env_example_present():
    assert (DEPLOY / "docker" / ".env.example").is_file()
    assert "OPENJARVIS_API_KEY" in _read("docker/.env.example")


def test_systemd_unit_binds_public_and_requires_env_file():
    text = _read("systemd/openjarvis.service")
    # Public bind -> must pull in an EnvironmentFile (no leading '-', so the
    # unit fails to start if it's missing).
    assert "--host 0.0.0.0" in text
    assert "EnvironmentFile=/etc/openjarvis/env" in text
    assert "\n-EnvironmentFile" not in text and "=-/etc" not in text


def test_launchd_plist_binds_loopback():
    text = _read("launchd/com.openjarvis.plist")
    # Personal-device default: loopback, not the network.
    assert "<string>127.0.0.1</string>" in text
    assert "<string>0.0.0.0</string>" not in text


@pytest.mark.parametrize(
    ("host", "api_key", "should_exit"),
    [
        ("127.0.0.1", "", False),
        ("localhost", "", False),
        ("0.0.0.0", "oj_sk_x", False),
        ("0.0.0.0", "", True),
        ("192.168.1.10", "", True),
    ],
)
def test_check_bind_safety(host, api_key, should_exit):
    from openjarvis.server.auth_middleware import check_bind_safety

    if should_exit:
        with pytest.raises(SystemExit):
            check_bind_safety(host, api_key=api_key)
    else:
        check_bind_safety(host, api_key=api_key)  # must not raise
