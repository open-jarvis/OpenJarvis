# src/openjarvis/mining/_docker.py
"""Pearl Docker container orchestration.

See spec ``docs/design/2026-05-05-vllm-pearl-mining-integration-design.md``
section 7 for the design.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openjarvis.mining._stubs import MiningConfig

from openjarvis.mining._constants import (
    PEARL_CACHE_DIR,
    PEARL_IMAGE_TAG,
    PEARL_PINNED_REF,
    PEARL_REPO,
)

CONTAINER_NAME = "openjarvis-pearl-miner"
LOCAL_MODEL_BIND_PATH = "/models/openjarvis-local-pearl-model"

_SECRET_LOG_PATTERNS = (
    (re.compile(r"(rpc_password:\s*)\S+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r"(PEARLD_RPC_PASSWORD=)\S+"), r"\1[REDACTED]"),
    (re.compile(r'("PEARLD_RPC_PASSWORD"\s*:\s*")[^"]+(")'), r"\1[REDACTED]\2"),
)


class ImageAcquisitionError(RuntimeError):
    """Raised when an image can be neither found, pulled, nor built."""


class ConfigurationError(RuntimeError):
    """Raised when required env vars or config fields are missing."""


class ImageNotFound(Exception):
    """Fallback image-not-found error when Docker SDK is not installed."""


class NotFound(Exception):
    """Fallback Docker not-found error when Docker SDK is not installed."""


class APIError(Exception):
    """Fallback Docker API error when Docker SDK is not installed."""


def _docker_error_types() -> tuple[type[Exception], type[Exception], type[Exception]]:
    try:
        import docker.errors as derr

        return derr.ImageNotFound, derr.NotFound, derr.APIError
    except ImportError:
        return ImageNotFound, NotFound, APIError


class PearlDockerLauncher:
    """Orchestrates the Pearl miner container.

    Construct with a ``docker.DockerClient`` (real or mocked).
    """

    def __init__(self, client: Any):
        self._client = client
        self._container: Any | None = None

    # -----------------------------------------------------------------
    # Image acquisition
    # -----------------------------------------------------------------

    def ensure_image(self, tag: str) -> str:
        """Resolve ``tag`` to a usable local image, building if necessary.

        Selection order (see spec §7.2):
        1. Image present locally → use it.
        2. Image pullable from a registry → pull and use.
        3. ``tag`` matches OJ's default → clone Pearl + ``docker build``.
        4. Otherwise → ``ImageAcquisitionError``.
        """
        image_not_found, not_found, api_error = _docker_error_types()

        try:
            self._client.images.get(tag)
            return tag
        except image_not_found:
            pass

        pull_error: str | None = None
        try:
            self._client.images.pull(tag)
            return tag
        except (not_found, api_error) as exc:
            # Capture for context in the eventual ImageAcquisitionError below;
            # we still fall through to the build path for the OJ default tag.
            msg = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
            pull_error = msg

        if tag == PEARL_IMAGE_TAG:
            cache = self._clone_pearl_repo()
            return self._docker_build(cache, tag)

        raise ImageAcquisitionError(
            f"image {tag!r} not present locally, not pullable, and not OJ's "
            f"default tag (no build fallback). Pull error: {pull_error}. "
            f"Either build it manually with "
            f"`docker buildx build -t {tag} -f miner/vllm-miner/Dockerfile .` "
            f"from the Pearl repo, or set [mining.extra].docker_image_tag to "
            f"the OJ default ({PEARL_IMAGE_TAG}) to enable the build fallback."
        )

    def _clone_pearl_repo(self) -> Path:
        """Sync the Pearl source cache to ``PEARL_PINNED_REF``.

        Uses a detached-HEAD checkout strategy so the result is correct for
        both branch refs (mutable) and commit SHAs (immutable). Discards any
        local modifications and untracked build artifacts in the cache so a
        previous interrupted run can't poison the build context.
        """
        PEARL_CACHE_DIR.parent.mkdir(parents=True, exist_ok=True)
        if PEARL_CACHE_DIR.exists() and (PEARL_CACHE_DIR / ".git").exists():
            self._git("fetch", "origin", cwd=PEARL_CACHE_DIR)
            # Detach to origin/<ref> when ref is a branch; for a SHA this
            # falls through naturally because `origin/<sha>` doesn't exist
            # but `<sha>` does — try the bare ref first, fall back to origin/.
            try:
                self._git("checkout", "--detach", PEARL_PINNED_REF, cwd=PEARL_CACHE_DIR)
            except ImageAcquisitionError:
                self._git(
                    "checkout",
                    "--detach",
                    f"origin/{PEARL_PINNED_REF}",
                    cwd=PEARL_CACHE_DIR,
                )
            self._git(
                "submodule",
                "update",
                "--init",
                "--recursive",
                cwd=PEARL_CACHE_DIR,
            )
            self._git("clean", "-fdx", cwd=PEARL_CACHE_DIR)
        else:
            # Fresh clone. Note: --branch accepts both branches and tags but
            # not arbitrary SHAs; for a SHA-pinned ref we'd need to clone +
            # then check out. For v1's ``main`` default, --branch is fine.
            self._git(
                "clone",
                "--branch",
                PEARL_PINNED_REF,
                PEARL_REPO,
                str(PEARL_CACHE_DIR),
                cwd=None,
            )
            self._git(
                "submodule",
                "update",
                "--init",
                "--recursive",
                cwd=PEARL_CACHE_DIR,
            )
        return PEARL_CACHE_DIR

    def _docker_build(self, repo_path: Path, tag: str) -> str:
        """Run ``docker buildx build`` with Pearl's Dockerfile against the monorepo."""
        self._patch_vllm_dockerfile(repo_path)
        self._patch_vllm_entrypoint(repo_path)

        # Build context is the repo root; Dockerfile is at miner/vllm-miner/Dockerfile.
        cmd = [
            "docker",
            "buildx",
            "build",
            "--ulimit",
            "nofile=1048576:1048576",
            "-t",
            tag,
            "-f",
            "miner/vllm-miner/Dockerfile",
            ".",
        ]
        try:
            subprocess.run(
                cmd,
                cwd=str(repo_path),
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr_tail = (exc.stderr or "").strip().splitlines()[-10:]
            raise ImageAcquisitionError(
                f"docker build failed (exit {exc.returncode}): "
                + " | ".join(stderr_tail)
            ) from exc
        return tag

    def _patch_vllm_dockerfile(self, repo_path: Path) -> None:
        """Patch Pearl's runtime image to include nvcc for DeepGEMM JIT.

        Pearl's current Dockerfile builds kernels in a CUDA devel image, then
        switches to a CUDA runtime image. vLLM 0.20's DeepGEMM path still JITs
        kernels at runtime and asserts that nvcc exists, so the runtime image
        must keep the CUDA compiler toolchain.
        """
        dockerfile = repo_path / "miner" / "vllm-miner" / "Dockerfile"
        text = dockerfile.read_text()
        old = "FROM nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu24.04"
        new = "FROM nvidia/cuda:${CUDA_VERSION}-devel-ubuntu24.04"
        if old in text:
            dockerfile.write_text(text.replace(old, new))

    def _patch_vllm_entrypoint(self, repo_path: Path) -> None:
        """Patch Pearl's current entrypoint to wait on the UDS gateway socket.

        The upstream entrypoint waits for a Prometheus endpoint that the current
        gateway package does not start, which causes the container to restart
        before vLLM launches. The miner itself expects the UDS path, so wait for
        that socket instead.
        """
        entrypoint = repo_path / "miner" / "vllm-miner" / "entrypoint.sh"
        text = entrypoint.read_text()
        old = (
            "# Wait until the gateway is ready\n"
            "curl -s http://localhost:8339/metrics --retry-delay 1 --retry 20 "
            "--retry-all-errors > /dev/null"
        )
        new = (
            "# Wait until the gateway is ready\n"
            "for i in $(seq 1 20); do\n"
            "    [ -S /tmp/pearlgw.sock ] && break\n"
            "    sleep 1\n"
            "done\n"
            "[ -S /tmp/pearlgw.sock ]"
        )
        if old in text:
            entrypoint.write_text(text.replace(old, new))

    # -----------------------------------------------------------------
    # Container lifecycle
    # -----------------------------------------------------------------

    def start(self, config: "MiningConfig", image: str) -> Any:
        """Launch the Pearl miner container.

        ``image`` must already be resolved by ``ensure_image()``.
        Returns the docker.models.containers.Container object.
        """
        extra = config.extra
        # Resolve secret env vars (we hold the *name*, not the value).
        password_env = extra.get("pearld_rpc_password_env", "PEARLD_RPC_PASSWORD")
        password = os.environ.get(password_env)
        if password is None:
            raise ConfigurationError(
                f"environment variable {password_env!r} is not set; "
                f"set it before running `jarvis mine start`"
            )

        hf_token_env = extra.get("hf_token_env", "HF_TOKEN")
        hf_token = os.environ.get(hf_token_env, "")

        model = str(extra.get("model", "pearl-ai/Llama-3.3-70B-Instruct-pearl"))
        local_model_path = extra.get("local_model_path")
        vllm_port = int(extra.get("vllm_port", 8000))
        gpu_mem = float(extra.get("gpu_memory_utilization", 0.96))
        max_len = int(extra.get("max_model_len", 8192))

        model_arg = model
        local_model_host_path: Path | None = None
        if local_model_path:
            local_model_host_path = Path(str(local_model_path)).expanduser().resolve()
            if not local_model_host_path.exists():
                raise ConfigurationError(
                    f"local Pearl model path does not exist: {local_model_host_path}"
                )
            if not local_model_host_path.is_dir():
                raise ConfigurationError(
                    "local Pearl model path must be a directory: "
                    f"{local_model_host_path}"
                )
            model_arg = LOCAL_MODEL_BIND_PATH

        command = [
            model_arg,
            "--host",
            "0.0.0.0",
            "--port",
            str(vllm_port),
            "--gpu-memory-utilization",
            str(gpu_mem),
            "--enforce-eager",
            "--max-model-len",
            str(max_len),
        ]
        if local_model_host_path is not None:
            command.extend(["--served-model-name", model])
        command.extend(_extra_vllm_args(extra.get("vllm_args", [])))

        environment = {
            "PEARLD_RPC_URL": extra.get("pearld_rpc_url", "http://localhost:44107"),
            "PEARLD_RPC_USER": extra.get("pearld_rpc_user", "rpcuser"),
            "PEARLD_RPC_PASSWORD": password,
            "PEARLD_MINING_ADDRESS": config.wallet_address,
            "HF_TOKEN": hf_token,
            "MINER_RPC_TRANSPORT": "uds",
            "MINER_RPC_SOCKET_PATH": "/tmp/pearlgw.sock",
        }

        cuda_devices = str(extra.get("cuda_visible_devices", "")).strip()
        device_ids = [part.strip() for part in cuda_devices.split(",") if part.strip()]
        if device_ids:
            # Docker's device request exposes the selected host GPUs inside
            # the container as a compact 0..N-1 list. Keep host IDs for the
            # NVIDIA runtime and use container-local IDs for CUDA/vLLM.
            environment["CUDA_VISIBLE_DEVICES"] = ",".join(
                str(idx) for idx, _ in enumerate(device_ids)
            )
            environment["NVIDIA_VISIBLE_DEVICES"] = ",".join(device_ids)

        # Dynamic import so tests don't need the real `docker` package shape.
        try:
            from docker.types import DeviceRequest

            if device_ids:
                device_requests = [
                    DeviceRequest(device_ids=device_ids, capabilities=[["gpu"]])
                ]
            else:
                device_requests = [DeviceRequest(count=-1, capabilities=[["gpu"]])]
        except ImportError:  # pragma: no cover
            device_requests = None

        hf_cache = Path.home() / ".cache" / "huggingface"
        volumes = {
            str(hf_cache): {"bind": "/root/.cache/huggingface", "mode": "rw"},
        }
        if local_model_host_path is not None:
            volumes[str(local_model_host_path)] = {
                "bind": LOCAL_MODEL_BIND_PATH,
                "mode": "ro",
            }

        # Sanitize wrap so an APIError from the daemon doesn't surface the
        # full container spec (which contains the resolved password) in a
        # bubbled-up traceback. Docker's APIError __str__ embeds the request
        # body verbatim. We surface the image name and exit reason only.
        try:
            self._container = self._client.containers.run(
                image=image,
                command=command,
                name=CONTAINER_NAME,
                detach=True,
                auto_remove=False,
                restart_policy={"Name": "unless-stopped"},
                device_requests=device_requests,
                shm_size="8g",
                network_mode="host",
                volumes=volumes,
                environment=environment,
            )
        except Exception as exc:  # noqa: BLE001 - intentional broad sanitize
            cls = exc.__class__.__name__
            raise ConfigurationError(
                f"failed to launch container from image {image!r} ({cls}); "
                f"check `docker ps -a` and `docker logs {CONTAINER_NAME}` "
                f"for daemon-side details"
            ) from None
        return self._container

    def _current_container(self) -> Any | None:
        if self._container is not None:
            return self._container

        _, not_found, _ = _docker_error_types()
        try:
            self._container = self._client.containers.get(CONTAINER_NAME)
        except not_found:
            return None
        except Exception:  # noqa: BLE001 - daemon unavailable means no session state.
            return None
        return self._container

    def stop(self, timeout: int = 30) -> None:
        container = self._current_container()
        if container is None:
            return
        try:
            container.stop(timeout=timeout)
        except Exception:  # noqa: BLE001 - best-effort
            pass
        try:
            container.remove()
        except Exception:  # noqa: BLE001 - best-effort
            pass
        self._container = None

    def is_running(self) -> bool:
        container = self._current_container()
        if container is None:
            return False
        try:
            container.reload()
        except Exception:  # noqa: BLE001
            return False
        return getattr(container, "status", "") == "running"

    def get_logs(self, tail: int = 200) -> str:
        container = self._current_container()
        if container is None:
            return ""
        raw = container.logs(tail=tail)
        if isinstance(raw, bytes):
            text = raw.decode("utf-8", errors="replace")
        else:
            text = str(raw)
        return _redact_container_logs(text)

    @staticmethod
    def _git(*args: str, cwd: Path | None) -> None:
        """Invoke git with stderr capture so failures surface readably."""
        cmd = ["git", *args]
        try:
            subprocess.run(
                cmd,
                cwd=str(cwd) if cwd is not None else None,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr_tail = (exc.stderr or "").strip().splitlines()[-5:]
            raise ImageAcquisitionError(
                f"`{' '.join(cmd)}` failed (exit {exc.returncode}): "
                + " | ".join(stderr_tail)
            ) from exc


def _redact_container_logs(text: str) -> str:
    """Redact secrets known to appear in upstream Pearl container logs."""
    redacted = text
    for pattern, replacement in _SECRET_LOG_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _extra_vllm_args(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return shlex.split(value)
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    raise ConfigurationError("[mining.extra].vllm_args must be a string or list")
