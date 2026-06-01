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
        # Every Dockerfile that builds the wheel from an explicit `COPY src/`
        # context (rather than `COPY . .`) must also copy the non-src
        # force-include paths before installing, or hatchling's wheel build
        # fails (see #447). Guard ALL such Dockerfiles, not just the CPU one,
        # so the GPU variants can't silently regress.
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())
        force_include = project["tool"]["hatch"]["build"]["targets"]["wheel"][
            "force-include"
        ]
        non_src_includes = [s for s in force_include if not s.startswith("src/")]

        install_marker = 'uv pip install --system ".[server]"'
        wheel_dockerfiles = [
            p
            for p in sorted(DOCKER_DIR.glob("Dockerfile*"))
            if install_marker in p.read_text() and "COPY src/ src/" in p.read_text()
        ]
        # Sanity: we actually found the wheel-building Dockerfiles to guard.
        assert wheel_dockerfiles, "no wheel-building Dockerfiles found to check"

        for dockerfile in wheel_dockerfiles:
            content = dockerfile.read_text()
            install_step = content.index(install_marker)
            for source in non_src_includes:
                copy_marker = f"COPY {source} "
                assert copy_marker in content, (
                    f"{dockerfile.name} is missing '{copy_marker.strip()}' "
                    f"(a non-src force-include path)"
                )
                assert content.index(copy_marker) < install_step, (
                    f"{dockerfile.name} copies '{source}' after the install step"
                )

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
