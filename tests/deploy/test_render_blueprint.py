"""Render Blueprint stays aligned with settings the server consumes."""

import shlex
from pathlib import Path

import yaml

from openjarvis.cli.serve import serve

RENDER_BLUEPRINT = Path(__file__).resolve().parents[2] / "render.yaml"
RENDER_DOC = Path(__file__).resolve().parents[2] / "docs/deployment/render.md"


def _service() -> dict:
    blueprint = yaml.safe_load(RENDER_BLUEPRINT.read_text(encoding="utf-8"))
    assert set(blueprint) == {"services"}
    assert len(blueprint["services"]) == 1
    return blueprint["services"][0]


def _env_vars(service: dict) -> dict[str, dict]:
    return {item["key"]: item for item in service["envVars"]}


def test_render_selects_cloud_engine_through_the_serve_cli() -> None:
    service = _service()
    args = shlex.split(service["dockerCommand"])

    assert args[0] == "serve"
    # Render expands $PORT before invoking the image entrypoint. Parsing the
    # substituted command through Click catches stale/renamed CLI options.
    parsed = serve.make_context(
        "serve",
        ["8080" if value == "$PORT" else value for value in args[1:]],
    )
    assert parsed.params["host"] == "0.0.0.0"
    assert parsed.params["port"] == 8080
    assert parsed.params["engine_key"] == "cloud"
    assert parsed.params["model_name"] == "gpt-4o-mini"
    assert "OPENJARVIS_ENGINE" not in _env_vars(service)


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
