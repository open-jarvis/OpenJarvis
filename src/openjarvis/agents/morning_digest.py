"""Morning Digest Agent — synthesizes a daily briefing from multiple sources.

Thin orchestrator that delegates to digest_collect (data fetching),
the LLM (narrative synthesis), and text_to_speech (audio generation).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult, ToolUsingAgent
from openjarvis.agents.digest_store import DigestArtifact, DigestStore
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import Message, Role, ToolCall


def _load_persona(persona_name: str) -> str:
    """Load a persona prompt file by name."""
    search_paths = [
        Path("configs/openjarvis/prompts/personas") / f"{persona_name}.md",
        Path.home() / ".openjarvis" / "prompts" / "personas" / f"{persona_name}.md",
    ]
    for p in search_paths:
        if p.exists():
            return p.read_text(encoding="utf-8")
    return ""


@AgentRegistry.register("morning_digest")
class MorningDigestAgent(ToolUsingAgent):
    """Pre-compute a daily digest from configured data sources."""

    agent_id = "morning_digest"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Extract digest-specific kwargs before passing to parent
        self._persona = kwargs.pop("persona", "jarvis")
        self._sections = kwargs.pop(
            "sections", ["messages", "calendar", "health", "world"]
        )
        self._section_sources = kwargs.pop("section_sources", {})
        self._timezone = kwargs.pop("timezone", "America/Los_Angeles")
        self._voice_id = kwargs.pop("voice_id", "")
        self._voice_speed = kwargs.pop("voice_speed", 1.0)
        self._tts_backend = kwargs.pop("tts_backend", "cartesia")
        self._digest_store_path = kwargs.pop("digest_store_path", "")
        self._honorific = kwargs.pop("honorific", "sir")
        super().__init__(*args, **kwargs)

    def _build_system_prompt(self) -> str:
        """Assemble the system prompt from persona + briefing structure."""
        persona_text = _load_persona(self._persona)
        now = datetime.now()
        honorific = getattr(self, "_honorific", "sir")

        return (
            f"{persona_text}\n\n"
            f"Today is {now.strftime('%A, %B %d, %Y')}. "
            f"The time is {now.strftime('%I:%M %p')} in {self._timezone}.\n"
            f"The user's preferred honorific is: {honorific}\n\n"
            "You receive structured data from the user's connected services. "
            "The data has ALREADY been collected — it appears in the user "
            "message. You do NOT fetch anything yourself.\n\n"
            "Produce a 2-4 minute spoken briefing in DECREASING order of "
            "importance:\n\n"
            "1. GREETING + PRIORITIES — Open with the honorific and "
            "immediately state what needs attention: overdue tasks, today's "
            "deadlines, events requiring preparation. Connect related items "
            "('Your rebuttals are overdue and you have a dinner at 6, so "
            "I'd tackle those first').\n\n"
            "2. SCHEDULE — Today's upcoming events with time context: 'You "
            "have 3 hours before your next meeting.' Skip past events.\n\n"
            "3. MESSAGES — Triage across ALL channels (email, texts, Slack):\n"
            "  - First: messages from real people needing a REPLY or DECISION\n"
            "  - Second: messages containing deadlines or action items\n"
            "  - Last: brief acknowledgment of casual threads ('Your group "
            "chat has been lively but nothing requiring a response')\n"
            "  - SKIP automated emails, newsletters, and marketing entirely\n"
            "  - Quote relevant message text when it helps\n\n"
            "4. HEALTH — Interpret trends, not raw numbers. 'Your sleep has "
            "improved three nights running and your readiness is strong' — "
            "not 'HRV 53, HR 56.' If multiple days of data, compare.\n\n"
            "5. WORLD — Weather forecast, top news (AI/tech, business, "
            "general). Skip if no data.\n\n"
            "6. CLOSING — One forward-looking sentence with the honorific.\n\n"
            "ABSOLUTE RULES (violations are unacceptable):\n"
            "- ONLY facts from the data. Zero hallucination.\n"
            "- NEVER mention disconnected or unavailable sources.\n"
            "- NEVER state raw health numbers. Say 'your sleep was solid' "
            "NOT 'heart rate 56 bpm' or 'HRV 53' or '6000 steps' or "
            "'readiness 82'. Interpret, never enumerate.\n"
            "- NEVER describe actions you are taking.\n"
            "- Acknowledge every source that returned data, even briefly.\n"
            "- No markdown, emojis, bullets, or headers.\n"
            "- STRICT LIMIT: 200 words. Be concise."
        )

    def _resolve_sources(self) -> List[str]:
        """Get the list of connector IDs to query."""
        default_source_map = {
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
        sources = set()
        for section in self._sections:
            section_sources = self._section_sources.get(
                section, default_source_map.get(section, [])
            )
            sources.update(section_sources)
        return list(sources)

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        self._emit_turn_start(input)

        # Step 1: Collect data from connectors
        sources = self._resolve_sources()
        collect_call = ToolCall(
            id="digest-collect-1",
            name="digest_collect",
            arguments=json.dumps({"sources": sources, "hours_back": 24}),
        )
        collect_result = self._executor.execute(collect_call)
        collected_data = collect_result.content

        # Step 2: Synthesize narrative via LLM
        system_prompt = self._build_system_prompt()
        messages = [
            Message(role=Role.SYSTEM, content=system_prompt),
            Message(
                role=Role.USER,
                content=(
                    f"Here is the collected data from my sources:\n\n"
                    f"{collected_data}\n\n"
                    f"Synthesize my morning briefing. Remember:\n"
                    f"- Priority-first, connect related items\n"
                    f"- For health: say 'solid', 'improving', 'dipped' "
                    f"— NEVER say any number (no 82, no 56, no 6000)\n"
                    f"- Do NOT invent reasons for health changes\n"
                    f"- Do NOT mention disconnected sources\n"
                    f"- Do NOT repeat the greeting in your closing\n"
                    f"- Use the honorific ONLY 2-3 times total\n"
                    f"- Skip notifications from the user themselves\n"
                    f"- STRICT LIMIT: 200-250 words maximum"
                ),
            ),
        ]

        result = self._generate(messages)
        narrative = self._strip_think_tags(result.get("content", ""))

        # Step 2b: Self-evaluate and optionally regenerate
        quality_score = 0.0
        evaluator_feedback = ""
        try:
            from openjarvis.agents.digest_evaluator import DigestEvaluator

            evaluator = DigestEvaluator(self._engine, self._model)
            quality_score, evaluator_feedback = evaluator.evaluate(
                collected_data, narrative
            )

            if quality_score < 7.0 and evaluator_feedback:
                # Regenerate with feedback
                messages.append(
                    Message(
                        role=Role.USER,
                        content=(
                            f"Your briefing scored {quality_score:.1f}/10. "
                            f"Feedback: {evaluator_feedback}\n"
                            f"Please revise the briefing addressing this feedback."
                        ),
                    )
                )
                result = self._generate(messages)
                narrative = self._strip_think_tags(result.get("content", ""))
        except Exception:  # noqa: BLE001
            pass  # Evaluator failure shouldn't block digest delivery

        # Step 3: Generate audio via TTS
        # Strip any markdown that slipped through (##, *, -, etc.)
        import re

        tts_text = re.sub(r"^#{1,6}\s+", "", narrative, flags=re.MULTILINE)
        tts_text = re.sub(r"^\s*[-*•]\s+", "", tts_text, flags=re.MULTILINE)
        tts_text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", tts_text)
        tts_text = tts_text.strip()

        tts_call = ToolCall(
            id="digest-tts-1",
            name="text_to_speech",
            arguments=json.dumps(
                {
                    "text": tts_text,
                    "voice_id": self._voice_id,
                    "backend": self._tts_backend,
                    "speed": self._voice_speed,
                }
            ),
        )
        tts_result = self._executor.execute(tts_call)
        audio_path = (
            tts_result.metadata.get("audio_path", "") if tts_result.success else ""
        )

        # Step 4: Store the artifact
        artifact = DigestArtifact(
            text=narrative,
            audio_path=Path(audio_path) if audio_path else Path(""),
            sections={},
            sources_used=sources,
            generated_at=datetime.now(),
            model_used=self._model,
            voice_used=self._voice_id,
            quality_score=quality_score,
            evaluator_feedback=evaluator_feedback,
        )

        store = DigestStore(db_path=self._digest_store_path)
        store.save(artifact)
        store.close()

        self._emit_turn_end(turns=1)
        return AgentResult(
            content=narrative,
            tool_results=[collect_result, tts_result],
            turns=1,
            metadata={
                "audio_path": audio_path,
                "sources_used": sources,
            },
        )
