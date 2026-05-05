"""Path resolution and commit-pin verification for foreign frameworks.

The ``_third_party.toml`` file declares the canonical filesystem path and
expected git commit for each foreign framework (Hermes Agent, OpenClaw).
Env vars (``HERMES_AGENT_PATH``, ``OPENCLAW_PATH``) override the default path.
``JARVIS_ALLOW_COMMIT_DRIFT=1`` disables strict commit-pin enforcement.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

import tomllib

LOGGER = logging.getLogger(__name__)

# Map framework name -> env var that overrides its `path` field.
# Must be kept in sync with the section keys in _third_party.toml.
_PATH_ENV_VAR = {
    "hermes": "HERMES_AGENT_PATH",
    "openclaw": "OPENCLAW_PATH",
}

# Map framework name -> env var that overrides its language-runtime executable.
# For hermes this overrides `python_executable` (point at the Hermes venv's
# python so its deps don't need to be installed in OpenJarvis's venv); for
# openclaw it overrides `node_executable` (point at a Node ≥14.8 binary if
# the system default is too old).
_RUNTIME_ENV_VAR = {
    "hermes": "HERMES_AGENT_PYTHON",
    "openclaw": "OPENCLAW_NODE",
}


class ThirdPartyError(Exception):
    """Base exception for third-party framework problems."""


class ThirdPartyNotFoundError(ThirdPartyError):
    """Raised when the third-party path cannot be resolved or doesn't exist."""


class CommitDriftError(ThirdPartyError):
    """Raised when the third-party repo's HEAD does not match the pinned commit."""


@dataclass(slots=True)
class ThirdPartyEntry:
    """One foreign framework's configuration."""

    name: str
    path: Path
    pinned_commit: str
    runner_script: str
    python_executable: str = ""
    node_executable: str = ""


@dataclass(slots=True)
class ThirdPartyConfig:
    """Top-level config: a map from framework name -> entry."""

    entries: Dict[str, ThirdPartyEntry] = field(default_factory=dict)


def _default_toml_path() -> Path:
    """Return the in-repo default location of `_third_party.toml`."""
    return (
        Path(__file__).resolve().parents[1]
        / "configs"
        / "framework_comparison"
        / "_third_party.toml"
    )


def load_third_party_config(toml_path: Optional[Path] = None) -> ThirdPartyConfig:
    """Load the third-party config, applying env-var path overrides.

    Raises:
        ThirdPartyNotFoundError: if the TOML doesn't exist.
    """
    if toml_path is None:
        toml_path = _default_toml_path()
    if not toml_path.exists():
        raise ThirdPartyNotFoundError(
            f"_third_party.toml not found at {toml_path}. "
            "Either create it or pass an explicit toml_path."
        )

    with open(toml_path, "rb") as fh:
        raw = tomllib.load(fh)

    entries: Dict[str, ThirdPartyEntry] = {}
    for name, body in raw.items():
        path_env = _PATH_ENV_VAR.get(name)
        path_str = os.environ.get(path_env, body["path"]) if path_env else body["path"]
        runtime_env = _RUNTIME_ENV_VAR.get(name)
        runtime_override = os.environ.get(runtime_env, "") if runtime_env else ""
        # The runtime-env override takes precedence over the TOML default for
        # whichever runtime field is relevant to this framework.
        python_exe = body.get("python_executable", "")
        node_exe = body.get("node_executable", "")
        if runtime_override:
            if name == "hermes":
                python_exe = runtime_override
            elif name == "openclaw":
                node_exe = runtime_override
        entries[name] = ThirdPartyEntry(
            name=name,
            path=Path(path_str),
            pinned_commit=body.get("pinned_commit", ""),
            runner_script=body.get("runner_script", ""),
            python_executable=python_exe,
            node_executable=node_exe,
        )
    return ThirdPartyConfig(entries=entries)


def verify_commit_pin(entry: ThirdPartyEntry) -> None:
    """Verify the entry's path is at the pinned commit.

    Raises:
        ThirdPartyNotFoundError: if the path doesn't exist or isn't a git repo.
        CommitDriftError: if HEAD doesn't match pinned_commit, unless
            ``JARVIS_ALLOW_COMMIT_DRIFT=1`` is set (then logs a warning).
    """
    env_var = _PATH_ENV_VAR.get(entry.name, "<env var>")
    if str(entry.path) == "" or str(entry.path) == ".":
        raise ThirdPartyNotFoundError(
            f"{entry.name} path is not configured. "
            f"Set the {env_var} environment variable to point at your "
            f"local {entry.name} checkout, or set `path = ...` in "
            f"_third_party.toml."
        )
    if not entry.path.exists():
        raise ThirdPartyNotFoundError(
            f"{entry.name} path does not exist: {entry.path}. "
            f"Set {env_var} to override, or update _third_party.toml."
        )

    try:
        result = subprocess.run(
            ["git", "-C", str(entry.path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise ThirdPartyNotFoundError(
            f"{entry.name} path is not a git repo: {entry.path} ({e.stderr.strip()})"
        ) from e

    actual = result.stdout.strip()
    pinned = entry.pinned_commit.strip()
    # Allow short-hash matches (e.g. pinned "abc123" matches actual "abc123def...")
    if not actual.startswith(pinned) and not pinned.startswith(actual):
        msg = (
            f"{entry.name} commit drift: pinned={pinned}, actual={actual}. "
            f"Either reset the repo to the pinned commit or update _third_party.toml. "
            f"To bypass for this run, set JARVIS_ALLOW_COMMIT_DRIFT=1."
        )
        if os.environ.get("JARVIS_ALLOW_COMMIT_DRIFT") == "1":
            LOGGER.warning(msg)
            return
        raise CommitDriftError(msg)
