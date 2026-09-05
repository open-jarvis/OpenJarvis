"""VOICE CORE - local speech-to-text and interruptible text-to-speech.

STT: faster-whisper (OpenJarvis's bundled speech backend), fully local.
TTS: pyttsx3 (drives the OS's native voice - SAPI5 on Windows) synthesizing
to a WAV file, then played back via sounddevice so playback can be
interrupted safely. Playing pyttsx3's audio directly (engine.say +
runAndWait) cannot be stopped from another thread: SAPI5 is a COM object
bound to the thread that created it, and calling engine.stop() from a
different thread deadlocks on Windows rather than interrupting playback.
sounddevice's play/stop are plain PortAudio calls with no such restriction.

No wake-word listening yet: this is push-to-talk (record for a fixed
duration on button press) rather than always-on.
"""

from __future__ import annotations

import io
import os
import tempfile
import threading

import pyttsx3
import sounddevice as sd
import soundfile as sf

from openjarvis.speech.faster_whisper import FasterWhisperBackend

SAMPLE_RATE = 16000


class VoiceCore:
    """Push-to-talk STT + interruptible TTS."""

    def __init__(self, whisper_model_size: str = "base"):
        self._stt = FasterWhisperBackend(model_size=whisper_model_size, device="auto")
        self._tts_lock = threading.Lock()
        self._speaking = False
        # Bumped on every interruption. A speak() call captures the token it
        # started with and refuses to begin playback if the token has since
        # changed - this catches interruptions that land while pyttsx3 is
        # still synthesizing, before there's any audio for sd.stop() to stop.
        self._speak_token = 0

    # -- speech-to-text ----------------------------------------------------
    def record_and_transcribe(self, seconds: float = 5.0) -> str:
        """Block for `seconds`, recording from the default mic, then transcribe."""
        recording = sd.rec(
            int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="float32"
        )
        sd.wait()

        buf = io.BytesIO()
        sf.write(buf, recording, SAMPLE_RATE, format="WAV")
        result = self._stt.transcribe(buf.getvalue(), format="wav")
        return result.text

    # -- text-to-speech ------------------------------------------------------
    def speak(self, text: str) -> None:
        """Synthesize and play `text` aloud. Blocks the calling thread until
        playback finishes or stop_speaking() is called from another thread."""
        if not text:
            return
        my_token = self._speak_token
        with self._tts_lock:
            if my_token != self._speak_token:
                # Interrupted while waiting for a prior speak() to release
                # the lock (e.g. still finishing its synthesis) - never
                # start playback for a turn that's already been superseded.
                return
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp.close()
            try:
                engine = pyttsx3.init()
                engine.save_to_file(text, tmp.name)
                engine.runAndWait()

                if my_token != self._speak_token:
                    # Interrupted mid-synthesis - discard, don't play.
                    return

                data, sample_rate = sf.read(tmp.name)
                self._speaking = True
                try:
                    sd.play(data, sample_rate)
                    sd.wait()
                finally:
                    self._speaking = False
            finally:
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass

    def stop_speaking(self) -> None:
        """Interrupt any speech currently playing or being synthesized.
        Safe to call from any thread."""
        self._speak_token += 1
        sd.stop()
        self._speaking = False

    @property
    def is_speaking(self) -> bool:
        return self._speaking
