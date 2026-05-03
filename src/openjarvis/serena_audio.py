"""Serena internal audio playback helpers.

Plays generated speech directly through the default Windows audio output
without opening Windows Media Player. Supports Enter-to-interrupt without
stealing the next live-session prompt input.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame
from rich.console import Console


def _enter_pressed() -> bool:
    """Return True if Enter was pressed.

    On Windows this uses msvcrt so we do not need a blocking input() thread.
    That prevents Serena's playback interrupt listener from stealing the next
    typed live-session message.
    """
    try:
        import msvcrt

        while msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                return True
        return False
    except Exception:
        return False


def play_audio_file(path: str | Path, *, interruptible: bool = True) -> bool:
    """Play an audio file through the default output.

    Returns True if playback completed normally.
    Returns False if interrupted by the user.
    """
    console = Console(stderr=True)
    audio_path = Path(path).resolve()

    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    interrupted = False

    try:
        pygame.mixer.init()
        pygame.mixer.music.load(str(audio_path))
        pygame.mixer.music.play()

        if interruptible:
            console.print("[dim]Press Enter to interrupt Serena speaking.[/dim]")

        while pygame.mixer.music.get_busy():
            if interruptible and _enter_pressed():
                interrupted = True
                pygame.mixer.music.stop()
                break
            time.sleep(0.05)

        try:
            pygame.mixer.music.unload()
        except Exception:
            pass

        pygame.mixer.quit()

        if interrupted:
            console.print("[yellow]Serena speech interrupted.[/yellow]")
            return False

        return True

    except Exception:
        try:
            pygame.mixer.quit()
        except Exception:
            pass
        raise
