"""Activities for the durable Morning Digest pipeline.

Each activity wraps one fallible side-effecting step from
``src/openjarvis/agents/morning_digest.py``. Activities are intentionally
small and idempotent-friendly so Temporal can retry them independently
without re-doing earlier work.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from temporalio import activity


@dataclass
class DigestInput:
    persona: str = "jarvis"
    sections: list[str] = field(
        default_factory=lambda: ["messages", "calendar", "health", "world"]
    )
    section_sources: dict[str, list[str]] = field(default_factory=dict)
    timezone: str = "America/Los_Angeles"
    voice_id: str = ""
    voice_speed: float = 1.0
    tts_backend: str = "cartesia"
    digest_store_path: str = ""
    honorific: str = "sir"
    model: str = ""
    engine: str = ""


@dataclass
class CollectedData:
    sources: list[str]
    payload: str


@dataclass
class GeneratedNarrative:
    text: str
    quality_score: float = 0.0
    evaluator_feedback: str = ""


@dataclass
class TTSResult:
    audio_path: str
    success: bool


_DEFAULT_SOURCE_MAP: dict[str, list[str]] = {
    "messages": [
        "gmail",
        "slack",
        "google_tasks",
        "imessage",
        "github_notifications",
    ],
    "calendar": ["gcalendar"],
    "health": ["oura", "apple_health"],
    "world": ["weather", "hackernews", "news_rss"],
    "music": ["spotify", "apple_music"],
}


def _resolve_sources(
    sections: list[str], overrides: dict[str, list[str]]
) -> list[str]:
    out: set[str] = set()
    for section in sections:
        out.update(overrides.get(section, _DEFAULT_SOURCE_MAP.get(section, [])))
    return sorted(out)


@activity.defn
def collect_sources(inp: DigestInput) -> CollectedData:
    """Step 1: fan out to connectors.

    Each connector inside ``digest_collect`` already handles its own auth,
    but the surrounding network/rate-limit failures bubble up here so
    Temporal can retry the *whole collection* with exponential backoff
    rather than letting one slow connector kill the run.
    """
    from openjarvis.core.types import ToolCall
    from openjarvis.tools.digest_collect import DigestCollectTool

    sources = _resolve_sources(inp.sections, inp.section_sources)
    activity.logger.info("collect_sources sources=%s", sources)

    tool = DigestCollectTool()
    call = ToolCall(
        id="digest-collect-1",
        name="digest_collect",
        arguments=json.dumps({"sources": sources, "hours_back": 24}),
    )
    result = tool.execute(call)
    return CollectedData(sources=sources, payload=result.content)


def _build_system_prompt(inp: DigestInput) -> str:
    from openjarvis.agents.morning_digest import _load_persona

    persona_text = _load_persona(inp.persona)
    now = datetime.now()
    return (
        f"{persona_text}\n\n"
        f"Today is {now.strftime('%A, %B %d, %Y')}. "
        f"The time is {now.strftime('%I:%M %p')} in {inp.timezone}.\n"
        f"The user's preferred honorific is: {inp.honorific}\n\n"
        "Produce a concise spoken briefing in decreasing order of importance. "
        "Zero hallucination. Strict 200-250 word limit."
    )


@activity.defn
def generate_narrative(
    inp: DigestInput, collected: CollectedData
) -> GeneratedNarrative:
    """Step 2 + 2b: synthesize the narrative and self-evaluate.

    Failure here is expensive (LLM cost) so we use a tighter retry budget
    in the workflow. The evaluator is best-effort; if the evaluator import
    or call fails, we keep the original narrative instead of swallowing
    the error silently the way the legacy implementation does.
    """
    from openjarvis.agents._stubs import ToolUsingAgent
    from openjarvis.core.types import Message, Role

    agent = ToolUsingAgent(engine=inp.engine, model=inp.model)
    system_prompt = _build_system_prompt(inp)
    messages = [
        Message(role=Role.SYSTEM, content=system_prompt),
        Message(
            role=Role.USER,
            content=(
                "Here is the collected data from my sources:\n\n"
                f"{collected.payload}\n\n"
                "Synthesize my morning briefing."
            ),
        ),
    ]

    result = agent._generate(messages)
    narrative = agent._strip_think_tags(result.get("content", ""))

    quality_score = 0.0
    feedback = ""
    try:
        from openjarvis.agents.digest_evaluator import DigestEvaluator

        evaluator = DigestEvaluator(inp.engine, inp.model)
        quality_score, feedback = evaluator.evaluate(collected.payload, narrative)

        if quality_score < 7.0 and feedback:
            messages.append(
                Message(
                    role=Role.USER,
                    content=(
                        f"Your briefing scored {quality_score:.1f}/10. "
                        f"Feedback: {feedback}\nPlease revise."
                    ),
                )
            )
            result = agent._generate(messages)
            narrative = agent._strip_think_tags(result.get("content", ""))
    except Exception as exc:  # noqa: BLE001
        activity.logger.warning("evaluator unavailable, skipping: %s", exc)

    return GeneratedNarrative(
        text=narrative,
        quality_score=quality_score,
        evaluator_feedback=feedback,
    )


@activity.defn
def synthesize_audio(inp: DigestInput, narrative: GeneratedNarrative) -> TTSResult:
    """Step 3: hand the cleaned text to TTS.

    External provider (Cartesia/Deepgram) — heartbeats keep Temporal
    aware that long syntheses are still alive instead of being marked
    timed out.
    """
    from openjarvis.core.types import ToolCall
    from openjarvis.tools.text_to_speech import TextToSpeechTool

    text = narrative.text
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*\u2022]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text).strip()

    activity.heartbeat("starting tts")
    tool = TextToSpeechTool()
    call = ToolCall(
        id="digest-tts-1",
        name="text_to_speech",
        arguments=json.dumps(
            {
                "text": text,
                "voice_id": inp.voice_id,
                "backend": inp.tts_backend,
                "speed": inp.voice_speed,
            }
        ),
    )
    result = tool.execute(call)
    audio_path = (
        result.metadata.get("audio_path", "") if getattr(result, "success", False) else ""
    )
    return TTSResult(audio_path=audio_path, success=bool(audio_path))


@activity.defn
def store_artifact(
    inp: DigestInput,
    collected: CollectedData,
    narrative: GeneratedNarrative,
    tts: TTSResult,
) -> dict[str, Any]:
    """Step 4: persist to the SQLite digest store. Local + idempotent."""
    from openjarvis.agents.digest_store import DigestArtifact, DigestStore

    artifact = DigestArtifact(
        text=narrative.text,
        audio_path=Path(tts.audio_path) if tts.audio_path else Path(""),
        sections={},
        sources_used=collected.sources,
        generated_at=datetime.now(),
        model_used=inp.model,
        voice_used=inp.voice_id,
        quality_score=narrative.quality_score,
        evaluator_feedback=narrative.evaluator_feedback,
    )

    store = DigestStore(db_path=inp.digest_store_path)
    try:
        store.save(artifact)
    finally:
        store.close()

    return {
        "audio_path": tts.audio_path,
        "sources_used": collected.sources,
        "quality_score": narrative.quality_score,
    }
