# src/openjarvis/mining/_docker.py
"""Pearl Docker container orchestration.

See spec ``docs/design/2026-05-05-vllm-pearl-mining-integration-design.md``
section 7 for the design.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from openjarvis.mining._constants import (
    PEARL_CACHE_DIR,
    PEARL_IMAGE_TAG,
    PEARL_PINNED_REF,
    PEARL_REPO,
)


class ImageAcquisitionError(RuntimeError):
    """Raised when an image can be neither found, pulled, nor built."""


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

        try:
            self._client.images.pull(tag)
            return tag
        except (derr.NotFound, derr.APIError):
            pass

        if tag == PEARL_IMAGE_TAG:
            cache = self._clone_pearl_repo()
            return self._docker_build(cache, tag)

        raise ImageAcquisitionError(
            f"image {tag!r} not present locally, not pullable, and not OJ's "
            f"default tag (no build fallback). Either build it manually with "
            f"`docker buildx build -t {tag} -f miner/vllm-miner/Dockerfile .` "
            f"from the Pearl repo, or set [mining.extra].docker_image_tag to "
            f"the OJ default ({PEARL_IMAGE_TAG}) to enable the build fallback."
        )

    def _clone_pearl_repo(self) -> Path:
        """Clone Pearl at the pinned ref into the OJ cache."""
        PEARL_CACHE_DIR.parent.mkdir(parents=True, exist_ok=True)
        if PEARL_CACHE_DIR.exists():
            subprocess.run(
                ["git", "fetch", "origin", PEARL_PINNED_REF],
                cwd=str(PEARL_CACHE_DIR),
                check=True,
            )
            subprocess.run(
                ["git", "checkout", PEARL_PINNED_REF],
                cwd=str(PEARL_CACHE_DIR),
                check=True,
            )
        else:
            subprocess.run(
                [
                    "git", "clone",
                    "--branch", PEARL_PINNED_REF,
                    PEARL_REPO,
                    str(PEARL_CACHE_DIR),
                ],
                check=True,
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
        subprocess.run(cmd, cwd=str(repo_path), check=True)
        return tag
