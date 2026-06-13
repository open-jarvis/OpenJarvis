"""BavariaBookingAgent — domain-specialised orchestrator for Landhaus Bavaria.

Reads the BavariaBookingX domain instructions from the companion
``bavaria_booking.md`` file so the agent behaves as a domain expert for
the website, booking system, deployment pipeline, and approved data sources.
"""

from __future__ import annotations

import pathlib
from typing import Any, List, Optional

from openjarvis.agents.orchestrator import OrchestratorAgent
from openjarvis.core.events import EventBus
from openjarvis.core.registry import AgentRegistry
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.tools._stubs import BaseTool

_BAVARIA_BOOKING_SYSTEM_PROMPT = (
    "You are the BavariaBooking Domain Expert. "
    "See bavaria_booking.md for full instructions."
)


def _load_domain_prompt() -> str:
    """Load the domain prompt from the adjacent ``bavaria_booking.md`` file."""
    md_path = pathlib.Path(__file__).with_suffix(".md")
    if md_path.exists():
        return md_path.read_text(encoding="utf-8")
    return _BAVARIA_BOOKING_SYSTEM_PROMPT


@AgentRegistry.register("bavaria_booking")
class BavariaBookingAgent(OrchestratorAgent):
    """Orchestrator pre-loaded with BavariaBooking domain knowledge.

    Inherits the full function-calling loop from :class:`OrchestratorAgent`
    but injects a fixed system prompt that embeds the BavariaBookingX skill
    content.  The agent can be invoked directly::

        jarvis ask "Fix the booking button" --agent bavaria_booking

    or, in a future routing layer, dispatched by the main orchestrator when
    the query matches the ``bavaria_booking`` domain.
    """

    agent_id = "bavaria_booking"
    _default_temperature = 0.7
    _default_max_tokens = 2048
    _default_max_turns = 15

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        tools: Optional[List[BaseTool]] = None,
        bus: Optional[EventBus] = None,
        max_turns: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        mode: str = "function_calling",
        system_prompt: Optional[str] = None,
        parallel_tools: bool = True,
        interactive: bool = False,
        confirm_callback=None,
    ) -> None:
        # If no explicit system_prompt is passed, load the domain prompt from
        # the companion Markdown file so it can be edited without touching code.
        effective_prompt = system_prompt if system_prompt is not None else _load_domain_prompt()
        super().__init__(
            engine,
            model,
            tools=tools,
            bus=bus,
            max_turns=max_turns,
            temperature=temperature,
            max_tokens=max_tokens,
            mode=mode,
            system_prompt=effective_prompt,
            parallel_tools=parallel_tools,
            interactive=interactive,
            confirm_callback=confirm_callback,
        )


__all__ = ["BavariaBookingAgent", "_BAVARIA_BOOKING_SYSTEM_PROMPT"]
