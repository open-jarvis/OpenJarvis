"""Render Blueprint stays aligned with settings the server consumes."""

import json
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


def _docker_json_instruction(name: str) -> list[str]:
    prefix = f"{name} "
    instructions = [
        line.removeprefix(prefix)
        for line in DOCKERFILE.read_text(encoding="utf-8").splitlines()
        if line.startswith(prefix)
    ]
    assert len(instructions) == 1
    value = json.loads(instructions[0])
    assert isinstance(value, list)
    assert all(isinstance(item, str) for item in value)
    return value


def _run_fake_jarvis(tmp_path: Path, argv: list[str]) -> list[str]:
    """Run an argv assembled with Docker's exec-form ENTRYPOINT semantics."""
    fake_jarvis = tmp_path / "jarvis"
    fake_jarvis.write_text(
        "#!/bin/sh\nprintf '%s\\0' \"$@\"\n",
        encoding="utf-8",
    )
    fake_jarvis.chmod(0o755)
    completed = subprocess.run(
        [str(fake_jarvis), *argv[1:]],
        check=True,
        capture_output=True,
    )
    return completed.stdout.rstrip(b"\0").decode().split("\0")


def test_render_selects_cloud_engine_through_the_serve_cli(tmp_path: Path) -> None:
    service = _service()
    command = service["dockerCommand"]
    assert "$" not in command
    assert "/bin/sh" not in command

    # Render replaces CMD but preserves the image's exec-form ENTRYPOINT.
    # Exercise the resulting argv without starting a real server.
    argv = [*_docker_json_instruction("ENTRYPOINT"), *shlex.split(command)]
    args = _run_fake_jarvis(tmp_path, argv)

    assert args == [
        "serve",
        "--host",
        "0.0.0.0",
        "--port",
        "10000",
        "--engine",
        "cloud",
        "--model",
        "gpt-4o-mini",
    ]
    parsed = serve.make_context("serve", args[1:])
    assert parsed.params["host"] == "0.0.0.0"
    assert parsed.params["port"] == 10000
    assert parsed.params["engine_key"] == "cloud"
    assert parsed.params["model_name"] == "gpt-4o-mini"
    assert "OPENJARVIS_ENGINE" not in _env_vars(service)
    assert _env_vars(service)["PORT"] == {"key": "PORT", "value": "10000"}


def test_docker_and_compose_command_overrides_remain_jarvis_subcommands(
    tmp_path: Path,
) -> None:
    entrypoint = _docker_json_instruction("ENTRYPOINT")
    default_command = _docker_json_instruction("CMD")
    compose_override = [
        "serve",
        "--host",
        "0.0.0.0",
        "--port",
        "9000",
        "--model",
        "qwen3:8b",
    ]

    assert entrypoint == ["jarvis"]
    assert default_command == [
        "serve",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ]
    assert (
        _run_fake_jarvis(tmp_path, [*entrypoint, *default_command]) == default_command
    )
    assert (
        _run_fake_jarvis(tmp_path, [*entrypoint, *compose_override]) == compose_override
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
