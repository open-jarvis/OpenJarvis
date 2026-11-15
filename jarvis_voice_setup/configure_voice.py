"""Configure the *separate* OpenJarvis installation for local voice and AI.

Always backs up existing config. Honors OPENJARVIS_HOME / OPENJARVIS_CONFIG,
so the user's older Jarvis application is never silently reconfigured.
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

import tomlkit

root = Path(os.environ.get("OPENJARVIS_HOME") or
            (Path.home() / ".openjarvis")).expanduser().resolve()
path_setting = os.environ.get("OPENJARVIS_CONFIG")
config = (Path(path_setting).expanduser().resolve() if path_setting
          else root / "config.toml")
config.parent.mkdir(exist_ok=True, parents=True)

persona = (Path(__file__).resolve().parent / "jarvis_persona.txt").read_text(
    encoding="utf-8"
).strip()

if config.is_file():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = config.with_name(f"config.backup-{stamp}.toml")
    shutil.copy2(config, backup)
    doc = tomlkit.parse(config.read_text(encoding="utf-8"))
    print("Existing settings backed up to:", backup)
else:
    doc = tomlkit.document()

if "speech" not in doc:
    doc["speech"] = tomlkit.table()
doc["speech"]["tts_backend"] = "jarvis_local"
doc["speech"]["voice_id"] = "jarvis-local"
doc["speech"]["voice_speed"] = 1.0
doc["speech"]["backend"] = "faster-whisper"
doc["speech"]["model"] = "base"
doc["speech"]["device"] = "cpu"
doc["speech"]["compute_type"] = "int8"

if "engine" not in doc:
    doc["engine"] = tomlkit.table()
doc["engine"]["default"] = "ollama"

if "agent" not in doc:
    doc["agent"] = tomlkit.table()
prior = str(doc["agent"].get("system_prompt", "")).strip()
if not prior.startswith(persona):
    doc["agent"]["system_prompt"] = persona + (
        "\n\nAdditional existing instructions:\n" + prior if prior else ""
    )

config.write_text(tomlkit.dumps(doc), encoding="utf-8")
print("Local Jarvis config:", config)
print("AI: Ollama | Speech recognition: local Whisper")
print("Voice: Jarvis-local (Piper; optional local Chatterbox)")
print("No paid cloud providers are configured by this script.")
