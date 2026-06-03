"""Local TTS helpers for Friday app mode."""

from __future__ import annotations

import base64
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import wave
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Callable

SAY_PATH = Path("/usr/bin/say")
AFPLAY_PATH = Path("/usr/bin/afplay")
DEFAULT_TTS_VOICE = "Yuna"
DEFAULT_TTS_RATE = 165
DEFAULT_TTS_MAX_CHARS = 400
DEFAULT_TTS_PAUSE_MS = 250
MAX_TTS_CHARS = 1200
CLOUD_TTS_SETUP_MESSAGE = "클라우드 TTS 설정이 필요합니다. 로컬 음성으로 대체합니다."
PIPER_TTS_SETUP_MESSAGE = "Piper TTS 설정이 필요합니다. 로컬 음성으로 대체합니다."
EDGE_TTS_SETUP_MESSAGE = "edge-tts 설치가 필요합니다. 로컬 음성으로 대체합니다."
GEMINI_TTS_SETUP_MESSAGE = (
    "Gemini TTS API 키 설정이 필요합니다. 로컬 음성으로 대체합니다."
)

_CURRENT_SAY_PROCESS: subprocess.Popen | None = None
_CURRENT_SAY_TOKEN = 0

_EMOJI_RE = re.compile(
    "["
    "\U0001f1e6-\U0001f1ff"
    "\U0001f300-\U0001f5ff"
    "\U0001f600-\U0001f64f"
    "\U0001f680-\U0001f6ff"
    "\U0001f700-\U0001f77f"
    "\U0001f780-\U0001f7ff"
    "\U0001f800-\U0001f8ff"
    "\U0001f900-\U0001f9ff"
    "\U0001fa00-\U0001fa6f"
    "\U0001fa70-\U0001faff"
    "\u2600-\u27bf"
    "]+"
)
_EMOJI_MODIFIER_RE = re.compile(r"[\ufe0e\ufe0f\u200d\u20e3]")
_TEXT_EMOTICON_RE = re.compile(
    r"(?:(?<=\s)|^)(?:[:;=8xX][-^']?[)(DPpOo/\\]|<3|[ㅋㅎㅠㅜ]{2,})(?=\s|$)"
)
_GEMINI_VOICES = {
    "zephyr",
    "puck",
    "charon",
    "kore",
    "fenrir",
    "leda",
    "orus",
    "aoede",
    "callirrhoe",
    "autonoe",
    "enceladus",
    "iapetus",
    "umbriel",
    "algieba",
    "despina",
    "erinome",
    "algenib",
    "rasalgethi",
    "laomedeia",
    "achernar",
    "alnilam",
    "schedar",
    "gacrux",
    "pulcherrima",
    "achird",
    "zubenelgenubi",
    "vindemiatrix",
    "sadachbia",
    "sadaltager",
    "sulafat",
}


@dataclass(slots=True)
class SpeakResult:
    ok: bool
    message: str = ""
    engine: str = "macos_say"
    text: str = ""
    chunks: list[str] | None = None


def _strip_emoji(text: str) -> str:
    stripped = _EMOJI_RE.sub(" ", text)
    stripped = _EMOJI_MODIFIER_RE.sub("", stripped)
    return _TEXT_EMOTICON_RE.sub(" ", stripped)


def _wav_bytes_from_pcm(
    pcm: bytes,
    *,
    channels: int = 1,
    rate: int = 24000,
    sample_width: int = 2,
) -> bytes:
    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(sample_width)
            wav.setframerate(rate)
            wav.writeframes(pcm)
        return buffer.getvalue()


def _select_gemini_voice(requested: str, fallback: str = "Sulafat") -> str:
    requested_clean = (requested or "").strip()
    if requested_clean.lower() in _GEMINI_VOICES:
        return requested_clean
    fallback_clean = (fallback or "Sulafat").strip()
    if fallback_clean.lower() in _GEMINI_VOICES:
        return fallback_clean
    return "Sulafat"


def _naturalize_weather_text(text: str) -> str:
    """Turn dense weather strings into shorter Korean spoken sentences."""
    weather_match = re.search(
        r"현재\s+(.+?)은\s+(.+?),\s*기온\s*([+-]?\d+(?:\.\d+)?)\s*°?C"
        r"(?:\(체감\s*([+-]?\d+(?:\.\d+)?)\s*°?C\))?"
        r".*?오늘\s+예상\s+기온은\s*([+-]?\d+(?:\.\d+)?)\s*°?C\s*[~～-]\s*([+-]?\d+(?:\.\d+)?)\s*°?C",
        text,
    )
    if not weather_match:
        return text

    city, condition, temp, feels_like, low, high = weather_match.groups()
    condition = condition.strip()
    condition = condition.replace("부분적으로 흐림", "조금 흐려요")
    condition = condition.replace("흐림", "흐려요")
    condition = condition.replace("맑음", "맑아요")
    condition = condition.replace("비", "비가 와요")
    if not condition.endswith(("요", "다")):
        condition = f"{condition}이에요"

    sentences = [
        f"{city.strip()}은 지금 {condition}.",
        f"기온은 약 {round(float(temp))}도예요.",
    ]
    if feels_like:
        sentences.append(f"체감 온도는 {round(float(feels_like))}도 정도예요.")
    sentences.append(
        f"오늘은 {round(float(low))}도에서 {round(float(high))}도 사이로 예상돼요."
    )
    return " ".join(sentences)


def _naturalize_general_speech(text: str) -> str:
    """Make concise assistant text sound less like written markdown."""
    replacements = {
        "확인했습니다": "확인했어요",
        "알겠습니다": "알겠어요",
        "완료했습니다": "완료했어요",
        "진행하겠습니다": "진행할게요",
        "도와드리겠습니다": "도와드릴게요",
        "말씀해주세요": "말씀해 주세요",
        "다음과 같습니다": "이렇게 정리했어요",
        "아래와 같습니다": "이렇게 정리했어요",
        "요약하면": "짧게 말하면",
        "참고로": "참고로요",
        "가능합니다": "가능해요",
        "필요합니다": "필요해요",
        "추천합니다": "추천해요",
        "macOS": "맥 오에스",
        "TTS": "티티에스",
        "STT": "에스티티",
        "API": "에이피아이",
        "URL": "유알엘",
        "Chrome": "크롬",
        "Safari": "사파리",
    }
    naturalized = text
    for old, new in replacements.items():
        naturalized = naturalized.replace(old, new)

    naturalized = re.sub(r"요\s*:\s*", "요. ", naturalized)
    naturalized = re.sub(r"\s*:\s*", "은 ", naturalized)
    naturalized = re.sub(r"\s*[;|]\s*", ". ", naturalized)
    naturalized = re.sub(r"([가-힣])입니다([.!?]?)", r"\1이에요\2", naturalized)
    naturalized = re.sub(r"([가-힣])합니다([.!?]?)", r"\1해요\2", naturalized)
    naturalized = re.sub(r"([가-힣])됩니다([.!?]?)", r"\1돼요\2", naturalized)
    naturalized = naturalized.replace("시이에요", "시예요")
    naturalized = re.sub(r"([가-힣])세요\.$", r"\1세요.", naturalized)
    naturalized = re.sub(r"\s+", " ", naturalized).strip()
    return naturalized


def cleanup_tts_text(
    text: str,
    *,
    max_chars: int = DEFAULT_TTS_MAX_CHARS,
    naturalize: bool = True,
) -> str:
    """Make assistant text more natural and safer to read aloud."""
    limit = max(1, min(int(max_chars or DEFAULT_TTS_MAX_CHARS), MAX_TTS_CHARS))
    cleaned = text or ""
    if re.search(
        r"(traceback|stack trace|http\s+\d{3}|exception|error:)",
        cleaned,
        re.I,
    ):
        return ""
    cleaned = re.sub(r"```[\s\S]*?```", " ", cleaned)
    cleaned = re.sub(r"`[^`]+`", " ", cleaned)
    cleaned = re.sub(r"https?://\S+", " ", cleaned)
    cleaned = re.sub(r"^\s*\|.*\|\s*$", " ", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(
        r"^\s*:?-{3,}:?(?:\s*\|\s*:?-{3,}:?)+\s*$",
        " ",
        cleaned,
        flags=re.MULTILINE,
    )
    cleaned = re.sub(r"^\s*[-*•]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^\s*\d+[.)]\s+", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"#{1,6}\s*", "", cleaned)
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
    cleaned = re.sub(
        r"\b(?:ollama|tokens?|token/sec|cost comparison|latency|telemetry|"
        r"debug|log|stack trace|http\s+\d{3})\b",
        " ",
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(r"Traceback \(most recent call last\):[\s\S]*", " ", cleaned)
    cleaned = _strip_emoji(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if naturalize:
        naturalized = _naturalize_weather_text(cleaned)
        if naturalized != cleaned:
            return naturalized[:limit].strip()
    replacements = {
        "->": "에서",
        "=>": "결과는",
        "&": "그리고",
        "%": "퍼센트",
        "/": " 또는 ",
        "=": " 는 ",
        "°C": "도",
        "km/h": "킬로미터 매 시",
        "~": "에서",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    if naturalize:
        cleaned = _naturalize_general_speech(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:limit].strip()


def split_tts_chunks(text: str, *, max_chars: int = 120) -> list[str]:
    """Split Korean text into short sentence chunks."""
    cleaned = text.strip()
    if not cleaned:
        return []
    chunks: list[str] = []
    sentence_parts = re.split(r"(?<=[.!?。！？요다니다죠습니다])\s+", cleaned)
    for sentence in sentence_parts:
        sentence = sentence.strip()
        if not sentence:
            continue
        while len(sentence) > max_chars:
            split_at = sentence.rfind(" ", 0, max_chars)
            if split_at <= 0:
                split_at = max_chars
            chunks.append(sentence[:split_at].strip())
            sentence = sentence[split_at:].strip()
        if sentence:
            chunks.append(sentence)
    return chunks


def _cleanup_temp_audio(path: str, proc: subprocess.Popen | None) -> None:
    if proc is not None:
        wait = getattr(proc, "wait", None)
        if callable(wait):
            wait()
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def play_audio_bytes(
    audio: bytes,
    *,
    suffix: str = ".mp3",
    afplay_path: Path = AFPLAY_PATH,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> SpeakResult:
    """Play generated audio locally with macOS afplay."""
    if not audio:
        return SpeakResult(ok=False, message="읽을 음성 응답이 없습니다.")
    if not afplay_path.exists():
        return SpeakResult(
            ok=False,
            message=(
                "로컬 오디오 재생기를 찾을 수 없습니다. "
                "macOS afplay 설정을 확인해주세요."
            ),
        )
    try:
        with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(audio)
            audio_path = tmp.name
        proc = popen([str(afplay_path), audio_path])
        thread = threading.Thread(
            target=_cleanup_temp_audio,
            args=(audio_path, proc),
            daemon=True,
        )
        thread.start()
    except FileNotFoundError:
        return SpeakResult(
            ok=False,
            message=(
                "로컬 오디오 재생기를 찾을 수 없습니다. "
                "macOS afplay 설정을 확인해주세요."
            ),
        )
    except OSError as exc:
        return SpeakResult(ok=False, message=f"로컬 오디오 재생에 실패했습니다: {exc}")
    return SpeakResult(ok=True, message="음성 응답 중...")


def _edge_rate_from_wpm(rate: str | int) -> str:
    try:
        numeric = int(rate)
    except (TypeError, ValueError):
        numeric = DEFAULT_TTS_RATE
    percent = max(
        -50,
        min(round(((numeric - DEFAULT_TTS_RATE) / DEFAULT_TTS_RATE) * 100), 50),
    )
    return f"{percent:+d}%"


def stop_macos_say() -> None:
    global _CURRENT_SAY_PROCESS, _CURRENT_SAY_TOKEN
    _CURRENT_SAY_TOKEN += 1
    proc = _CURRENT_SAY_PROCESS
    _CURRENT_SAY_PROCESS = None
    if proc and proc.poll() is None:
        proc.terminate()


def _speak_remaining_chunks(
    chunks: list[str],
    command_prefix: list[str],
    *,
    initial_proc: subprocess.Popen | None,
    pause_ms: int,
    token: int,
    popen: Callable[..., subprocess.Popen],
) -> None:
    global _CURRENT_SAY_PROCESS
    if initial_proc is not None:
        wait = getattr(initial_proc, "wait", None)
        if callable(wait):
            wait()
    for chunk in chunks:
        if token != _CURRENT_SAY_TOKEN:
            return
        if pause_ms > 0:
            time.sleep(pause_ms / 1000)
        if token != _CURRENT_SAY_TOKEN:
            return
        try:
            proc = popen([*command_prefix, chunk])
            _CURRENT_SAY_PROCESS = proc
            wait = getattr(proc, "wait", None)
            if callable(wait):
                wait()
        except (FileNotFoundError, OSError):
            return


def speak_macos_say(
    text: str,
    *,
    voice: str = DEFAULT_TTS_VOICE,
    rate: int = DEFAULT_TTS_RATE,
    max_chars: int = DEFAULT_TTS_MAX_CHARS,
    pause_ms: int = DEFAULT_TTS_PAUSE_MS,
    naturalize: bool = True,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> SpeakResult:
    """Speak text with macOS /usr/bin/say using safe argv construction."""
    if not SAY_PATH.exists():
        return SpeakResult(
            ok=False,
            message="TTS 음성을 찾을 수 없습니다. macOS 음성 설정을 확인해주세요.",
        )
    cleaned = cleanup_tts_text(text, max_chars=max_chars, naturalize=naturalize)
    if not cleaned:
        return SpeakResult(ok=False, message="읽을 음성 응답이 없습니다.")
    chunks = split_tts_chunks(cleaned)
    spoken_text = " ".join(chunks).strip()
    if not spoken_text:
        return SpeakResult(ok=False, message="읽을 음성 응답이 없습니다.")

    stop_macos_say()
    safe_rate = max(80, min(int(rate or DEFAULT_TTS_RATE), 320))
    safe_pause_ms = max(0, min(int(pause_ms or 0), 2000))
    safe_voice = (voice or DEFAULT_TTS_VOICE).strip() or DEFAULT_TTS_VOICE
    command_prefix = [str(SAY_PATH), "-v", safe_voice, "-r", str(safe_rate)]
    try:
        global _CURRENT_SAY_PROCESS, _CURRENT_SAY_TOKEN
        _CURRENT_SAY_TOKEN += 1
        token = _CURRENT_SAY_TOKEN
        first_proc = popen([*command_prefix, chunks[0]])
        _CURRENT_SAY_PROCESS = first_proc
        if len(chunks) > 1:
            thread = threading.Thread(
                target=_speak_remaining_chunks,
                args=(chunks[1:], command_prefix),
                kwargs={
                    "initial_proc": first_proc,
                    "pause_ms": safe_pause_ms,
                    "token": token,
                    "popen": popen,
                },
                daemon=True,
            )
            thread.start()
    except FileNotFoundError:
        return SpeakResult(
            ok=False,
            message="TTS 음성을 찾을 수 없습니다. macOS 음성 설정을 확인해주세요.",
        )
    except OSError as exc:
        return SpeakResult(ok=False, message=f"로컬 TTS 실행에 실패했습니다: {exc}")
    return SpeakResult(
        ok=True,
        message="음성 응답 중...",
        text=spoken_text,
        chunks=chunks,
    )


def speak_elevenlabs_tts(
    text: str,
    *,
    voice_id: str = "",
    model: str = "eleven_v3",
    max_chars: int = DEFAULT_TTS_MAX_CHARS,
    naturalize: bool = True,
    env: dict[str, str] | None = None,
    urlopen: Callable[..., object] = urllib.request.urlopen,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> SpeakResult:
    """Generate ElevenLabs audio and play it locally."""
    env_map = env if env is not None else os.environ
    key = env_map.get("ELEVENLABS_API_KEY", "").strip()
    configured_voice = "" if voice_id == DEFAULT_TTS_VOICE else voice_id
    safe_voice_id = (configured_voice or env_map.get("ELEVENLABS_VOICE_ID", "")).strip()
    if not key or not safe_voice_id:
        return SpeakResult(
            ok=False,
            engine="elevenlabs",
            message=CLOUD_TTS_SETUP_MESSAGE,
        )

    cleaned = cleanup_tts_text(text, max_chars=max_chars, naturalize=naturalize)
    if not cleaned:
        return SpeakResult(
            ok=False,
            engine="elevenlabs",
            message="읽을 음성 응답이 없습니다.",
        )

    payload = json.dumps(
        {
            "text": cleaned,
            "model_id": (model or "eleven_v3").strip() or "eleven_v3",
            "voice_settings": {
                "stability": 0.38,
                "similarity_boost": 0.82,
                "style": 0.45,
                "use_speaker_boost": True,
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{safe_voice_id}",
        data=payload,
        headers={
            "xi-api-key": key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            audio = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return SpeakResult(
            ok=False,
            engine="elevenlabs",
            message=f"ElevenLabs TTS 실행에 실패했습니다: {exc}",
        )

    result = play_audio_bytes(audio, suffix=".mp3", popen=popen)
    result.engine = "elevenlabs"
    result.text = cleaned
    result.chunks = split_tts_chunks(cleaned)
    return result


def speak_gemini_tts(
    text: str,
    *,
    model: str = "gemini-2.5-flash-preview-tts",
    voice: str = "Sulafat",
    api_key: str = "",
    max_chars: int = DEFAULT_TTS_MAX_CHARS,
    naturalize: bool = True,
    env: dict[str, str] | None = None,
    urlopen: Callable[..., object] = urllib.request.urlopen,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> SpeakResult:
    """Generate Gemini TTS PCM audio and play it locally as a WAV file."""
    env_map = env if env is not None else os.environ
    key = (
        (api_key or "").strip()
        or env_map.get("GEMINI_API_KEY", "").strip()
        or env_map.get("GOOGLE_API_KEY", "").strip()
    )
    if not key:
        return SpeakResult(
            ok=False,
            engine="gemini_tts",
            message=GEMINI_TTS_SETUP_MESSAGE,
        )

    cleaned = cleanup_tts_text(text, max_chars=max_chars, naturalize=naturalize)
    if not cleaned:
        return SpeakResult(
            ok=False,
            engine="gemini_tts",
            message="읽을 음성 응답이 없습니다.",
        )

    prompt = (
        "한국어 개인 비서처럼 자연스럽고 따뜻하게 말해 주세요. "
        "문서를 낭독하듯 읽지 말고, 짧은 대화처럼 "
        "편안한 속도와 억양으로 말해 주세요.\n\n"
        f"{cleaned}"
    )
    model_id = (model or "gemini-2.5-flash-preview-tts").strip()
    safe_voice = _select_gemini_voice(voice)
    payload = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {
                            "voiceName": safe_voice,
                        }
                    }
                },
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model_id}:generateContent?key={key}"
        ),
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (json.JSONDecodeError, urllib.error.URLError, TimeoutError, OSError) as exc:
        return SpeakResult(
            ok=False,
            engine="gemini_tts",
            message=f"Gemini TTS 실행에 실패했습니다: {exc}",
        )

    try:
        inline_data = body["candidates"][0]["content"]["parts"][0]["inlineData"]
        pcm = base64.b64decode(inline_data["data"])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        return SpeakResult(
            ok=False,
            engine="gemini_tts",
            message=f"Gemini TTS 응답에서 오디오를 찾지 못했습니다: {exc}",
        )

    result = play_audio_bytes(
        _wav_bytes_from_pcm(pcm),
        suffix=".wav",
        popen=popen,
    )
    result.engine = "gemini_tts"
    result.text = cleaned
    result.chunks = split_tts_chunks(cleaned)
    return result


def speak_edge_tts(
    text: str,
    *,
    voice: str = "ko-KR-SunHiNeural",
    rate: str | int = DEFAULT_TTS_RATE,
    max_chars: int = DEFAULT_TTS_MAX_CHARS,
    naturalize: bool = True,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> SpeakResult:
    """Generate speech with the optional edge-tts package and play it locally."""
    cleaned = cleanup_tts_text(text, max_chars=max_chars, naturalize=naturalize)
    if not cleaned:
        return SpeakResult(
            ok=False,
            engine="edge_tts",
            message="읽을 음성 응답이 없습니다.",
        )

    safe_voice = (voice or "ko-KR-SunHiNeural").strip() or "ko-KR-SunHiNeural"
    tmp_path = ""
    try:
        with NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
            tmp_path = tmp.name
        run(
            [
                sys.executable,
                "-m",
                "edge_tts",
                "--voice",
                safe_voice,
                "--rate",
                _edge_rate_from_wpm(rate),
                "--text",
                cleaned,
                "--write-media",
                tmp_path,
            ],
            capture_output=True,
            text=True,
            timeout=45,
            check=True,
        )
        audio = Path(tmp_path).read_bytes()
    except FileNotFoundError:
        return SpeakResult(ok=False, engine="edge_tts", message=EDGE_TTS_SETUP_MESSAGE)
    except (subprocess.SubprocessError, OSError) as exc:
        return SpeakResult(
            ok=False,
            engine="edge_tts",
            message=f"edge-tts 실행에 실패했습니다: {exc}",
        )
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass

    result = play_audio_bytes(audio, suffix=".mp3", popen=popen)
    result.engine = "edge_tts"
    result.text = cleaned
    result.chunks = split_tts_chunks(cleaned)
    return result


def speak_piper_tts(
    text: str,
    *,
    piper_path: str = "",
    model_path: str = "",
    max_chars: int = DEFAULT_TTS_MAX_CHARS,
    naturalize: bool = True,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> SpeakResult:
    """Generate speech with local Piper and play it locally."""
    command_path = Path(piper_path).expanduser() if piper_path else Path("")
    voice_model = Path(model_path).expanduser() if model_path else Path("")
    if not command_path.is_file() or not voice_model.is_file():
        return SpeakResult(ok=False, engine="piper", message=PIPER_TTS_SETUP_MESSAGE)

    cleaned = cleanup_tts_text(text, max_chars=max_chars, naturalize=naturalize)
    if not cleaned:
        return SpeakResult(
            ok=False,
            engine="piper",
            message="읽을 음성 응답이 없습니다.",
        )

    try:
        with NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            audio_path = tmp.name
        run(
            [
                str(command_path),
                "--model",
                str(voice_model),
                "--output_file",
                audio_path,
            ],
            input=cleaned,
            text=True,
            capture_output=True,
            timeout=30,
            check=True,
        )
    except FileNotFoundError:
        return SpeakResult(ok=False, engine="piper", message=PIPER_TTS_SETUP_MESSAGE)
    except (subprocess.SubprocessError, OSError) as exc:
        return SpeakResult(
            ok=False,
            engine="piper",
            message=f"Piper TTS 실행에 실패했습니다: {exc}",
        )

    try:
        audio = Path(audio_path).read_bytes()
    except OSError as exc:
        return SpeakResult(
            ok=False,
            engine="piper",
            message=f"Piper 음성 파일을 읽지 못했습니다: {exc}",
        )
    finally:
        try:
            Path(audio_path).unlink(missing_ok=True)
        except OSError:
            pass

    result = play_audio_bytes(audio, suffix=".wav", popen=popen)
    result.engine = "piper"
    result.text = cleaned
    result.chunks = split_tts_chunks(cleaned)
    return result


def speak_with_provider(
    text: str,
    *,
    mode: str = "macos_say",
    fallback_mode: str = "macos_say",
    voice: str = DEFAULT_TTS_VOICE,
    rate: str | int = DEFAULT_TTS_RATE,
    max_chars: int = DEFAULT_TTS_MAX_CHARS,
    pause_ms: int = DEFAULT_TTS_PAUSE_MS,
    naturalize: bool = True,
    enabled: bool = True,
    elevenlabs_voice_id: str = "",
    elevenlabs_model: str = "eleven_v3",
    gemini_model: str = "gemini-2.5-flash-preview-tts",
    gemini_voice: str = "Sulafat",
    gemini_api_key: str = "",
    edge_voice: str = "ko-KR-SunHiNeural",
    piper_path: str = "",
    piper_model: str = "",
) -> SpeakResult:
    """Route TTS to the configured provider, falling back locally when needed."""
    if not enabled or mode == "disabled":
        return SpeakResult(
            ok=False,
            engine="disabled",
            message="음성 응답이 꺼져 있습니다.",
        )

    selected = (mode or "macos_say").strip().lower()
    fallback = (fallback_mode or "macos_say").strip().lower()

    if selected == "macos_say":
        return speak_macos_say(
            text,
            voice=voice or DEFAULT_TTS_VOICE,
            rate=(
                int(rate)
                if isinstance(rate, int) or str(rate).isdigit()
                else DEFAULT_TTS_RATE
            ),
            max_chars=max_chars,
            pause_ms=pause_ms,
            naturalize=naturalize,
        )
    if selected == "elevenlabs":
        result = speak_elevenlabs_tts(
            text,
            voice_id=elevenlabs_voice_id or voice,
            model=elevenlabs_model,
            max_chars=max_chars,
            naturalize=naturalize,
        )
    elif selected == "gemini_tts":
        result = speak_gemini_tts(
            text,
            model=gemini_model,
            voice=_select_gemini_voice(voice, gemini_voice),
            api_key=gemini_api_key,
            max_chars=max_chars,
            naturalize=naturalize,
        )
    elif selected == "edge_tts":
        result = speak_edge_tts(
            text,
            voice=edge_voice or voice or "ko-KR-SunHiNeural",
            rate=rate,
            max_chars=max_chars,
            naturalize=naturalize,
        )
    elif selected == "piper":
        result = speak_piper_tts(
            text,
            piper_path=piper_path,
            model_path=piper_model,
            max_chars=max_chars,
            naturalize=naturalize,
        )
    else:
        return SpeakResult(
            ok=False,
            engine=selected,
            message="지원하지 않는 TTS 모드입니다.",
        )

    if result.ok or fallback != "macos_say":
        return result

    fallback_result = speak_macos_say(
        text,
        voice=DEFAULT_TTS_VOICE,
        rate=DEFAULT_TTS_RATE,
        max_chars=max_chars,
        pause_ms=pause_ms,
        naturalize=naturalize,
    )
    fallback_result.message = f"{result.message} {fallback_result.message}"
    return fallback_result


__all__ = [
    "DEFAULT_TTS_MAX_CHARS",
    "DEFAULT_TTS_PAUSE_MS",
    "DEFAULT_TTS_RATE",
    "DEFAULT_TTS_VOICE",
    "MAX_TTS_CHARS",
    "CLOUD_TTS_SETUP_MESSAGE",
    "PIPER_TTS_SETUP_MESSAGE",
    "EDGE_TTS_SETUP_MESSAGE",
    "GEMINI_TTS_SETUP_MESSAGE",
    "SAY_PATH",
    "SpeakResult",
    "cleanup_tts_text",
    "play_audio_bytes",
    "speak_edge_tts",
    "speak_elevenlabs_tts",
    "speak_gemini_tts",
    "speak_macos_say",
    "speak_piper_tts",
    "speak_with_provider",
    "split_tts_chunks",
    "stop_macos_say",
]
