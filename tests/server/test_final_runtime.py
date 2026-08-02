from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from openjarvis.final_runtime import (
    FINAL_CODEX_EFFORT,
    FINAL_CODEX_MODEL,
    FINAL_HEALTH_MARKER,
    FINAL_MODEL,
    FINAL_RUNTIME_NAME,
    FinalCodexHealthEngine,
    _prepend_active_python_to_path,
    build_final_runtime,
    render_final_config,
    write_final_config,
)


def _roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    home = tmp_path / "product-home"
    vault = tmp_path / "approved-vault"
    home.mkdir()
    vault.mkdir()
    (vault / "note.md").write_text("# harmless fixture\n", encoding="utf-8")
    return home, vault, home / "config.toml"


def test_health_engine_never_performs_legacy_inference() -> None:
    engine = FinalCodexHealthEngine()
    assert engine.health() is True
    assert engine.list_models() == [FINAL_MODEL]
    assert engine.can_serve(FINAL_MODEL) is True
    assert engine.can_serve("ollama") is False
    with pytest.raises(RuntimeError, match="canonical Codex task API"):
        engine.generate([], model=FINAL_MODEL)


def test_generated_config_is_secret_free_and_fail_closed(tmp_path: Path) -> None:
    home, vault, _ = _roots(tmp_path)
    rendered = render_final_config(
        home=home.resolve(), vault=vault.resolve(), host="127.0.0.1", port=8123
    )
    assert "python_sdk" in rendered
    assert 'approval_mode = "deny_all"' in rendered
    assert 'analysis_sandbox = "read_only"' in rendered
    assert f'model = "{FINAL_CODEX_MODEL}"' in rendered
    assert f'reasoning_effort = "{FINAL_CODEX_EFFORT}"' in rendered
    assert "require_model_confirmation = true" in rendered
    assert "enabled = false" in rendered
    assert "api_key" not in rendered.lower()
    assert "password" not in rendered.lower()
    assert "cookie" not in rendered.lower()
    assert "ollama" not in rendered.lower()
    assert "http://" not in rendered.lower()
    assert "https://" not in rendered.lower()


def test_active_python_environment_is_prepended_for_child_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python_bin = tmp_path / "isolated-python" / "Scripts"
    python_bin.mkdir(parents=True)
    monkeypatch.setattr(
        "openjarvis.final_runtime.sys.executable", str(python_bin / "python.exe")
    )
    monkeypatch.setenv(
        "PATH", os.pathsep.join([str(tmp_path / "system"), str(python_bin)])
    )

    _prepend_active_python_to_path()
    first = os.environ["PATH"]
    _prepend_active_python_to_path()

    assert first.split(os.pathsep)[0] == str(python_bin)
    assert first.split(os.pathsep).count(str(python_bin)) == 1
    assert os.environ["PATH"] == first


def test_active_python_environment_is_added_without_private_hardcoding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python_bin = tmp_path / "venv" / "Scripts"
    python_bin.mkdir(parents=True)
    monkeypatch.setattr(
        "openjarvis.final_runtime.sys.executable", str(python_bin / "python.exe")
    )
    monkeypatch.setenv("PATH", str(tmp_path / "system"))

    _prepend_active_python_to_path()

    assert os.environ["PATH"].split(os.pathsep)[0] == str(python_bin)


@pytest.mark.asyncio
async def test_factory_wires_only_bounded_runtime_and_guarded_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, vault, config_path = _roots(tmp_path)
    monkeypatch.setenv("OPENJARVIS_HOME", str(home.resolve()))
    write_final_config(
        home=home,
        vault=vault,
        config_path=config_path,
        host="127.0.0.1",
        port=8124,
    )
    stopped: list[bool] = []
    runtime = build_final_runtime(
        home=home,
        vault=vault,
        config_path=config_path,
        shutdown_token="unit-test-token",
        shutdown_callback=lambda: stopped.append(True),
        initial_index=False,
    )

    assert runtime.app.state.browser_session_service is None
    assert runtime.app.state.channel_bridge is None
    assert runtime.app.state.analytics_client is None
    assert runtime.app.state.final_staging_root.is_relative_to(home.resolve())
    assert not runtime.app.state.final_staging_root.is_relative_to(vault.resolve())
    assert runtime.app.state.tool_action_service.runtime_available(
        "website.staging.mutate"
    )
    cleaned: list[str] = []
    monkeypatch.setattr(
        runtime.app.state.website_staging_service,
        "cleanup",
        lambda workspace_id: cleaned.append(workspace_id),
    )

    transport = httpx.ASGITransport(
        app=runtime.app,
        client=("127.0.0.1", 53123),
    )
    async with runtime.app.router.lifespan_context(runtime.app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:8124",
        ) as client:
            health = await client.get("/v1/final/health")
            assert health.status_code == 200
            assert health.json()["marker"] == FINAL_HEALTH_MARKER
            assert health.json()["runtime"] == FINAL_RUNTIME_NAME
            assert health.json()["components"] == {
                "codex_tasks": True,
                "vault_memory": True,
                "phase7": True,
                "tools": True,
                "website_staging": True,
                "analytics": False,
                "browser": False,
                "channels": False,
                "mcp": False,
            }
            denied = await client.post("/v1/final/shutdown")
            assert denied.status_code == 403
            invalid_cleanup = await client.post(
                "/v1/final/pilot-cleanup/bad.dot",
                headers={"x-openjarvis-shutdown-token": "unit-test-token"},
            )
            assert invalid_cleanup.status_code == 422
            cleanup = await client.post(
                "/v1/final/pilot-cleanup/phase8-final-website-pilot",
                headers={"x-openjarvis-shutdown-token": "unit-test-token"},
            )
            assert cleanup.status_code == 200
            assert cleanup.json() == {
                "status": "cleaned",
                "marker": FINAL_HEALTH_MARKER,
            }
            accepted = await client.post(
                "/v1/final/shutdown",
                headers={"x-openjarvis-shutdown-token": "unit-test-token"},
            )
            assert accepted.status_code == 202
            assert accepted.json()["marker"] == FINAL_HEALTH_MARKER
    assert stopped == [True]
    assert cleaned == ["phase8-final-website-pilot"]


def test_runtime_home_may_not_overlap_vault(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    forbidden_home = vault / "runtime"
    with pytest.raises(ValueError, match="outside both repository and vault"):
        write_final_config(
            home=forbidden_home,
            vault=vault,
            config_path=forbidden_home / "config.toml",
        )
    assert not forbidden_home.exists()
