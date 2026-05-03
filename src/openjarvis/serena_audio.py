"""Serena internal audio playback helpers.

Plays generated speech directly through the default Windows audio output
without opening Windows Media Player. Supports Enter-to-interrupt.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

import pygame
from rich.console import Console


def play_audio_file(path: str | Path, *, interruptible: bool = True) -> bool:
    """Play an audio file through the default output.

    Returns True if playback completed normally.
    Returns False if interrupted by the user.
    """
    console = Console(stderr=True)
    audio_path = Path(path).resolve()

    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    interrupted = {"value": False}

    def _wait_for_enter() -> None:
        try:
            input()
            interrupted["value"] = True
            pygame.mixer.music.stop()
        except Exception:
            pass

    try:
        pygame.mixer.init()
        pygame.mixer.music.load(str(audio_path))
        pygame.mixer.music.play()

        if interruptible:
            console.print("[dim]Press Enter to interrupt Serena speaking.[/dim]")
            listener = threading.Thread(target=_wait_for_enter, daemon=True)
            listener.start()

        while pygame.mixer.music.get_busy():
            if interrupted["value"]:
                break
            time.sleep(0.1)

        pygame.mixer.music.unload()
        pygame.mixer.quit()

        if interrupted["value"]:
            console.print("[yellow]Serena speech interrupted.[/yellow]")
            return False

        return True

    except Exception:
        try:
            pygame.mixer.quit()
        except Exception:
            pass
        raise
