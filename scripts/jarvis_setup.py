"""Deja la configuración de Jarvis lista: cerebro en Gemini, voz y personalidad.

Lo ejecuta ``scripts/jarvis-setup.ps1`` dentro del entorno de OpenJarvis:

    uv run python scripts/jarvis_setup.py --model gemini-3.1-flash-lite-preview

Es idempotente: ejecutarlo de nuevo no duplica nada. No toca la clave de
Gemini; esa la guarda el instalador en las variables del usuario.
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

import tomlkit

REPO_ROOT = Path(__file__).resolve().parents[1]
PERSONA_NAME = "jarvis"
PERSONA_SOURCE = REPO_ROOT / "configs" / "jarvis" / "personas" / PERSONA_NAME

# Herramientas que alimentan las tarjetas del HUD; se suman a las ya activas.
EXTRA_TOOLS = ["web_search", "get_weather", "calculator", "think", "memory_store", "memory_search"]


def jarvis_settings(model: str) -> list[tuple[str, str, str | int]]:
    """Ajustes de Jarvis: sección, clave y valor."""
    return [
        # Cerebro: Gemini por internet (plan gratuito de Google AI Studio).
        ("engine", "default", "cloud"),
        ("intelligence", "default_model", model),
        # Oído: Whisper "base" es el más rápido en CPU; el idioma fijo evita errores.
        ("speech", "language", "es"),
        ("speech", "model", "base"),
        ("speech", "compute_type", "int8"),
        ("security", "profile", "personal"),
        ("memory_files", "persona_name", PERSONA_NAME),
        # Si algún día vuelve al modelo local, espera a que Ollama arranque.
        ("server", "engine_wait_seconds", 180),
    ]


def update_config(config_path: Path, model: str) -> list[str]:
    """Aplica los ajustes conservando el resto del archivo y sus comentarios."""
    document = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    changes = []
    for section, key, value in jarvis_settings(model):
        table = document.setdefault(section, tomlkit.table())
        if table.get(key) != value:
            table[key] = value
            changes.append(f"{section}.{key} = {value}")

    tools = document.setdefault("tools", tomlkit.table())
    enabled = list(tools.get("enabled", []))
    missing = [tool for tool in EXTRA_TOOLS if tool not in enabled]
    if missing:
        tools["enabled"] = enabled + missing
        changes.append(f"tools.enabled += {', '.join(missing)}")

    if changes:
        config_path.write_text(tomlkit.dumps(document), encoding="utf-8")
    return changes


def install_persona(config_dir: Path) -> list[str]:
    """Copia la personalidad sin pisar archivos que el usuario ya haya editado."""
    target = config_dir / "personas" / PERSONA_NAME
    target.mkdir(parents=True, exist_ok=True)
    copied = []
    for source in sorted(PERSONA_SOURCE.glob("*.md")):
        destination = target / source.name
        if not destination.exists():
            shutil.copyfile(source, destination)
            copied.append(source.name)
    return copied


def download_transcription_model(size: str) -> None:
    """Descarga Whisper antes de arrancar, para que la primera orden no espere."""
    # La descarga acelerada reserva bloques grandes de memoria; la clásica no.
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    from faster_whisper import download_model

    download_model(size)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Modelo Gemini del cerebro")
    parser.add_argument("--skip-download", action="store_true", help="No descargar Whisper")
    args = parser.parse_args()

    from openjarvis.core.config import get_config_dir, get_config_path

    config_path = Path(get_config_path())
    if not config_path.is_file():
        raise SystemExit(f"No existe {config_path}. Ejecute primero: uv run jarvis init")

    changes = update_config(config_path, args.model)
    print(f"  Configuración: {'; '.join(changes) if changes else 'ya estaba al día'}")
    copied = install_persona(Path(get_config_dir()))
    print(f"  Personalidad: {', '.join(copied) if copied else 'ya estaba instalada'}")
    if not args.skip_download:
        print("  Descargando el modelo de transcripción (solo la primera vez)...")
        download_transcription_model("base")
        print("  Modelo de transcripción listo.")


if __name__ == "__main__":
    main()
