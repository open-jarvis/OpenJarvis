#!/usr/bin/env python3
"""One local wake event, then release the microphone before opening the HUD.

The desktop owns this process. stdin closure or a stop line cancels listening.
Only readiness/wake markers leave this process; audio is never retained.
"""
from __future__ import annotations

import signal
import sys
import threading
import time

SAMPLE_RATE = 16000
FRAME_LENGTH = 1280
THRESHOLD = 0.45


def listen(model, stream_factory, stop, clock=time.monotonic, emit=print):
    import numpy as np

    detected = False
    with stream_factory(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                        blocksize=FRAME_LENGTH) as stream:
        warm_until = clock() + 2.0
        ready = False
        while not stop.is_set():
            frame, overflow = stream.read(FRAME_LENGTH)
            if overflow:
                model.reset()
                continue
            scores = model.predict(np.frombuffer(frame, dtype=np.int16))
            if clock() < warm_until:
                continue
            if not ready:
                emit("ready", flush=True)
                ready = True
            # Only one stock model is loaded; versions may suffix its score key.
            score = max((float(value) for key, value in scores.items()
                         if key == "hey_jarvis" or key.startswith("hey_jarvis_")), default=0.0)
            if score >= THRESHOLD:
                detected = True
                break
    # The stream is closed before the desktop is asked to become visible.
    if detected and not stop.is_set():
        emit("wake", flush=True)


def main():
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    threading.Thread(target=lambda: (sys.stdin.readline(), stop.set()), daemon=True).start()
    try:
        import sounddevice as sd
        from openwakeword.model import Model
        model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        if not stop.is_set():
            listen(model, sd.RawInputStream, stop)
        return 0
    except Exception:
        # No paths, device details, credentials or audio-derived contents.
        print("unavailable", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
