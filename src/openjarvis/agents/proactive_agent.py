# ruff: noqa: E501
"""Proactive Agent — runs on a cron (default 5am local) to autonomously handle
routine tasks based on learned user behavior.

Lifecycle per run
-----------------
1. Load USER.md + MEMORY.md for behavioral context.
2. Collect overnight data from connected sources via ``digest_collect``.
3. Use the LLM to classify each item and propose actions with a tier + permission key.
4. For each proposed action:
   - TRIVIAL tier          → queue + immediately approve
   - Known always_approve  → queue + immediately approve
   - Known always_deny     → skip silently
   - Everything else       → queue as pending, notify user
5. Execute all approved actions via ``execute_pending_actions``.
6. Send the user a concise summary: what was done + numbered list of what needs approval.

Approval reply format (user replies to the notification message):
    ``{action_id} yes``            approve one action
    ``{action_id} no``             deny one action
    ``always yes {action_id}``     approve + remember for this pattern
    ``always no {action_id}``      deny + remember for this pattern
    ``yes all`` / ``no all``       bulk decision

Wire up ``parse_approval_response`` from ``proactive_tools`` in your channel
message handler to process replies without running the full agent.

Scheduling
----------
The agent self-registers a 5am daily cron task when ``register_cron`` is
called from your app startup:

    from openjarvis.agents.proactive_agent import register_cron
    register_cron(scheduler, notification_channel_id="your-channel-id")
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from openjarvis.agents._stubs import AgentContext, AgentResult, ToolUsingAgent
from openjarvis.core.config import load_config
from openjarvis.core.paths import get_config_dir
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import Message, Role, ToolCall
from openjarvis.tools.approval_store import (
    DECISION_ALWAYS_APPROVE,
    DECISION_ALWAYS_DENY,
    STATUS_APPROVED,
    TIER_MEDIUM,
    TIER_TRIVIAL,
    ApprovalStore,
)
from openjarvis.tools.proactive_tools import get_store

_SYSTEM_PROMPT = """You are a proactive personal assistant agent. You have already collected
data from the user's connected sources (email, messages, calendar). Your job is to:

1. Analyze each item and decide what action (if any) should be taken.
2. For each action, output a JSON object in your response inside a ```json ... ``` block.

Each action object must have these fields:
  - action_type: one of email_delete | email_archive | sms_send | sms_draft_reply |
                 calendar_decline | calendar_accept | no_action
  - description: human-readable sentence explaining what you will do
  - payload: dict with the data needed to execute. ALWAYS include:
      - doc_id: copy the value of ``id=...`` from the digest line, EXACTLY
        as shown.  Example: a digest line ``[gmail id=gmail:18f9abc] From:
        ...`` means ``doc_id`` must be ``"gmail:18f9abc"``.  NEVER invent
        ids like ``"gmail:wells_fargo"`` or ``"msg_1"`` — the executor
        will fail.  If a digest line has no ``id=...`` segment, do not
        propose an action for that line.
      - For email actions: message_id MUST be the part of doc_id after
        the ``gmail:`` prefix (e.g. ``"18f9abc"``).
      - For sms actions: contact (phone/email), body (the message text)
      - For calendar actions: event_id (the part after ``gcalendar:`` in
        the digest's ``id=...``) and calendar_id (default "primary")
  - permission_key: pattern string like "email_delete:domain:noreply.github.com"
  - tier: one of trivial | low | medium | high
  - reasoning: one sentence why

Tier guidance:
  trivial — read-only or categorization only, no external effect
  low     — reversible, routine (delete a known-spam sender, archive newsletter)
  medium  — affects another party but is expected (reply to a simple scheduling text)
  high    — sends a message in the user's voice for the first time, or irreversible

Output a JSON array of action objects inside a single ```json ... ``` block.
Only include items where action_type is not 'no_action'.
If nothing needs to be done, output an empty array: ```json [] ```

HARD LIMITS — these keep responses parseable:
  - Output AT MOST 8 action objects.  Pick the highest-value ones (most
    clearly safe-to-delete or obviously useful to handle).
  - Keep each `reasoning` field to ONE short sentence (≤ 15 words).
  - Keep each `description` field to ONE short sentence (≤ 15 words).
  - No nested objects beyond what the schema requires.
  - Your entire visible response MUST be ONLY the fenced JSON block —
    no explanations, headers, or commentary before or after.

Example response when the digest has two newsletters and a calendar
invite (use exactly this shape; substitute real ids from the digest):

```json
[
  {
    "action_type": "email_archive",
    "description": "Archive Substack newsletter from on+stories@substack.com",
    "payload": {"doc_id": "gmail:18f9...", "message_id": "18f9..."},
    "permission_key": "email_archive:from:on+stories@substack.com",
    "tier": "low",
    "reasoning": "Routine newsletter — safe to archive."
  },
  {
    "action_type": "email_delete",
    "description": "Delete Wells Fargo marketing email",
    "payload": {"doc_id": "gmail:18fa...", "message_id": "18fa..."},
    "permission_key": "email_delete:from:wf.com",
    "tier": "low",
    "reasoning": "Marketing email, user already has account."
  }
]
```

Be generous about proposing low-tier actions for marketing emails,
newsletters, transactional receipts the user has already seen, and
calendar duplicates — these are the items the user wants triaged.

User context is provided below — use it to tailor decisions to their patterns.
"""


def _load_md_file(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _extract_json_block(text: str) -> Optional[List[Dict[str, Any]]]:
    """Extract a JSON array from LLM output.

    Tries (in order):
      1. ```json ... ``` fenced block (preferred).
      2. ``` ... ``` fenced block with no language tag.
      3. First ``[ ... ]`` array in the raw text.

    Returns the parsed list, or ``None`` if nothing parses.
    """
    import re

    candidates: List[str] = []

    # 1. ```json ... ``` (case-insensitive)
    m = re.search(r"```(?:json|JSON)\s*(.*?)```", text, re.DOTALL)
    if m:
        candidates.append(m.group(1).strip())

    # 2. Any ``` ... ``` block (model may omit the language tag)
    for m in re.finditer(r"```\s*(.*?)```", text, re.DOTALL):
        candidates.append(m.group(1).strip())

    # 3. Raw top-level JSON array anywhere in the text (best-effort,
    #    balanced-bracket walk so nested objects don't trip us up).
    start = text.find("[")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : i + 1])
                    break
        next_start = text.find("[", start + 1)
        if next_start == start:
            break
        start = next_start

    for raw in candidates:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            return parsed  # type: ignore[return-value]
        if isinstance(parsed, dict):
            return [parsed]
    return None


def _build_notification_channel(channel_spec: str) -> Optional[Any]:
    """Parse a ``"type:identifier"`` string into a channel backend instance.

    Supports:
      ``imessage:+15551234567``  — sends via AppleScript directly
      ``telegram:123456789``     — instantiates TelegramChannel
      ``slack:D0123456789``      — instantiates registered Slack channel
      Any other type registered in ChannelRegistry

    Returns ``None`` (silently) if the spec is empty or the channel can't
    be instantiated so the agent degrades gracefully to no notifications.
    """
    if not channel_spec or ":" not in channel_spec:
        return None

    channel_type, _, channel_id = channel_spec.partition(":")

    # iMessage: wrap send_imessage() in a minimal BaseChannel-compatible shim
    if channel_type == "imessage":
        from openjarvis.channels._stubs import (
            BaseChannel,
            ChannelStatus,
        )

        class _IMessageShim(BaseChannel):
            channel_id = "imessage"

            def __init__(self, handle: str) -> None:
                self._handle = handle

            def connect(self) -> None:
                pass

            def disconnect(self) -> None:
                pass

            def send(
                self, channel: str, content: str, *, conversation_id: str = ""
            ) -> bool:
                from openjarvis.channels.imessage_daemon import send_imessage

                return send_imessage(self._handle, content)

            def status(self) -> ChannelStatus:
                return ChannelStatus.CONNECTED

            def list_channels(self) -> List[str]:
                return [self._handle]

            def on_message(self, handler: Any) -> None:
                pass

        return _IMessageShim(channel_id)

    # All other channel types: look up in ChannelRegistry
    try:
        import openjarvis.channels  # noqa: F401  trigger registration
        from openjarvis.core.registry import ChannelRegistry

        if ChannelRegistry.contains(channel_type):
            channel_cls = ChannelRegistry.get(channel_type)
            instance = channel_cls()
            try:
                instance.connect()
            except Exception:
                pass
            return instance
    except Exception:
        pass

    return None


@AgentRegistry.register("proactive")
class ProactiveAgent(ToolUsingAgent):
    """Autonomous agent that handles routine tasks based on learned user behavior."""

    agent_id = "proactive"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._notification_channel_id: str = kwargs.pop("notification_channel_id", "")
        self._hours_back: int = kwargs.pop("hours_back", 24)
        self._approval_store: Optional[ApprovalStore] = kwargs.pop(
            "approval_store", None
        )
        self._timezone: str = kwargs.pop("timezone", "America/Los_Angeles")

        # Read config defaults before super().__init__ so we can inject tools
        try:
            cfg = load_config()
            p = cfg.proactive
            if not self._notification_channel_id:
                self._notification_channel_id = p.notification_channel
                self._hours_back = p.hours_back
                self._timezone = p.timezone
        except Exception:
            pass

        # Build the required tools and inject them into the executor.
        # This must happen before super().__init__ is called because
        # ToolUsingAgent builds the ToolExecutor from kwargs["tools"].
        store = self._approval_store or get_store()
        self._approval_store = store

        notification_channel = _build_notification_channel(
            self._notification_channel_id
        )
        self._notification_channel = notification_channel

        from openjarvis.tools.channel_tools import ChannelSendTool
        from openjarvis.tools.digest_collect import DigestCollectTool
        from openjarvis.tools.proactive_tools import (
            CheckPermissionTool,
            ExecutePendingActionsTool,
            GetPendingActionsTool,
            QueueActionTool,
            RecordDecisionTool,
        )

        proactive_tools = [
            DigestCollectTool(),
            ExecutePendingActionsTool(store=store),
            ChannelSendTool(channel=notification_channel),
            CheckPermissionTool(store=store),
            QueueActionTool(store=store),
            GetPendingActionsTool(store=store),
            RecordDecisionTool(store=store),
        ]

        # Merge with any tools passed by the caller
        caller_tools: List[Any] = kwargs.pop("tools", None) or []
        kwargs["tools"] = proactive_tools + caller_tools

        # The agent emits a JSON array of proposals — one entry per actionable
        # item — and a typical morning digest produces dozens. The default
        # max_tokens (often ~1024) truncates the array mid-element, which the
        # parser then rejects.  Give it real room unless the caller overrode.
        kwargs.setdefault("max_tokens", 8192)
        # Deterministic-ish output makes the JSON shape more reliable.
        kwargs.setdefault("temperature", 0.2)

        super().__init__(*args, **kwargs)

    def _get_already_seen_ids(self, store: ApprovalStore) -> Set[str]:
        return store.get_seen_ids()

    def _store(self) -> ApprovalStore:
        if self._approval_store is None:
            self._approval_store = get_store()
        return self._approval_store

    def _build_system_prompt(self) -> str:
        user_md = _load_md_file(get_config_dir() / "USER.md")
        memory_md = _load_md_file(get_config_dir() / "MEMORY.md")
        now = datetime.now()
        context_block = ""
        if user_md or memory_md:
            context_block = "\n\n---\nUSER CONTEXT:\n"
            if user_md:
                context_block += f"\n{user_md.strip()}\n"
            if memory_md:
                context_block += f"\n{memory_md.strip()}\n"
        return (
            _SYSTEM_PROMPT
            + f"\nToday is {now.strftime('%A, %B %d, %Y')} ({self._timezone})."
            + context_block
        )

    def run(
        self,
        input: str = "",
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        self._emit_turn_start(input or "proactive_run")

        store = self._store()
        store.expire_stale()

        # --- Step 1: Collect data — only items user hasn't acted on ---
        sources = ["gmail", "imessage", "gcalendar", "slack", "google_tasks"]
        seen_ids = self._get_already_seen_ids(store)
        collect_call = ToolCall(
            id="proactive-collect-1",
            name="digest_collect",
            arguments=json.dumps(
                {
                    "sources": sources,
                    "hours_back": self._hours_back,
                    "unacted_only": True,
                    "seen_ids": list(seen_ids),
                }
            ),
        )
        collect_result = self._executor.execute(collect_call)
        if not collect_result.success or not collect_result.content.strip():
            self._emit_turn_end(turns=1)
            return AgentResult(
                content="No data collected from connectors — nothing to do.",
                turns=1,
            )

        # --- Step 2: Ask LLM to classify items and propose actions ---
        messages = [
            Message(role=Role.SYSTEM, content=self._build_system_prompt()),
            Message(
                role=Role.USER,
                content=(
                    f"Here is the data collected from the last {self._hours_back} hours:\n\n"
                    f"{collect_result.content}\n\n"
                    "Analyze each item and output the JSON array of proposed actions."
                ),
            ),
        ]
        llm_result = self._generate(messages)
        raw_full = llm_result.get("content", "")
        raw_output = self._strip_think_tags(raw_full)
        proposed: List[Dict[str, Any]] = _extract_json_block(raw_output) or []

        # Debug log — write the raw LLM output and what we parsed out so a
        # human can diagnose "Nothing to report" without re-running the
        # whole agent.  Best-effort; never fail the run because of logging.
        try:
            from openjarvis.core.config import DEFAULT_CONFIG_DIR

            log_dir = DEFAULT_CONFIG_DIR / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "proactive_debug.log"
            with log_path.open("a", encoding="utf-8") as f:
                f.write(f"\n===== {datetime.now().isoformat()} =====\n")
                f.write(f"--- digest ({len(collect_result.content)} chars) ---\n")
                f.write(collect_result.content + "\n")
                f.write(f"--- llm raw ({len(raw_full)} chars) ---\n")
                f.write(raw_full + "\n")
                f.write(f"--- parsed proposals: {len(proposed)} ---\n")
                f.write(json.dumps(proposed, indent=2, default=str) + "\n")
        except Exception:
            pass

        # --- Step 3: Route each proposed action ---
        auto_approve_ids: List[str] = []
        pending_actions = []

        for item in proposed:
            action_type = item.get("action_type", "")
            tier = item.get("tier", TIER_MEDIUM)
            permission_key = item.get("permission_key", f"{action_type}:default")
            description = item.get("description", "")
            payload = item.get("payload", {})

            if not action_type or action_type == "no_action":
                continue

            # Check remembered permission first
            rule = store.get_permission(permission_key)
            if rule and rule.decision == DECISION_ALWAYS_DENY:
                continue

            # Queue the action
            action = store.queue_action(
                action_type=action_type,
                description=description,
                payload=payload,
                permission_key=permission_key,
                tier=tier,
            )

            if tier == TIER_TRIVIAL or (
                rule and rule.decision == DECISION_ALWAYS_APPROVE
            ):
                store.update_status(action.id, STATUS_APPROVED)
                auto_approve_ids.append(action.id)
            else:
                pending_actions.append(action)

        # --- Step 4: Execute all auto-approved actions ---
        executed_results: List[Dict[str, Any]] = []
        if auto_approve_ids:
            exec_call = ToolCall(
                id="proactive-exec-1",
                name="execute_pending_actions",
                arguments=json.dumps({"action_ids": auto_approve_ids}),
            )
            exec_result = self._executor.execute(exec_call)
            if exec_result.success and exec_result.content:
                try:
                    executed_results = json.loads(exec_result.content)
                except json.JSONDecodeError:
                    pass

        # --- Step 5: Build and send notification ---
        notification = self._build_notification(executed_results, pending_actions)

        if notification and self._notification_channel_id:
            send_call = ToolCall(
                id="proactive-notify-1",
                name="channel_send",
                arguments=json.dumps(
                    {
                        "channel": self._notification_channel_id,
                        "content": notification,
                    }
                ),
            )
            self._executor.execute(send_call)
            for action in pending_actions:
                store.update_status(action.id, action.status, notification_sent=True)

        self._emit_turn_end(turns=1)
        return AgentResult(
            content=notification or "Nothing to report.",
            turns=1,
            metadata={
                "auto_executed": len(executed_results),
                "pending_approval": len(pending_actions),
            },
        )

    def _build_notification(
        self,
        executed: List[Dict[str, Any]],
        pending: List[Any],
    ) -> str:
        lines: List[str] = []

        if executed:
            successes = [r for r in executed if r.get("success")]
            failures = [r for r in executed if not r.get("success")]
            lines.append(f"Done automatically ({len(successes)} actions):")
            for r in successes:
                lines.append(f"  ✓ {r['description']}")
            for r in failures:
                lines.append(f"  ✗ {r['description']} — {r.get('message', 'error')}")

        if pending:
            if lines:
                lines.append("")
            lines.append(f"Needs your approval ({len(pending)} actions):")
            for action in pending:
                tier_label = {
                    "low": "low-risk",
                    "medium": "medium",
                    "high": "HIGH",
                }.get(action.tier, action.tier)
                lines.append(f"  [{action.id}] ({tier_label}) {action.description}")
            lines.append("")
            lines.append(
                "Reply with: '{id} yes/no' to decide. "
                "Add 'always' to remember (e.g. 'always yes {id}'). "
                "'yes all' / 'no all' for bulk."
            )

        if not lines:
            return ""
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Convenience: register the 5am cron task
# ---------------------------------------------------------------------------


def register_cron(
    scheduler: Any,
    *,
    notification_channel_id: str = "",
    cron_expr: str = "",
    hours_back: int = 0,
    timezone: str = "",
) -> Any:
    """Register the proactive agent as a daily cron task.

    All defaults are read from ``config.toml [proactive]`` when not explicitly
    passed.  Call this once from app startup after the scheduler is started.

    Parameters
    ----------
    scheduler:
        A ``TaskScheduler`` instance.
    notification_channel_id:
        Override the channel ID from config.  If empty, uses ``notification_channel``
        from ``[proactive]`` in config.toml.
    cron_expr:
        Override the cron schedule.  Defaults to config value (``"0 5 * * *"``).
    hours_back:
        Override hours of data to scan.  Defaults to config value (24).
    timezone:
        Override timezone string.  Defaults to config value.
    """
    try:
        cfg = load_config()
        p = cfg.proactive
        notification_channel_id = notification_channel_id or p.notification_channel
        cron_expr = cron_expr or p.schedule
        hours_back = hours_back or p.hours_back
        timezone = timezone or p.timezone
    except Exception:
        cron_expr = cron_expr or "0 5 * * *"
        hours_back = hours_back or 24
        timezone = timezone or "America/Los_Angeles"

    return scheduler.create_task(
        prompt="Run the proactive agent: collect overnight data, execute approved actions, notify pending approvals.",
        schedule_type="cron",
        schedule_value=cron_expr,
        agent="proactive",
        context_mode="isolated",
        metadata={
            "notification_channel_id": notification_channel_id,
            "hours_back": hours_back,
            "timezone": timezone,
        },
    )
