# src/openjarvis/mining/_docker.py
"""Pearl Docker container orchestration.

See spec ``docs/design/2026-05-05-vllm-pearl-mining-integration-design.md``
section 7 for the design.
"""

from __future__ import annotations

import os
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


class ImageAcquisitionError(RuntimeError):
    """Raised when an image can be neither found, pulled, nor built."""


class ConfigurationError(RuntimeError):
    """Raised when required env vars or config fields are missing."""


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
        import docker.errors as derr

        try:
            self._client.images.get(tag)
            return tag
        except derr.ImageNotFound:
            pass

        pull_error: str | None = None
        try:
            self._client.images.pull(tag)
            return tag
        except (derr.NotFound, derr.APIError) as exc:
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
                    "checkout", "--detach", f"origin/{PEARL_PINNED_REF}",
                    cwd=PEARL_CACHE_DIR,
                )
            self._git("clean", "-fdx", cwd=PEARL_CACHE_DIR)
        else:
            # Fresh clone. Note: --branch accepts both branches and tags but
            # not arbitrary SHAs; for a SHA-pinned ref we'd need to clone +
            # then check out. For v1's ``main`` default, --branch is fine.
            self._git(
                "clone", "--branch", PEARL_PINNED_REF,
                PEARL_REPO, str(PEARL_CACHE_DIR),
                cwd=None,
            )
        return PEARL_CACHE_DIR

    def _docker_build(self, repo_path: Path, tag: str) -> str:
        """Run ``docker buildx build`` with Pearl's Dockerfile against the monorepo."""
        # Build context is the repo root; Dockerfile is at miner/vllm-miner/Dockerfile.
        cmd = [
            "docker", "buildx", "build",
            "-t", tag,
            "-f", "miner/vllm-miner/Dockerfile",
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

        model = extra.get("model", "pearl-ai/Llama-3.3-70B-Instruct-pearl")
        vllm_port = int(extra.get("vllm_port", 8000))
        gpu_mem = float(extra.get("gpu_memory_utilization", 0.9))
        max_len = int(extra.get("max_model_len", 8192))

        command = [
            model,
            "--host", "0.0.0.0",
            "--port", str(vllm_port),
            "--gpu-memory-utilization", str(gpu_mem),
            "--enforce-eager",
            "--max-model-len", str(max_len),
        ]

        environment = {
            "PEARLD_RPC_URL": extra.get("pearld_rpc_url", "http://localhost:44107"),
            "PEARLD_RPC_USER": extra.get("pearld_rpc_user", "rpcuser"),
            "PEARLD_RPC_PASSWORD": password,
            "PEARLD_MINING_ADDRESS": config.wallet_address,
            "HF_TOKEN": hf_token,
            "MINER_RPC_TRANSPORT": "tcp",
        }

        # Dynamic import so tests don't need the real `docker` package shape.
        try:
            from docker.types import DeviceRequest
            device_requests = [DeviceRequest(count=-1, capabilities=[["gpu"]])]
        except ImportError:  # pragma: no cover
            device_requests = None

        hf_cache = Path.home() / ".cache" / "huggingface"
        volumes = {
            str(hf_cache): {"bind": "/root/.cache/huggingface", "mode": "rw"},
        }

        self._container = self._client.containers.run(
            image=image,
            command=command,
            name="openjarvis-pearl-miner",
            detach=True,
            auto_remove=False,
            restart_policy={"Name": "unless-stopped"},
            device_requests=device_requests,
            shm_size="8g",
            network_mode="host",
            volumes=volumes,
            environment=environment,
        )
        return self._container

    def stop(self, timeout: int = 30) -> None:
        if self._container is None:
            return
        try:
            self._container.stop(timeout=timeout)
        except Exception:  # noqa: BLE001 - best-effort
            pass
        self._container = None

    def is_running(self) -> bool:
        if self._container is None:
            return False
        try:
            self._container.reload()
        except Exception:  # noqa: BLE001
            return False
        return getattr(self._container, "status", "") == "running"

    def get_logs(self, tail: int = 200) -> str:
        if self._container is None:
            return ""
        raw = self._container.logs(tail=tail)
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="replace")
        return str(raw)

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
