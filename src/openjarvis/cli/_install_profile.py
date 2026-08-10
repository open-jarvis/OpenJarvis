"""Persist optional uv features used by editable OpenJarvis installs."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

PROFILE_FILENAME = ".openjarvis-install-profile.json"
PROFILE_VERSION = 1

_OPTION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class InstallProfile:
    """The uv feature set selected by a project-local installer."""

    version: int
    extras: tuple[str, ...]
    groups: tuple[str, ...]


def _normalize_options(options: Sequence[str]) -> tuple[str, ...]:
    normalized: set[str] = set()
    for option in options:
        if not isinstance(option, str) or _OPTION_PATTERN.fullmatch(option) is None:
            raise ValueError(f"invalid install profile option: {option!r}")
        normalized.add(option)
    return tuple(sorted(normalized))


def load_install_profile(
    repo_root: Path,
) -> tuple[InstallProfile | None, str | None]:
    """Load a validated profile, returning a user-facing warning on failure."""
    path = Path(repo_root) / PROFILE_FILENAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, f"Invalid install profile at {path}: {exc}"

    if not isinstance(raw, dict):
        return None, f"Invalid install profile at {path}: expected an object"

    version = raw.get("version")
    if type(version) is not int or version != PROFILE_VERSION:
        return None, f"Unsupported install profile version at {path}: {version!r}"

    extras = raw.get("extras")
    groups = raw.get("groups")
    if not isinstance(extras, list) or not isinstance(groups, list):
        return None, f"Invalid install profile at {path}: extras/groups must be lists"

    try:
        profile = InstallProfile(
            version=version,
            extras=_normalize_options(extras),
            groups=_normalize_options(groups),
        )
    except ValueError as exc:
        return None, f"Invalid install profile at {path}: {exc}"
    return profile, None


def write_install_profile(
    repo_root: Path,
    *,
    extras: Sequence[str],
    groups: Sequence[str],
) -> Path:
    """Atomically write a validated version-1 profile in ``repo_root``."""
    root = Path(repo_root)
    profile = InstallProfile(
        version=PROFILE_VERSION,
        extras=_normalize_options(extras),
        groups=_normalize_options(groups),
    )
    payload = {
        "version": profile.version,
        "extras": list(profile.extras),
        "groups": list(profile.groups),
    }
    path = root / PROFILE_FILENAME

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=root,
            prefix=f"{PROFILE_FILENAME}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            json.dump(payload, temporary, indent=2)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return path


def profile_sync_args(profile: InstallProfile) -> tuple[str, ...]:
    """Build the uv flags needed to reproduce ``profile`` exactly."""
    args: list[str] = []
    for extra in profile.extras:
        args.extend(("--extra", extra))
    for group in profile.groups:
        args.extend(("--group", group))
    return tuple(args)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    record = commands.add_parser("record", help="record the current uv features")
    record.add_argument("--repo-root", type=Path, default=Path.cwd())
    record.add_argument("--extra", action="append", default=[])
    record.add_argument("--group", action="append", default=[])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the private installer-profile command-line interface."""
    args = _parser().parse_args(argv)
    if args.command == "record":
        path = write_install_profile(
            args.repo_root,
            extras=args.extra,
            groups=args.group,
        )
        print(f"Recorded OpenJarvis install profile: {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through ``main``
    raise SystemExit(main())
