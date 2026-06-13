"""ChiefOfStaff Agent — automatic domain-agent routing.

Inspired by the Claude Agent SDK cookbook.  The ChiefOfStaff reads a
natural-language request, classifies it, and routes it to the most
suitable domain agent.  If the request is ambiguous or spans multiple
domains, it can optionally fall back to Plan Mode so the user sees a
roadmap before execution.
"""

from __future__ import annotations

import json
import logging
from typing import Any, List, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult, ToolUsingAgent
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.tools._stubs import BaseTool

logger = logging.getLogger("openjarvis.chief_of_staff")

_ROUTING_PROMPT = """You are the Chief of Staff for OpenJarvis. Your sole job is to analyse a user request and decide which specialist agent should handle it.

Available specialists:
{descriptions}

Respond using ONLY this JSON format (no markdown, no extra text):

{{"agent": "<agent_id>", "confidence": 0.0-1.0, "reason": "<one-sentence explanation>", "needs_plan": true|false}}

Rules:
- Choose exactly one agent from the list above.
- confidence >= 0.7 means route immediately.
- confidence < 0.7 means ask the user for clarification (do NOT guess).
- Set needs_plan=true when the task clearly spans multiple steps or domains.
- If the request is a greeting, small-talk, or general question, choose "orchestrator".
- If the user explicitly mentions an agent name, trust that unless it is clearly wrong.
"""


@AgentRegistry.register("chief_of_staff")
class ChiefOfStaffAgent(ToolUsingAgent):
    """Meta-agent that routes requests to domain agents.

    When ``auto_route=True`` the agent acts as a transparent router:
    it classifies the request, forwards it to the chosen domain agent,
    and returns the result verbatim.  The caller sees only the final
    answer, not the routing decision.

    When ``plan_first=True`` the agent returns a :class:`PlanResponse`
    instead of executing, giving the user a chance to review before
    proceeding.
    """

    agent_id = "chief_of_staff"
    _default_temperature = 0.3
    _default_max_tokens = 1024
    _default_max_turns = 2

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        tools: Optional[List[BaseTool]] = None,
        bus: Optional[Any] = None,
        max_turns: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        auto_route: bool = True,
        plan_first: bool = False,
    ) -> None:
        super().__init__(
            engine,
            model,
            tools=tools,
            bus=bus,
            max_turns=max_turns,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._auto_route = auto_route
        self._plan_first = plan_first

    def _build_routing_prompt(self) -> str:
        """Enumerate all registered domain agents for the LLM prompt."""
        descriptions = []
        for aid, cls in AgentRegistry.items():
            if aid == self.agent_id:
                continue
            # Derive a short description from class docstring or a custom attr
            doc = (cls.__doc__ or "").strip().split("\n")[0]
            if not doc:
                doc = "General purpose agent"
            descriptions.append(f"- {aid}: {doc}")
        return _ROUTING_PROMPT.format(descriptions="\n".join(descriptions))

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        self._emit_turn_start(input)

        # ------------------------------------------------------------------
        # 1. Classification
        # ------------------------------------------------------------------
        routing_sys = self._build_routing_prompt()
        classify_messages = [
            Message(role=Role.SYSTEM, content=routing_sys),
            Message(role=Role.USER, content=f"User request: {input}"),
        ]

        classify_result = self._generate(classify_messages)
        raw_json = classify_result.get("content", "")

        # Strip markdown fences if the model wrapped JSON in ```json ... ```
        raw_json = raw_json.strip()
        if raw_json.startswith("```"):
            raw_json = raw_json.split("```", 2)[-1]
            raw_json = raw_json.lstrip("json").strip()

        decision = {"agent": "orchestrator", "confidence": 1.0, "reason": "Fallback", "needs_plan": False}
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, dict):
                decision.update(parsed)
        except json.JSONDecodeError:
            logger.warning("Routing JSON parse failed, using fallback: %s", raw_json[:200])

        chosen_agent_id = decision.get("agent", "orchestrator")
        confidence = decision.get("confidence", 0.0)
        needs_plan = decision.get("needs_plan", False)

        logger.info(
            "ChiefOfStaff routed to %s (confidence=%.2f, needs_plan=%s)",
            chosen_agent_id,
            confidence,
            needs_plan,
        )

        # ------------------------------------------------------------------
        # 2. Low confidence -> ask user
        # ------------------------------------------------------------------
        if confidence < 0.7:
            reply = (
                f"I'm not sure which specialist fits best ({confidence:.0%} confidence). "
                f"My best guess is **{chosen_agent_id}** because: {decision.get('reason', '')}\n\n"
                f"Could you clarify which domain this relates to (e.g. booking, housekeeping, staff)?"
            )
            self._emit_turn_end(turns=1)
            return AgentResult(
                content=reply,
                tool_results=[],
                turns=1,
                metadata={"routing": decision, "await_clarification": True},
            )

        # ------------------------------------------------------------------
        # 3. Plan-first mode -> return plan without executing
        # ------------------------------------------------------------------
        if self._plan_first or needs_plan:
            from openjarvis.agents.plan_mode import PlanModeAgent

            plan_agent = PlanModeAgent(
                self._engine,
                self._model,
                temperature=0.4,
                max_tokens=2048,
            )
            plan_result = plan_agent.run(input, context=context)
            self._emit_turn_end(turns=1)
            return AgentResult(
                content=plan_result.content,
                tool_results=[],
                turns=1,
                metadata={
                    "routing": decision,
                    "plan_mode": True,
                    **plan_result.metadata,
                },
            )

        # ------------------------------------------------------------------
        # 4. Auto-route -> delegate to chosen domain agent
        # ------------------------------------------------------------------
        if self._auto_route and chosen_agent_id != self.agent_id:
            agent_cls = AgentRegistry.get(chosen_agent_id)
            if agent_cls is None:
                # Agent not found -> fall back to orchestrator
                chosen_agent_id = "orchestrator"
                agent_cls = AgentRegistry.get(chosen_agent_id)

            if agent_cls is not None:
                # Instantiate the target agent with the same engine / model
                target = agent_cls(
                    self._engine,
                    self._model,
                    tools=self._tools,
                    bus=self._bus,
                    max_turns=getattr(self, "_max_turns", 10),
                    temperature=getattr(self, "_temperature", 0.7),
                    max_tokens=getattr(self, "_max_tokens", 1024),
                )
                # Forward the request verbatim
                _raw = target.run(input, context=context)
                # Handle async run() if the target agent returns a coroutine
                import asyncio
                if asyncio.iscoroutine(_raw):
                    # We are inside a sync method — run via asyncio.run() only
                    # if no loop is running, otherwise use run_until_complete
                    try:
                        loop = asyncio.get_running_loop()
                        target_result = asyncio.run_coroutine_threadsafe(_raw, loop).result()
                    except RuntimeError:
                        target_result = asyncio.run(_raw)
                else:
                    target_result = _raw

                self._emit_turn_end(turns=1)
                return AgentResult(
                    content=target_result.content,
                    tool_results=target_result.tool_results,
                    turns=1,
                    metadata={
                        "routing": decision,
                        "delegated_to": chosen_agent_id,
                        **target_result.metadata,
                    },
                )

        # Ultimate fallback: treat as direct chat
        self._emit_turn_end(turns=1)
        return AgentResult(
            content=f"Routed to {chosen_agent_id} but no agent found.",
            tool_results=[],
            turns=1,
            metadata={"routing": decision, "error": "agent_not_found"},
        )


__all__ = ["ChiefOfStaffAgent"]
