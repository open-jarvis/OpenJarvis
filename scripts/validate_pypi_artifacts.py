"""Report release archive sizes and reject unexpectedly large distributions."""

from __future__ import annotations

import argparse
from pathlib import Path

MAX_ARTIFACT_BYTES = 20 * 1024 * 1024


def validate_artifacts(directory: Path) -> None:
    """Require a wheel and sdist, each within the compressed upload budget."""
    wheels = sorted(directory.glob("*.whl"))
    sdists = sorted(directory.glob("*.tar.gz"))
    if not wheels or not sdists:
        raise ValueError("Expected at least one wheel and one .tar.gz source archive")

    oversized = []
    for artifact in [*wheels, *sdists]:
        size = artifact.stat().st_size
        print(f"{artifact.name}: {size:,} bytes ({size / 1024**2:.2f} MiB)")
        if size > MAX_ARTIFACT_BYTES:
            oversized.append(artifact.name)
    if oversized:
        raise ValueError(
            "Archive exceeds the 20 MiB upload budget: "
            + ", ".join(oversized)
            + ". Check for bundled build outputs or native binaries."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?", default=Path("dist"))
    args = parser.parse_args()
    try:
        validate_artifacts(args.directory)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Artifact validation failed: {error}\n")


if __name__ == "__main__":
    main()
