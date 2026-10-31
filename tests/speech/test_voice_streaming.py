"""Sentence-chunked and token-streamed speech for chat TTS.

These tests pin the streaming contract: the full reply text always comes
back to the caller, every word reaches synthesis exactly once and in
order, the first chunk is cut early (at a clause) for fast
time-to-first-audio, and TTS problems never interrupt the chat.
"""

from __future__ import annotations

import io
import threading
import time
import wave

import numpy as np
import pytest

from openjarvis.cli._voice_chat import (
    _split_sentences,
    _strip_markdown,
    speak_stream,
)
from openjarvis.speech.tts import TTSResult


def _wav(n_samples: int, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * n_samples)
    return buf.getvalue()


class _Console:
    def __init__(self) -> None:
        self.printed: list[str] = []

    def print(self, *args, **kwargs) -> None:
        self.printed.append("".join(str(a) for a in args))


class _Backend:
    """Whole-clip backend: one WAV per chunk, len(text) samples long."""

    backend_id = "fake"

    def __init__(self, fail_on: str | None = None) -> None:
        self.synthesized: list[str] = []
        self._fail_on = fail_on

    def synthesize(self, text: str, **kwargs) -> TTSResult:
        if self._fail_on is not None and self._fail_on in text:
            raise RuntimeError("synth failed")
        self.synthesized.append(text)
        return TTSResult(audio=_wav(len(text)), format="wav", sample_rate=24000)


class _StreamingBackend:
    """Frame-streaming backend: three frames per chunk, tagged by order."""

    backend_id = "fake-stream"

    def __init__(self) -> None:
        self.streamed: list[tuple[str, dict]] = []
        self._next = 0

    def synthesize(self, text: str, **kwargs) -> TTSResult:  # pragma: no cover
        raise AssertionError("streaming backends must not be synthesized whole")

    def synthesize_stream(self, text: str, **kwargs):
        self.streamed.append((text, kwargs))
        for _ in range(3):
            self._next += 1
            yield np.full(4, self._next, dtype=np.float32), 22050


class _Session:
    def __init__(self, backend) -> None:
        self._backend = backend

    def get_voice_preferences(self):
        return ("fake", "voice-1", 1.0)

    def get_tts_backend(self):
        return self._backend

    def voice_for_backend(self, backend, console=None):
        return ("voice-1", 1.0)


class _Recorder:
    """Stands in for ``voice_io.open_stream_player`` and its players."""

    def __init__(self, fail_writes: bool = False, write_delay: float = 0.0) -> None:
        self.opened = 0
        self.writes: list[tuple[np.ndarray, int]] = []
        self.closed = 0
        self.aborted = 0
        self.interrupted = 0
        self.fail_writes = fail_writes
        self.write_delay = write_delay

    def __call__(self):
        self.opened += 1
        return self

    def write(self, samples, sample_rate) -> None:
        if self.fail_writes:
            raise OSError("no audio device")
        if self.write_delay:
            time.sleep(self.write_delay)
        self.writes.append((np.asarray(samples), sample_rate))

    def close(self) -> None:
        self.closed += 1

    def abort(self) -> None:
        self.aborted += 1

    def interrupt(self) -> None:
        self.interrupted += 1


def _eventually(predicate, timeout: float = 3.0) -> bool:
    """The playback thread releases the device asynchronously after a cut."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


@pytest.fixture
def played(monkeypatch) -> _Recorder:
    recorder = _Recorder()
    monkeypatch.setattr("openjarvis.speech.voice_io.open_stream_player", recorder)
    return recorder


def _words(text: str) -> list[str]:
    return text.split()


# ---------------------------------------------------------------------------
# _split_sentences / _strip_markdown
# ---------------------------------------------------------------------------


def test_split_sentences_first_chunk_uses_lower_floor():
    text = "Bonjour Denis, ça va. " + "Ceci est une phrase plus longue. " * 4
    chunks = _split_sentences(text)
    assert chunks[0] == "Bonjour Denis, ça va."
    assert all(len(c) >= 60 for c in chunks[1:-1])
    assert _words(" ".join(chunks)) == _words(text)


def test_split_sentences_merges_short_fragments():
    chunks = _split_sentences("Oui. Non. Peut-être. D'accord.", first_chunk_chars=20)
    assert chunks == ["Oui. Non. Peut-être.", "D'accord."]


def test_split_sentences_empty_text():
    assert _split_sentences("   ") == []


def test_strip_markdown_removes_spoken_noise():
    md = "# Titre\n**gras** et `code` et [lien](http://x)\n- puce\n```py\nx=1\n```"
    stripped = _strip_markdown(md)
    for noise in ("#", "**", "`", "](", "http://x", "- puce", "x=1"):
        assert noise not in stripped
    for kept in ("Titre", "gras", "code", "lien", "puce"):
        assert kept in stripped


# ---------------------------------------------------------------------------
# speak_stream
# ---------------------------------------------------------------------------


def test_returns_full_text_and_speaks_every_word_in_order(played):
    deltas = ["Le ciel est bleu", ". La lumière ", "bleue est diffusée", " davantage."]
    backend = _Backend()
    text = speak_stream(iter(deltas), _Console(), _Session(backend))

    assert text == "".join(deltas)
    assert _words(" ".join(backend.synthesized)) == _words(text)
    assert [len(s) for s, _ in played.writes] == [len(c) for c in backend.synthesized]
    assert {rate for _, rate in played.writes} == {24000}
    assert (played.opened, played.closed, played.aborted) == (1, 1, 0)


def test_first_chunk_is_cut_at_a_clause_boundary(played):
    deltas = list(
        "Le ciel apparaît bleu, à cause de la diffusion Rayleigh qui touche "
        "surtout les courtes longueurs d'onde. Fin."
    )
    backend = _Backend()
    speak_stream(iter(deltas), _Console(), _Session(backend))
    assert backend.synthesized[0] == "Le ciel apparaît bleu,"


def test_markdown_is_stripped_before_synthesis(played):
    backend = _Backend()
    speak_stream(
        iter(["Voici **un point important** pour toi."]), _Console(), _Session(backend)
    )
    assert backend.synthesized == ["Voici un point important pour toi."]


def test_deltas_are_echoed_to_console(played):
    console = _Console()
    speak_stream(iter(["Salut", " Denis."]), console, _Session(_Backend()))
    assert "Salut" in console.printed and " Denis." in console.printed


def test_without_tts_backend_text_is_still_returned(played):
    text = speak_stream(iter(["Pas de voix", " ici."]), _Console(), _Session(None))
    assert text == "Pas de voix ici."
    assert played.opened == 0 and played.writes == []


def test_failed_chunk_is_skipped_and_the_rest_is_spoken(played):
    deltas = [
        "Première phrase assez longue pour partir. ",
        "Deuxième phrase BOOM, elle aussi assez longue pour partir toute seule. ",
        "Troisième phrase finale qui doit encore être prononcée.",
    ]
    backend = _Backend(fail_on="BOOM")
    text = speak_stream(iter(deltas), _Console(), _Session(backend))
    assert text == "".join(deltas)
    assert backend.synthesized[0].startswith("Première phrase")
    assert backend.synthesized[-1].startswith("Troisième phrase")
    assert not any("BOOM" in chunk for chunk in backend.synthesized)


def test_words_split_across_deltas_are_not_merged(played):
    # A short first sentence is held back below the chunk floor; the
    # whitespace ending one delta must survive into the next chunk.
    deltas = ["Il fait beau. La ", "lumière ", "bleue domine."]
    backend = _Backend()
    speak_stream(iter(deltas), _Console(), _Session(backend))
    spoken = " ".join(backend.synthesized)
    assert "lumière bleue" in spoken
    assert _words(spoken) == _words("".join(deltas))


def test_engine_error_propagates_without_hanging(played):
    def _deltas():
        yield "Début de réponse. "
        raise RuntimeError("engine down")

    with pytest.raises(RuntimeError, match="engine down"):
        speak_stream(_deltas(), _Console(), _Session(_Backend()))


def test_engine_error_lets_queued_speech_finish_first(played):
    def _deltas():
        yield "Une première phrase bien assez longue pour partir. "
        raise RuntimeError("engine down")

    with pytest.raises(RuntimeError, match="engine down"):
        speak_stream(_deltas(), _Console(), _Session(_StreamingBackend()))
    # Playback was drained (not aborted) before the error surfaced, so a
    # hands-free loop cannot reopen the mic over the speaker.
    assert len(played.writes) == 3
    assert (played.closed, played.aborted) == (1, 0)


def test_ctrl_c_while_waiting_for_speech_cuts_it(monkeypatch, played):
    monkeypatch.setattr(
        "openjarvis.cli._voice_chat._join_workers",
        lambda workers: (_ for _ in ()).throw(KeyboardInterrupt),
    )
    with pytest.raises(KeyboardInterrupt):
        speak_stream(iter(["Bonjour Denis."]), _Console(), _Session(_Backend()))
    assert played.interrupted == 1
    # The playback thread, which owns the device, releases it.
    assert _eventually(lambda: played.aborted == 1)
    assert played.closed == 0


class _LockedStreamingBackend:
    """Like PocketTTSBackend: the backend lock is held across the yields."""

    backend_id = "locked"

    def __init__(self, frames: int) -> None:
        self._lock = threading.Lock()
        self._frames = frames

    def synthesize_stream(self, text, **kwargs):
        with self._lock:
            for _ in range(self._frames):
                yield np.zeros(4, np.float32), 24000


def test_a_cut_long_reply_does_not_wedge_the_next_one(monkeypatch):
    # More frames than the audio queue holds, played slower than they are
    # produced: before the fix, the synth thread blocked forever on a full
    # queue while holding the backend lock, and the next reply hung.
    recorder = _Recorder(write_delay=0.002)
    monkeypatch.setattr("openjarvis.speech.voice_io.open_stream_player", recorder)
    backend = _LockedStreamingBackend(frames=700)

    def _cut_after_first_sentence():
        yield "Une première phrase bien assez longue pour partir. "
        time.sleep(0.2)
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        speak_stream(_cut_after_first_sentence(), _Console(), _Session(backend))

    backend._frames = 3
    result: list = []
    second = threading.Thread(
        target=lambda: result.append(
            speak_stream(iter(["Encore une réponse."]), _Console(), _Session(backend))
        ),
        daemon=True,
    )
    second.start()
    second.join(5)
    assert not second.is_alive(), "second reply hung after the cut"
    assert result == ["Encore une réponse."]


def test_streaming_backend_frames_are_played_in_order(played):
    deltas = ["Première phrase assez longue pour partir. ", "Puis la suite et la fin."]
    backend = _StreamingBackend()
    text = speak_stream(iter(deltas), _Console(), _Session(backend))

    assert text == "".join(deltas)
    assert [chunk for chunk, _ in backend.streamed] == [
        "Première phrase assez longue pour partir.",
        "Puis la suite et la fin.",
    ]
    # Voice settings reach the stream; the whole-clip output_format does not.
    assert backend.streamed[0][1] == {"voice_id": "voice-1", "speed": 1.0}
    assert [int(s[0]) for s, _ in played.writes] == [1, 2, 3, 4, 5, 6]
    assert {rate for _, rate in played.writes} == {22050}
    assert played.closed == 1


def test_interrupt_aborts_playback_and_propagates(played):
    def _deltas():
        yield "Une première phrase bien assez longue pour partir. "
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        speak_stream(_deltas(), _Console(), _Session(_StreamingBackend()))
    assert played.interrupted == 1
    assert _eventually(lambda: played.aborted == 1)


def test_broken_audio_device_does_not_block_the_chat(monkeypatch):
    recorder = _Recorder(fail_writes=True)
    monkeypatch.setattr("openjarvis.speech.voice_io.open_stream_player", recorder)
    deltas = ["Une phrase. " * 20]
    text = speak_stream(iter(deltas), _Console(), _Session(_StreamingBackend()))
    assert text == "".join(deltas)
    assert recorder.writes == []
