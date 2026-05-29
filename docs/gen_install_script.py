"""Publish the canonical install scripts into the docs site.

Serves the installers at ``https://open-jarvis.github.io/OpenJarvis/install.sh``
and ``…/install.ps1`` so users have HTTPS-valid, project-controlled install
URLs that do not depend on the externally-hosted ``openjarvis.ai`` domain —
whose TLS config broke and which the project does not control (issue #337).

Single source of truth: the scripts live at ``scripts/install/`` (also bundled
into the wheel as ``_install_scripts/``). This copies them verbatim into the
built site on every ``mkdocs build`` so the published copies can never drift.

``install.ps1`` is guidance-only — it points Windows users at WSL2 or the
desktop app rather than installing the native CLI (which is unsupported), so
PowerShell users who ran ``curl … | bash`` get the right path instead of
``bash: not recognized`` (#334).
"""

from pathlib import Path

import mkdocs_gen_files

for _name in ("install.sh", "install.ps1"):
    with mkdocs_gen_files.open(_name, "wb") as dst:
        dst.write(Path("scripts/install", _name).read_bytes())
