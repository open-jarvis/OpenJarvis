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
