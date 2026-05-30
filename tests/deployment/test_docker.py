"""Tests for Docker and deployment files."""

from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent.parent
DOCKER_DIR = ROOT / "deploy" / "docker"


class TestDockerFiles:
    def test_dockerfile_exists(self):
        assert (DOCKER_DIR / "Dockerfile").is_file()

    def test_dockerfile_gpu_exists(self):
        assert (DOCKER_DIR / "Dockerfile.gpu").is_file()

    def test_dockerfile_has_entrypoint(self):
        content = (DOCKER_DIR / "Dockerfile").read_text()
        assert "ENTRYPOINT" in content
        assert "jarvis" in content

    def test_dockerfile_copies_forced_package_includes(self):
        content = (DOCKER_DIR / "Dockerfile").read_text()
        install_step = content.index('uv pip install --system ".[server]"')
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())
        force_include = project["tool"]["hatch"]["build"]["targets"]["wheel"][
            "force-include"
        ]

        for source in force_include:
            if source.startswith("src/"):
                continue
            assert content.index(f"COPY {source} ") < install_step

    def test_docker_compose_valid_yaml(self):
        import importlib

        yaml_mod = None
        try:
            yaml_mod = importlib.import_module("yaml")
        except ImportError:
            pass

        compose_path = DOCKER_DIR / "docker-compose.yml"
        assert compose_path.is_file()
        content = compose_path.read_text()

        # Basic structural checks without requiring PyYAML
        assert "services:" in content
        assert "jarvis:" in content

        if yaml_mod is not None:
            data = yaml_mod.safe_load(content)
            assert "services" in data

    def test_docker_compose_has_services(self):
        content = (DOCKER_DIR / "docker-compose.yml").read_text()
        assert "jarvis:" in content
        assert "ollama:" in content

    def test_systemd_service_exists(self):
        assert (ROOT / "deploy" / "systemd" / "openjarvis.service").is_file()
