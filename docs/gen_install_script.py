"""Publish the canonical install scripts into the docs site.

Serves the installers at::

    https://open-jarvis.github.io/OpenJarvis/install.sh   (Linux / macOS / WSL2)
    https://open-jarvis.github.io/OpenJarvis/install.ps1  (native Windows)

so users have an HTTPS-valid, project-controlled install URL that does not
depend on the externally-hosted ``openjarvis.ai`` domain — whose TLS config
broke and which the project does not control (issue #337).

Single source of truth: the scripts live under ``scripts/install/`` and
``deploy/windows/`` (also bundled into the wheel as ``_install_scripts/``).
This copies them verbatim into the built site on every ``mkdocs build``,
so the published copies can never drift from the canonical ones.
"""

from pathlib import Path

import mkdocs_gen_files

# (source path, published URL path)
_SCRIPTS = [
    (Path("scripts/install/install.sh"), "install.sh"),
    (Path("deploy/windows/install.ps1"), "install.ps1"),
]

for src, dest in _SCRIPTS:
    with mkdocs_gen_files.open(dest, "wb") as out:
        out.write(src.read_bytes())
