"""Render Blueprint stays aligned with settings the server consumes."""

import os
import shlex
import subprocess
from pathlib import Path

import yaml

from openjarvis.cli.serve import serve

RENDER_BLUEPRINT = Path(__file__).resolve().parents[2] / "render.yaml"
RENDER_DOC = Path(__file__).resolve().parents[2] / "docs/deployment/render.md"
DOCKERFILE = Path(__file__).resolve().parents[2] / "deploy/docker/Dockerfile"


def _service() -> dict:
    blueprint = yaml.safe_load(RENDER_BLUEPRINT.read_text(encoding="utf-8"))
    assert set(blueprint) == {"services"}
    assert len(blueprint["services"]) == 1
    return blueprint["services"][0]


def _env_vars(service: dict) -> dict[str, dict]:
    return {item["key"]: item for item in service["envVars"]}


def test_render_selects_cloud_engine_through_the_serve_cli(tmp_path: Path) -> None:
    service = _service()
    docker_command = shlex.split(service["dockerCommand"])

    assert docker_command[:2] == ["/bin/sh", "-c"]

    # Exercise the same shell Render starts. A fake `jarvis` executable records
    # the expanded argv without starting a real server.
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_jarvis = fake_bin / "jarvis"
    fake_jarvis.write_text(
        "#!/bin/sh\nprintf '%s\\0' \"$@\"\n",
        encoding="utf-8",
    )
    fake_jarvis.chmod(0o755)
    env = os.environ.copy()
    env.update({"PATH": f"{fake_bin}{os.pathsep}{env['PATH']}", "PORT": "18080"})
    completed = subprocess.run(
        docker_command,
        check=True,
        capture_output=True,
        env=env,
    )
    args = completed.stdout.rstrip(b"\0").decode().split("\0")

    assert args == [
        "serve",
        "--host",
        "0.0.0.0",
        "--port",
        "18080",
        "--engine",
        "cloud",
        "--model",
        "gpt-4o-mini",
    ]
    parsed = serve.make_context("serve", args[1:])
    assert parsed.params["host"] == "0.0.0.0"
    assert parsed.params["port"] == 18080
    assert parsed.params["engine_key"] == "cloud"
    assert parsed.params["model_name"] == "gpt-4o-mini"
    assert "OPENJARVIS_ENGINE" not in _env_vars(service)


def test_docker_command_can_replace_the_image_default() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert 'ENTRYPOINT ["jarvis"]' not in dockerfile
    assert 'CMD ["jarvis", "serve", "--host", "0.0.0.0", "--port", "8000"]' in (
        dockerfile
    )


def test_render_does_not_advertise_an_unconsumed_cors_variable() -> None:
    assert "OPENJARVIS_CORS_ORIGINS" not in _env_vars(_service())


def test_render_public_bind_generates_an_api_key() -> None:
    env = _env_vars(_service())

    assert env["OPENJARVIS_API_KEY"] == {
        "key": "OPENJARVIS_API_KEY",
        "generateValue": True,
    }


def test_render_contract_requires_one_supported_cloud_provider() -> None:
    service = _service()
    env = _env_vars(service)

    assert service["runtime"] == "docker"
    assert service["dockerfilePath"] == "./deploy/docker/Dockerfile"
    assert service["healthCheckPath"] == "/health"
    assert env["OPENAI_API_KEY"] == {"key": "OPENAI_API_KEY", "sync": False}
    # Every sync:false entry is mandatory during initial Blueprint creation.
    assert [
        item["key"] for item in service["envVars"] if item.get("sync") is False
    ] == ["OPENAI_API_KEY"]


def test_render_free_tier_ephemeral_storage_is_explicitly_documented() -> None:
    service = _service()
    env = _env_vars(service)
    docs = RENDER_DOC.read_text(encoding="utf-8").lower()

    assert service["plan"] == "free"
    assert "disk" not in service
    assert env["OPENJARVIS_HOME"]["value"] == "/home/openjarvis/.openjarvis"
    assert "ephemeral" in docs
    assert "lost" in docs
    assert "persistent disk" in docs
