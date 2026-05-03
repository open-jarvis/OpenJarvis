"""Path resolution and commit-pin verification for foreign frameworks.

The ``_third_party.toml`` file declares the canonical filesystem path and
expected git commit for each foreign framework (Hermes Agent, OpenClaw).
Env vars (``HERMES_AGENT_PATH``, ``OPENCLAW_PATH``) override the default path.
``JARVIS_ALLOW_COMMIT_DRIFT=1`` disables strict commit-pin enforcement.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

import tomllib

# Map framework name -> env var that overrides its `path` field.
# Must be kept in sync with the section keys in _third_party.toml.
_PATH_ENV_VAR = {
    "hermes": "HERMES_AGENT_PATH",
    "openclaw": "OPENCLAW_PATH",
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
        env_var = _PATH_ENV_VAR.get(name)
        path_str = os.environ.get(env_var, body["path"]) if env_var else body["path"]
        entries[name] = ThirdPartyEntry(
            name=name,
            path=Path(path_str),
            pinned_commit=body.get("pinned_commit", ""),
            runner_script=body.get("runner_script", ""),
            python_executable=body.get("python_executable", ""),
            node_executable=body.get("node_executable", ""),
        )
    return ThirdPartyConfig(entries=entries)
