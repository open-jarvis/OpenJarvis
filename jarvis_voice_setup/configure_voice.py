"""Configure this OpenJarvis checkout to speak locally; backup before changing."""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

try:
    import tomlkit
except ImportError:
    raise SystemExit("Run this using uv run python (or the OpenJarvis .venv).")

HOME = Path.home() / ".openjarvis"
HOME.mkdir(exist_ok=True, parents=True)
CONFIG = HOME / "config.toml"
PERSONA = Path(__file__).resolve().parent / "jarvis_persona.txt"

if CONFIG.exists():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = HOME / f"config.toml.backup-{stamp}"
    shutil.copy2(CONFIG, backup)
    data = tomlkit.parse(CONFIG.read_text(encoding="utf-8"))
    print("Existing config backed up to", backup)
else:
    data = tomlkit.document()

if "speech" not in data:
    data["speech"] = tomlkit.table()
data["speech"]["tts_backend"] = "jarvis_local"
data["speech"]["voice_id"] = "jarvis-local"
data["speech"]["voice_speed"] = 1.0

if "agent" not in data:
    data["agent"] = tomlkit.table()
prior = str(data["agent"].get("system_prompt", "")).strip()
jarvis_prompt = PERSONA.read_text(encoding="utf-8").strip()
if not prior.startswith(jarvis_prompt):
    data["agent"]["system_prompt"] = jarvis_prompt + (
        "\n\nAdditional existing instructions:\n" + prior if prior else ""
    )
CONFIG.write_text(tomlkit.dumps(data), encoding="utf-8")
print("Jarvis voice: local-only bridge, fallback local Kokoro.")
print("OpenJarvis config:", CONFIG)
print("Your AI model and tools were not changed.")
