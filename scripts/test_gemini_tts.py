"""Generate a quick Gemini TTS voice sample."""

from __future__ import annotations

import argparse
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openjarvis.speech.gemini_tts import GeminiTTSBackend  # noqa: E402
from openjarvis.speech.text_normalizer import normalize_for_tts  # noqa: E402


def _play(path: Path) -> None:
    if platform.system() == "Windows":
        import winsound

        winsound.PlaySound(str(path), winsound.SND_FILENAME)
        return

    raise RuntimeError("--play is currently implemented only for Windows")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--text",
        default=(
            "Guten Abend, Andre. System bereit. "
            "Kalender, Mail und Sprachsteuerung sind als naechstes dran."
        ),
    )
    parser.add_argument("--voice", default="Orus")
    parser.add_argument("--speed", type=float, default=0.95)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("voice_tests") / "gemini_orus_jarvis_test.wav",
    )
    parser.add_argument("--play", action="store_true")
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    backend = GeminiTTSBackend()
    result = backend.synthesize(
        normalize_for_tts(args.text),
        voice_id=args.voice,
        speed=args.speed,
    )
    result.save(args.out)
    print(args.out.resolve())

    if args.play:
        _play(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
