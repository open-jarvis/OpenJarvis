"""Tests for Docker and deployment files.

These are static file-content checks (no Docker daemon required) so they run in
the default CI lane. They guard the deployment hardening from #228 and its
sub-issues (#563 image pinning, #564 systemd hardening, #565 non-root, #566
secure Node install, #567 frozen lockfile installs).
"""

from __future__ import annotations

import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent.parent
DOCKER_DIR = ROOT / "deploy" / "docker"
SYSTEMD_DIR = ROOT / "deploy" / "systemd"


def _dockerfiles() -> list[Path]:
    return sorted(DOCKER_DIR.glob("Dockerfile*"))


def _compose_files() -> list[Path]:
    return sorted(DOCKER_DIR.glob("docker-compose*.yml"))


def _from_lines(content: str) -> list[str]:
    return [
        ln.strip()
        for ln in content.splitlines()
        if ln.strip().upper().startswith("FROM ")
    ]


def _image_lines(content: str) -> list[str]:
    """`image: ...` lines from a compose file, ignoring comments."""
    out = []
    for ln in content.splitlines():
        stripped = ln.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith("image:"):
            out.append(stripped)
    return out


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

        # The project itself is built by the final `--no-deps .` install (#567);
        # the force-includes must be present before that step.
        install_marker = "uv pip install --system --no-deps ."
        wheel_dockerfiles = [
            p
            for p in _dockerfiles()
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

    def test_dockerfiles_build_native_rust_extension(self):
        build_dockerfiles = [
            "Dockerfile",
            "Dockerfile.gpu",
            "Dockerfile.gpu.rocm",
            "Dockerfile.sandbox",
        ]
        required_markers = [
            "rustup toolchain install 1.88",
            "maturin build --release",
            "rust/crates/openjarvis-python/Cargo.toml",
            "/tmp/openjarvis-rust-wheel/*.whl",
            "import openjarvis_rust",
        ]

        for name in build_dockerfiles:
            content = (DOCKER_DIR / name).read_text()
            for marker in required_markers:
                assert marker in content, (
                    f"{name}: missing native build marker {marker!r}"
                )

        for name in ["Dockerfile", "Dockerfile.gpu", "Dockerfile.gpu.rocm"]:
            content = (DOCKER_DIR / name).read_text()
            assert "COPY rust/ rust/" in content, f"{name}: rust workspace not copied"
            assert content.index("COPY rust/ rust/") < content.index(
                "maturin build --release"
            ), f"{name}: rust workspace copied after native build"

    def test_systemd_service_exists(self):
        assert (SYSTEMD_DIR / "openjarvis.service").is_file()


class TestImagePinning:
    """#563 — base images and ollama pinned to fixed versions + digests."""

    def test_no_floating_latest_tag_in_image_directives(self):
        # `:latest` only acceptable inside comments (rationale text).
        for path in _dockerfiles() + _compose_files():
            for ln in path.read_text().splitlines():
                code = ln.split("#", 1)[0]
                assert ":latest" not in code, f"{path.name}: floating :latest in {ln!r}"

    def test_every_from_pins_a_digest(self):
        for path in _dockerfiles():
            froms = _from_lines(path.read_text())
            assert froms, f"{path.name}: no FROM lines found"
            for ln in froms:
                assert "@sha256:" in ln, (
                    f"{path.name}: FROM is not digest-pinned: {ln!r}"
                )

    def test_ollama_image_pinned_with_version_and_digest(self):
        for path in _compose_files():
            for ln in _image_lines(path.read_text()):
                if "ollama/ollama" in ln:
                    assert "@sha256:" in ln, f"{path.name}: ollama not digest-pinned"
                    # A concrete version tag (digits) must accompany the digest.
                    assert re.search(r"ollama/ollama:\d", ln), (
                        f"{path.name}: ollama missing a version tag"
                    )


class TestNonRootUser:
    """#565 — GPU images (and the base image) drop root."""

    NON_ROOT = ["Dockerfile", "Dockerfile.gpu", "Dockerfile.gpu.rocm"]

    def test_creates_and_switches_to_non_root_user(self):
        for name in self.NON_ROOT:
            content = (DOCKER_DIR / name).read_text()
            assert "useradd" in content, f"{name}: no useradd"
            # A USER directive switching away from root must exist and not be root.
            user_lines = [
                ln.strip()
                for ln in content.splitlines()
                if ln.strip().upper().startswith("USER ")
            ]
            assert user_lines, f"{name}: no USER directive"
            assert all("root" not in ln for ln in user_lines), (
                f"{name}: USER directive still root"
            )

    def test_user_directive_is_last_stage(self):
        # USER must appear after the final FROM so the runtime stage is non-root.
        for name in self.NON_ROOT:
            content = (DOCKER_DIR / name).read_text()
            last_from = content.rfind("\nFROM ")
            user_idx = content.rfind("\nUSER ")
            assert user_idx > last_from, f"{name}: USER not in final runtime stage"


class TestSandboxNodeSecurity:
    """#566 — Node installed without an unverified curl|bash pipe."""

    def test_no_curl_pipe_bash(self):
        content = (DOCKER_DIR / "Dockerfile.sandbox").read_text()
        for ln in content.splitlines():
            code = ln.split("#", 1)[0]  # ignore the explanatory comment
            assert "| bash" not in code and "|bash" not in code, (
                f"unverified pipe-to-bash install remains: {ln!r}"
            )
            assert "nodesource.com" not in code, "still using NodeSource setup script"

    def test_node_sourced_from_pinned_official_image(self):
        content = (DOCKER_DIR / "Dockerfile.sandbox").read_text()
        assert "COPY --from=node" in content, "Node not copied from pinned image stage"
        froms = _from_lines(content)
        assert any("node:" in ln and "@sha256:" in ln for ln in froms), (
            "no digest-pinned node base stage"
        )


class TestFrozenInstall:
    """#567 — Docker builds install from the committed, frozen uv.lock."""

    BUILD_DOCKERFILES = [
        "Dockerfile",
        "Dockerfile.gpu",
        "Dockerfile.gpu.rocm",
        "Dockerfile.sandbox",
    ]

    def test_copies_lockfile(self):
        for name in self.BUILD_DOCKERFILES:
            content = (DOCKER_DIR / name).read_text()
            assert "uv.lock" in content, f"{name}: uv.lock not referenced"

    def test_uses_frozen_export(self):
        for name in self.BUILD_DOCKERFILES:
            content = (DOCKER_DIR / name).read_text()
            assert "uv export --frozen" in content, f"{name}: no frozen export"
            assert "--no-deps" in content, (
                f"{name}: deps re-resolved (missing --no-deps)"
            )

    def test_no_unpinned_pyproject_resolution(self):
        # The old `uv pip install --system ".[server]"` re-resolved deps on every
        # build; it must not come back.
        for name in self.BUILD_DOCKERFILES:
            content = (DOCKER_DIR / name).read_text()
            assert '".[server]"' not in content, (
                f"{name}: still re-resolves from pyproject"
            )


class TestSystemdHardening:
    """#564 — systemd unit ships secrets via EnvironmentFile and is sandboxed."""

    def _service(self) -> str:
        return (SYSTEMD_DIR / "openjarvis.service").read_text()

    def test_environment_file_for_secrets(self):
        assert "EnvironmentFile=" in self._service()

    def test_core_hardening_directives_present(self):
        content = self._service()
        for directive in (
            "NoNewPrivileges=true",
            "ProtectSystem=strict",
            "PrivateTmp=true",
        ):
            assert directive in content, f"missing hardening directive: {directive}"

    def test_writable_state_path_declared(self):
        # ProtectSystem=strict makes the FS read-only; the working/home dir must
        # be re-granted write access or the server cannot persist config/state.
        content = self._service()
        assert "ReadWritePaths=" in content
