"""WorkArena task environment — per-task BrowserGym lifecycle + validation.

Wraps BrowserGym's ``BrowserEnv`` to provide per-task browser/ServiceNow
setup, observation access, action stepping, and native ``validate()``
scoring against the live ServiceNow instance.
"""

from __future__ import annotations

import logging
import re
from types import TracebackType
from typing import Any, Callable, Dict, MutableMapping, Optional, Tuple, Type

LOGGER = logging.getLogger(__name__)

_MAX_OBS_CHARS = 16_000

_BROWSERGYM_SYSTEM_MSG = """\
You are a web automation agent operating in a ServiceNow instance via BrowserGym.
You interact with the page through structured actions.

## Action Space

Respond with exactly ONE action per turn. Actions are function calls:

  click(bid)                    - Click element with browser ID
  dblclick(bid)                 - Double-click element
  fill(bid, value)              - Clear field and type value
  select_option(bid, options)   - Select option(s) in dropdown
  check(bid) / uncheck(bid)     - Toggle checkbox
  hover(bid)                    - Hover over element
  press(bid, key_comb)          - Press key (e.g. "Enter", "Tab")
  focus(bid)                    - Focus on element
  clear(bid)                    - Clear a text field
  scroll(delta_x, delta_y)      - Scroll the page (pixels)
  drag_and_drop(from_bid, to_bid) - Drag element to another
  goto(url)                     - Navigate to URL
  go_back()                     - Browser back
  go_forward()                  - Browser forward
  new_tab()                     - Open a new tab
  tab_focus(index)              - Switch to tab by index
  tab_close()                   - Close current tab
  send_msg_to_user(text)        - Send answer/message to the user
  report_infeasible(reason)     - Report task cannot be completed
  noop()                        - Wait / do nothing

Element IDs (bid) appear in the accessibility tree as [bid=XXX].
Respond with your reasoning, then the action on its own line.
"""

_ACTION_NAMES = (
    "click",
    "dblclick",
    "fill",
    "select_option",
    "check",
    "uncheck",
    "clear",
    "hover",
    "press",
    "focus",
    "scroll",
    "goto",
    "go_back",
    "go_forward",
    "tab_focus",
    "tab_close",
    "new_tab",
    "send_msg_to_user",
    "report_infeasible",
    "noop",
    "drag_and_drop",
)
_ACTION_PREFIX_RE = re.compile(
    r"(" + "|".join(_ACTION_NAMES) + r")\s*\(",
)


def _extract_action_call(text: str, match: re.Match) -> str:
    """Extract a balanced action call starting from a regex match on ``name(``."""
    start = match.start()
    paren_start = match.end() - 1  # position of '('
    depth = 1
    i = paren_start + 1
    in_str: str | None = None
    while i < len(text) and depth > 0:
        ch = text[i]
        if in_str is not None:
            if ch == "\\" and i + 1 < len(text):
                i += 2
                continue
            if ch == in_str:
                in_str = None
        else:
            if ch in ('"', "'"):
                in_str = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
        i += 1
    return text[start:i]


class WorkArenaTaskEnv:
    """Per-task BrowserGym environment for WorkArena.

    Context manager that creates a ``BrowserEnv``, resets the task against
    the ServiceNow instance, and exposes observation/action/validate methods.

    After the agent finishes, ``run_tests()`` calls the task's native
    ``validate()`` to determine pass/fail from the actual ServiceNow state.
    """

    def __init__(self, metadata: MutableMapping[str, Any]) -> None:
        self._metadata = metadata
        self._env: Any = None
        self._obs: Optional[Dict[str, Any]] = None
        self._goal: str = ""
        self._chat_messages: list = []
        self._done: bool = False
        self._last_reward: float = 0.0
        self._step_count: int = 0
        self.all_responses: list[str] = []
        self.turn_wall_clocks: list[float] = []

    def __enter__(self) -> WorkArenaTaskEnv:
        from browsergym.core.env import BrowserEnv

        task_class = self._metadata["task_class"]
        task_seed = self._metadata["task_seed"]
        headless = self._metadata.get("headless", True)

        LOGGER.info(
            "Setting up WorkArena task: %s (seed=%d, headless=%s)",
            task_class.get_task_id(),
            task_seed,
            headless,
        )

        self._env = BrowserEnv(
            task_entrypoint=task_class,
            headless=headless,
        )

        obs, info = self._env.reset(seed=task_seed)
        self._obs = obs
        self._done = False
        self._step_count = 0

        self._goal = obs.get("goal", "")
        self._chat_messages = list(obs.get("chat_messages", []))

        self._metadata["workarena_env"] = self
        self._metadata["workarena_goal"] = self._goal
        self._metadata["workarena_obs"] = self._format_observation(obs)
        self._metadata["workarena_page"] = self._env.page
        self._metadata["workarena_task"] = self._env.task

        LOGGER.info("WorkArena task goal: %s", self._goal[:200])

        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        self._metadata.pop("workarena_env", None)
        self._metadata.pop("workarena_obs", None)
        self._metadata.pop("workarena_page", None)
        self._metadata.pop("workarena_task", None)

        if self._env is not None:
            try:
                self._env.close()
            except Exception as exc:
                LOGGER.warning("Error closing BrowserEnv: %s", exc)
            self._env = None

        # BrowserGym keeps a process-level Playwright singleton that is
        # bound to the current thread's event loop.  Once this thread
        # exits the instance becomes stale and subsequent tasks fail
        # with "no running event loop".  Stop it and reset the global
        # so the next task creates a fresh one.
        try:
            import browsergym.core as _bgym_core

            pw = _bgym_core._PLAYWRIGHT
            if pw is not None:
                try:
                    pw.stop()
                except Exception:
                    pass
                _bgym_core._set_global_playwright(None)
        except (ImportError, AttributeError):
            pass

    @property
    def goal(self) -> str:
        return self._goal

    @property
    def done(self) -> bool:
        return self._done

    @property
    def observation(self) -> Optional[Dict[str, Any]]:
        return self._obs

    def get_observation_text(self) -> str:
        """Return the current observation formatted as text for the agent."""
        if self._obs is None:
            return ""
        return self._format_observation(self._obs)

    def step(self, action: str) -> Tuple[str, float, bool, Dict[str, Any]]:
        """Execute a BrowserGym action and return (obs_text, reward, done, info).

        Actions use BrowserGym's high-level action format, e.g.:
          click("bid_123")
          fill("bid_456", "hello world")
          scroll(0, 300)
          send_msg_to_user("The answer is 42")
        """
        if self._env is None:
            raise RuntimeError("WorkArena environment not initialized")
        if self._done:
            return "", 0.0, True, {"message": "Episode already finished"}

        obs, reward, terminated, truncated, info = self._env.step(action)
        self._obs = obs
        self._step_count += 1
        self._last_reward = reward
        self._chat_messages = list(obs.get("chat_messages", []))

        self._done = terminated or truncated
        obs_text = self._format_observation(obs)

        self._metadata["workarena_obs"] = obs_text

        return obs_text, reward, self._done, info

    def send_chat_message(self, message: str) -> None:
        """Send a message from the assistant to the chat."""
        if self._env is not None and hasattr(self._env, "chat"):
            self._env.chat.add_message(role="assistant", msg=message)

    def run_tests(self) -> Tuple[bool, Dict[str, Any]]:
        """Validate the task using the native WorkArena validate() method.

        This calls ``task.validate(page, chat_messages)`` which checks the
        actual state of the ServiceNow instance — the canonical evaluation
        method from the original benchmark.
        """
        results: Dict[str, Any] = {
            "steps_taken": self._step_count,
        }

        if self._env is None or self._env.task is None:
            results["error"] = "environment_not_initialized"
            self._metadata["is_resolved"] = False
            self._metadata["reward"] = 0.0
            self._metadata["test_results"] = results
            return False, results

        try:
            chat_msgs = []
            if self._env.chat is not None:
                chat_msgs = self._env.chat.messages

            reward, done, message, info = self._env.task.validate(
                self._env.page,
                chat_msgs,
            )

            is_resolved = reward == 1.0
            results["reward"] = reward
            results["is_resolved"] = is_resolved
            results["validate_message"] = message
            results["validate_info"] = _safe_serialize(info)
            results["chat_message_count"] = len(chat_msgs)

            self._metadata["is_resolved"] = is_resolved
            self._metadata["reward"] = reward
            self._metadata["test_results"] = results

            LOGGER.info(
                "WorkArena validate: reward=%.1f resolved=%s msg=%s",
                reward,
                is_resolved,
                message,
            )
            return is_resolved, results

        except Exception as exc:
            LOGGER.exception("WorkArena validation failed")
            results["error"] = str(exc)
            self._metadata["is_resolved"] = False
            self._metadata["reward"] = 0.0
            self._metadata["test_results"] = results
            return False, results

    # ------------------------------------------------------------------
    # BrowserGym agent-environment interaction loop
    # ------------------------------------------------------------------

    def run_agent_loop(
        self,
        generate_fn: Callable[[str], str],
        max_steps: Optional[int] = None,
    ) -> str:
        """Drive the BrowserGym env in a step loop using *generate_fn* for LLM calls.

        ``generate_fn(prompt) -> response`` is called once per step.
        The loop feeds observations to the LLM, parses a BrowserGym
        action from its response, and steps the environment until the
        task is done or *max_steps* is reached.

        Validation (``run_tests``) is **not** called here — the caller
        (e.g. ``AgenticRunner``) is responsible for that.
        """
        if self._env is None:
            raise RuntimeError(
                "WorkArena environment not initialised — use as context manager"
            )

        if max_steps is None:
            level = self._metadata.get("level", "l1")
            max_steps = 15 if level == "l1" else 50

        import time as _time

        self.all_responses = []
        self.turn_wall_clocks = []
        parse_error: Optional[str] = None

        for step_idx in range(max_steps):
            if self._done:
                break

            prompt = self._build_step_prompt(step_idx, max_steps, parse_error)
            t0 = _time.monotonic()
            response = generate_fn(prompt)
            self.turn_wall_clocks.append(_time.monotonic() - t0)
            self.all_responses.append(response)

            action = self._parse_action(response)
            if action is None:
                parse_error = (
                    "Could not parse a valid action from your previous "
                    "response. Please respond with exactly one action "
                    'call, e.g. click("bid_42").'
                )
                LOGGER.warning(
                    "Step %d: unparseable action, issuing noop",
                    step_idx,
                )
                action = "noop()"
            else:
                parse_error = None

            LOGGER.info("Step %d/%d action: %s", step_idx + 1, max_steps, action[:200])

            _obs_text, _reward, done, _info = self.step(action)
            if done:
                break

        return "\n---\n".join(self.all_responses)

    def _build_step_prompt(
        self,
        step_idx: int,
        max_steps: int,
        parse_error: Optional[str] = None,
    ) -> str:
        parts: list[str] = [_BROWSERGYM_SYSTEM_MSG]
        parts.append(f"## Goal\n{self._goal}")

        obs_text = self.get_observation_text()
        if len(obs_text) > _MAX_OBS_CHARS:
            obs_text = obs_text[:_MAX_OBS_CHARS] + "\n[...observation truncated...]"
        parts.append(f"## Current Observation\n{obs_text}")

        parts.append(f"## Progress\nStep {step_idx + 1} of {max_steps}")

        if parse_error:
            parts.append(f"## Warning\n{parse_error}")

        parts.append("What is your next action?")
        return "\n\n".join(parts)

    @staticmethod
    def _parse_action(response: str) -> Optional[str]:
        """Extract the last BrowserGym high-level action from *response*."""
        last_action: str | None = None
        for m in _ACTION_PREFIX_RE.finditer(response):
            last_action = _extract_action_call(response, m)
        return last_action.strip() if last_action else None

    def _format_observation(self, obs: Dict[str, Any]) -> str:
        """Format a BrowserGym observation as text for the agent."""
        parts: list[str] = []

        goal = obs.get("goal", "")
        if goal:
            parts.append(f"## Goal\n{goal}")

        url = obs.get("url", "")
        if url:
            parts.append(f"## Current URL\n{url}")

        axtree = obs.get("axtree_object")
        if axtree is not None:
            axtree_text = self._flatten_axtree(axtree)
            if axtree_text:
                parts.append(f"## Accessibility Tree\n{axtree_text}")

        focused = obs.get("focused_element_bid", "")
        if focused:
            parts.append(f"## Focused Element\n{focused}")

        last_action = obs.get("last_action", "")
        if last_action:
            parts.append(f"## Last Action\n{last_action}")

        last_error = obs.get("last_action_error", "")
        if last_error:
            parts.append(f"## Last Action Error\n{last_error}")

        open_urls = obs.get("open_pages_urls", [])
        open_titles = obs.get("open_pages_titles", [])
        if open_urls:
            tabs = []
            for i, (u, t) in enumerate(
                zip(open_urls, open_titles or [""] * len(open_urls))
            ):
                tabs.append(f"  [{i}] {t} — {u}")
            parts.append("## Open Tabs\n" + "\n".join(tabs))

        return "\n\n".join(parts)

    def _flatten_axtree(self, node: Any, depth: int = 0) -> str:
        """Recursively flatten a BrowserGym AXTree node into text."""
        if node is None:
            return ""

        if isinstance(node, str):
            return node

        if not isinstance(node, dict):
            return str(node)

        lines: list[str] = []
        indent = "  " * depth

        role = node.get("role", "")
        name = node.get("name", "")
        bid = node.get("bid", "")
        value = node.get("value", "")

        tag = role
        if bid:
            tag += f" [bid={bid}]"
        if name:
            tag += f' "{name}"'
        if value:
            tag += f' value="{value}"'

        if tag.strip():
            lines.append(f"{indent}{tag}")

        children = node.get("children", [])
        if isinstance(children, list):
            for child in children:
                child_text = self._flatten_axtree(child, depth + 1)
                if child_text:
                    lines.append(child_text)

        return "\n".join(lines)


def _safe_serialize(obj: Any) -> Any:
    """Convert non-serializable objects to strings."""
    if isinstance(obj, dict):
        return {k: _safe_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_serialize(v) for v in obj]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    return str(obj)


__all__ = ["WorkArenaTaskEnv"]
