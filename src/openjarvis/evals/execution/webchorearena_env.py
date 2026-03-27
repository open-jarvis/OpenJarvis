"""WebChoreArena task environment — Playwright-based browser interaction.

Wraps the WebArena browser environment to provide per-task setup,
observation access, action stepping, and evaluation using the
original WebArena evaluation harness (StringEvaluator, URLEvaluator,
HTMLContentEvaluator combined multiplicatively).

Requires:
  - playwright (pip install playwright && playwright install)
  - Running WebArena standalone sites (Shopping, Reddit, GitLab, etc.)
  - Environment variables: SHOPPING, SHOPPING_ADMIN, REDDIT, GITLAB, MAP, WIKIPEDIA
"""

from __future__ import annotations

import html
import logging
import os
import re
import urllib.parse
from pathlib import Path
from types import TracebackType
from typing import Any, Callable, Dict, List, MutableMapping, Optional, Tuple, Type

LOGGER = logging.getLogger(__name__)

_MAX_OBS_CHARS = 16_000
_MAX_STEPS_DEFAULT = 30

_SYSTEM_MSG = """\
You are a web browsing agent. You interact with web pages using actions.

## Available Actions

  click [element_id]            - Click an element
  type [element_id] [text]      - Type text into an element
  hover [element_id]            - Hover over an element
  press [key]                   - Press a key (Enter, Tab, etc.)
  scroll [up|down]              - Scroll the page
  goto [url]                    - Navigate to a URL
  go_back                       - Go back
  stop [answer]                 - Stop and provide your final answer

When the task asks for information, use `stop [your answer]` to provide it.
When the task asks you to perform an action, complete it and then `stop [done]`.

Element IDs appear in brackets like [123] in the accessibility tree.
"""

_STOP_RE = re.compile(r"stop\s*\[(.+)\]", re.IGNORECASE | re.DOTALL)


class WebChoreArenaTaskEnv:
    """Per-task browser environment for WebChoreArena.

    Context manager that creates a Playwright browser, navigates to the
    task's start URL, and exposes observation/action/evaluate methods.

    Evaluation uses the original WebArena evaluator harness with
    multiplicative combination of StringEvaluator, URLEvaluator, and
    HTMLContentEvaluator.
    """

    def __init__(
        self,
        metadata: MutableMapping[str, Any],
        headless: bool = True,
    ) -> None:
        self._metadata = metadata
        self._headless = headless
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._cdp_session: Any = None
        self._done = False
        self._agent_answer = ""
        self._step_count = 0
        self._task_config: Dict[str, Any] = metadata.get("task_config", {})

    def __enter__(self) -> WebChoreArenaTaskEnv:
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self._headless,
        )

        storage_state = self._resolve_storage_state()
        if storage_state and Path(storage_state).exists():
            self._context = self._browser.new_context(
                viewport={"width": 1920, "height": 1080},
                storage_state=storage_state,
            )
        else:
            self._context = self._browser.new_context(
                viewport={"width": 1920, "height": 1080},
            )

        self._page = self._context.new_page()
        self._cdp_session = self._context.new_cdp_session(self._page)

        start_url = self._resolve_url(
            self._metadata.get("start_url", "")
            or self._metadata.get("start_url_lite", "")
        )
        if start_url:
            self._page.goto(start_url, wait_until="domcontentloaded")
            self._page.wait_for_timeout(2000)

        self._done = False
        self._step_count = 0
        self._agent_answer = ""

        LOGGER.info(
            "WebChoreArena task %s: started at %s",
            self._metadata.get("task_id", "?"),
            start_url,
        )

        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        if self._cdp_session is not None:
            try:
                self._cdp_session.detach()
            except Exception:
                pass
            self._cdp_session = None
        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    # ------------------------------------------------------------------
    # Agent interaction loop
    # ------------------------------------------------------------------

    def run_agent_loop(
        self,
        generate_fn: Callable[[str], str],
        max_steps: Optional[int] = None,
    ) -> str:
        """Drive the browser env in a step loop using *generate_fn* for LLM calls.

        Returns the agent's final answer text.
        """
        if self._page is None:
            raise RuntimeError("Environment not initialized — use as context manager")

        if max_steps is None:
            max_steps = _MAX_STEPS_DEFAULT

        responses: List[str] = []
        intent = self._task_config.get(
            "intent",
            self._task_config.get("intent_template", ""),
        )

        for step_idx in range(max_steps):
            if self._done:
                break

            prompt = self._build_step_prompt(intent, step_idx, max_steps)
            response = generate_fn(prompt)
            responses.append(response)

            action = response.strip()
            self._execute_action(action)
            self._step_count += 1

            if self._done:
                break

        # Run evaluation after the interaction loop
        self._run_evaluation()

        return self._agent_answer or "\n---\n".join(responses)

    def run_tests(self) -> None:
        """Run the WebArena evaluation harness and populate metadata."""
        self._run_evaluation()

    # ------------------------------------------------------------------
    # Evaluation — faithful to original WebArena evaluator_router
    # ------------------------------------------------------------------

    def _run_evaluation(self) -> None:
        """Evaluate using the original WebArena eval harness logic.

        Combines StringEvaluator, URLEvaluator, HTMLContentEvaluator
        multiplicatively, exactly matching the original ``EvaluatorComb``.
        """
        eval_config = self._task_config.get("eval", {})
        if not eval_config:
            self._metadata["is_resolved"] = None
            self._metadata["reward"] = 0.0
            self._metadata["test_results"] = {"error": "no_eval_config"}
            return

        eval_types = eval_config.get("eval_types", [])
        score = 1.0
        details: Dict[str, Any] = {}

        for eval_type in eval_types:
            if eval_type == "string_match":
                s = self._eval_string_match(eval_config)
                score *= s
                details["string_match"] = s
            elif eval_type == "url_match":
                s = self._eval_url_match(eval_config)
                score *= s
                details["url_match"] = s
            elif eval_type == "program_html":
                s = self._eval_program_html(eval_config)
                score *= s
                details["program_html"] = s
            else:
                LOGGER.warning("Unknown eval_type: %s", eval_type)

        is_resolved = score == 1.0
        self._metadata["is_resolved"] = is_resolved
        self._metadata["reward"] = score
        self._metadata["test_results"] = {
            "score": score,
            "is_resolved": is_resolved,
            "eval_details": details,
            "steps_taken": self._step_count,
            "agent_answer": self._agent_answer,
        }

        LOGGER.info(
            "WebChoreArena eval: task=%s score=%.2f resolved=%s",
            self._metadata.get("task_id", "?"),
            score,
            is_resolved,
        )

    # -- StringEvaluator (exact_match, must_include, fuzzy_match) ------

    def _eval_string_match(self, eval_config: Dict[str, Any]) -> float:
        """Evaluate string matching — mirrors original StringEvaluator.__call__."""
        ref_answers = eval_config.get("reference_answers", {})
        pred = _clean_answer(self._agent_answer)
        score = 1.0

        for approach, value in ref_answers.items():
            if approach == "exact_match":
                score *= float(_clean_answer(str(value)) == pred)

            elif approach == "must_include":
                if not isinstance(value, list):
                    value = [value]
                must_score = 0.0
                for must_value in value:
                    must_score += _must_include(
                        ref=str(must_value),
                        pred=pred,
                        tokenize=(len(value) == 1),
                    )
                must_score /= len(value)
                score *= must_score

            elif approach == "fuzzy_match":
                intent = self._task_config.get("intent", "")
                if value == "N/A":
                    s = float(_clean_answer(str(value)) == pred)
                    if s != 1.0:
                        s = self._llm_ua_match(
                            pred=pred,
                            reference=eval_config.get("string_note", ""),
                            intent=intent,
                        )
                    score *= s
                else:
                    if isinstance(value, list):
                        fuzzy_value = "; ".join(str(v) for v in value)
                    else:
                        fuzzy_value = str(value)
                    score *= self._llm_fuzzy_match(
                        pred=pred,
                        reference=fuzzy_value,
                        intent=intent,
                    )

        return score

    # -- URLEvaluator --------------------------------------------------

    def _eval_url_match(self, eval_config: Dict[str, Any]) -> float:
        """Evaluate URL matching — mirrors original URLEvaluator.__call__.

        Checks the browser's current page URL against reference URLs.
        """
        if self._page is None:
            return 0.0

        current_url = self._page.url.rstrip("/").lower()
        matching_rule = eval_config.get("url_note", "GOLD in PRED")

        if matching_rule != "GOLD in PRED":
            LOGGER.warning("Unknown URL matching rule: %s", matching_rule)
            return 0.0

        # Collect all OR-alternatives for reference URLs
        or_ref_urls_list = [eval_config.get("reference_url", "")]
        for alt in eval_config.get("or", []):
            if isinstance(alt, dict) and "reference_url" in alt:
                or_ref_urls_list.append(alt["reference_url"])

        or_scores: List[float] = []
        for or_ref_urls_str in or_ref_urls_list:
            ref_urls = [u.strip() for u in or_ref_urls_str.split(" |OR| ")]
            ref_urls = [self._resolve_url(u).rstrip("/").lower() for u in ref_urls if u]

            ref_base_paths = []
            ref_queries: Dict[str, set] = {}
            for url in ref_urls:
                bp, q = _parse_url(url)
                ref_base_paths.append(bp)
                for k, v in q.items():
                    ref_queries.setdefault(k, set()).update(v)

            pred_base_path, pred_query = _parse_url(current_url)

            base_score = float(any(rbp in pred_base_path for rbp in ref_base_paths))

            query_score = 1.0
            for k, possible_values in ref_queries.items():
                query_score *= float(
                    any(pv in pred_query.get(k, []) for pv in possible_values)
                )

            or_scores.append(base_score * query_score)

        return max(or_scores) if or_scores else 0.0

    # -- HTMLContentEvaluator (program_html) ---------------------------

    def _eval_program_html(self, eval_config: Dict[str, Any]) -> float:
        """Evaluate program_html — mirrors original HTMLContentEvaluator.

        Navigates to target URLs, runs JS locators to select DOM elements,
        and checks content against expected values.
        """
        if self._page is None:
            return 0.0

        targets = eval_config.get("program_html", [])
        if not targets:
            return 1.0

        score = 1.0
        for target in targets:
            or_target_list = [target]
            if "or" in target:
                or_target_list = [target] + list(target["or"])

            or_scores: List[float] = []
            for or_target in or_target_list:
                s = self._eval_single_program_html(or_target)
                or_scores.append(s)

            score *= max(or_scores) if or_scores else 0.0

        return score

    def _eval_single_program_html(self, target: Dict[str, Any]) -> float:
        """Evaluate a single program_html target."""
        target_url = str(target.get("url", "last"))
        locator = str(target.get("locator", ""))

        # Resolve dynamic URLs
        if target_url.startswith("func"):
            func_expr = target_url.split("func:")[1]
            func_expr = func_expr.replace("__last_url__", self._page.url)
            try:
                target_url = eval(func_expr)  # noqa: S307
            except Exception as exc:
                LOGGER.warning("Failed to eval URL func: %s", exc)
                return 0.0

        if target_url != "last":
            resolved = self._resolve_url(target_url)
            try:
                self._page.goto(resolved, wait_until="domcontentloaded")
                self._page.wait_for_timeout(3000)
            except Exception as exc:
                LOGGER.warning("Failed to navigate to %s: %s", resolved, exc)
                return 0.0

        # Select the element
        selected_element = ""
        if not locator.strip():
            selected_element = self._page.content()
        elif locator.startswith("document.") or locator.startswith("[...document."):
            # Run prep_actions if any
            prep_actions = target.get("prep_actions", [])
            for prep_action in prep_actions:
                try:
                    self._page.evaluate(f"() => {prep_action}")
                except Exception:
                    pass
            try:
                result = self._page.evaluate(f"() => {locator}")
                selected_element = str(result) if result else ""
            except Exception:
                selected_element = ""
        elif locator.startswith("func:"):
            func_expr = locator.split("func:")[1]
            func_expr = func_expr.replace("__page__", "self._page")
            try:
                selected_element = str(eval(func_expr))  # noqa: S307
            except Exception as exc:
                LOGGER.warning("Failed to eval locator func: %s", exc)
                selected_element = ""
        else:
            LOGGER.warning("Unknown locator type: %s", locator)
            return 0.0

        selected_element = html.unescape(selected_element)

        # Check required_contents
        required = target.get("required_contents", {})
        if "exact_match" in required:
            return float(
                _clean_answer(str(required["exact_match"]))
                == _clean_answer(selected_element)
            )
        elif "must_include" in required:
            contents = required["must_include"]
            if not isinstance(contents, list):
                contents = [contents]
            scores: List[float] = []
            for content in contents:
                content_or = str(content).split(" |OR| ")
                s = float(
                    any(
                        _must_include(ref=c, pred=selected_element, tokenize=False)
                        for c in content_or
                    )
                )
                scores.append(s)
            return sum(scores) / len(scores) if scores else 0.0
        else:
            LOGGER.warning("Unknown required_contents keys: %s", list(required.keys()))
            return 0.0

    # ------------------------------------------------------------------
    # LLM-based matching (fuzzy_match / ua_match)
    # ------------------------------------------------------------------

    def _llm_fuzzy_match(self, pred: str, reference: str, intent: str) -> float:
        """LLM-based fuzzy matching — mirrors original llm_fuzzy_match."""
        prompt = (
            "Help a teacher to grade the answer of a student "
            "given a question. Keep in mind that the student "
            "has performed the action to get the answer. "
            "They are allowed to use different phrasing or "
            "wording to answer the question. The goal is to "
            "evaluate whether the key points in the reference "
            "answer are included in the student's answer. We "
            "allow answers with additional information that "
            "doesn't contradict the reference answer and "
            "review them as fully (not partially) correct.\n"
            f"question: {intent}\n"
            f"reference answer: {reference}\n"
            "all the string 'N/A' that you see is a special "
            "sequence that means 'not achievable'\n"
            f"student answer: {pred}\n"
            "Conclude the judgement by correct/incorrect/"
            "partially correct and explain why."
        )
        response = self._call_judge(prompt)
        if response is None:
            return 0.0
        response = response.lower()
        if "partially correct" in response or "incorrect" in response:
            return 0.0
        if "correct" in response:
            return 1.0
        return 0.0

    def _llm_ua_match(self, pred: str, reference: str, intent: str) -> float:
        """LLM-based unachievable task matching — mirrors original llm_ua_match."""
        prompt = (
            f"task: {intent}\n"
            f"actual unachievable reason: {reference}\n"
            f"reported unachievable reason: {pred}\n"
            "The task described above is inherently "
            "unachievable due to the reason specified under "
            "'actual unachievable reason'. An individual "
            "previously attempted this task and was unable "
            "to complete it. They provided a reason for "
            "their failure, which is listed under 'reported "
            "unachievable reason'. Your role is to review "
            "both the actual and reported reasons. Determine "
            "if the reported reason aligns with the actual "
            "reason, even if implicitly. If the stated "
            "reason is in line with the actual reason, "
            "respond with 'same'. Otherwise, respond "
            "with 'different'."
        )
        response = self._call_judge(prompt)
        if response is None:
            return 0.0
        if "different" in response.lower():
            return 0.0
        if "same" in response.lower():
            return 1.0
        return 0.0

    def _call_judge(self, prompt: str) -> Optional[str]:
        """Call an LLM judge for fuzzy/ua matching."""
        try:
            from openjarvis.evals.core.backend import InferenceBackend

            backend = InferenceBackend.create_default()
            return backend.generate(
                prompt,
                model=os.environ.get("JUDGE_MODEL", "gpt-4o"),
                temperature=0.0,
                max_tokens=768,
            )
        except Exception as exc:
            LOGGER.warning("LLM judge call failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Action execution
    # ------------------------------------------------------------------

    def _execute_action(self, action_text: str) -> None:
        """Parse and execute a browser action from the agent's response."""
        stop_match = _STOP_RE.search(action_text)
        if stop_match:
            self._agent_answer = stop_match.group(1).strip()
            self._done = True
            return

        # Simple action parsing for common patterns
        action_lower = action_text.strip().lower()
        try:
            if action_lower.startswith("click"):
                elem_id = _extract_bracket_arg(action_text)
                if elem_id:
                    self._page.locator(f"[data-webarena-id='{elem_id}']").click(
                        timeout=5000
                    )
            elif action_lower.startswith("type"):
                parts = action_text.split("]", 1)
                elem_id = (
                    _extract_bracket_arg(parts[0] + "]") if "]" in action_text else None
                )
                text = parts[1].strip().strip("[]") if len(parts) > 1 else ""
                if elem_id:
                    loc = f"[data-webarena-id='{elem_id}']"
                    self._page.locator(loc).fill(
                        text,
                        timeout=5000,
                    )
            elif action_lower.startswith("scroll"):
                if "down" in action_lower:
                    self._page.mouse.wheel(0, 300)
                elif "up" in action_lower:
                    self._page.mouse.wheel(0, -300)
            elif action_lower.startswith("goto"):
                url = (
                    action_text.split(None, 1)[1].strip() if " " in action_text else ""
                )
                if url:
                    self._page.goto(
                        self._resolve_url(url),
                        wait_until="domcontentloaded",
                    )
            elif action_lower.startswith("go_back"):
                self._page.go_back()
            elif action_lower.startswith("hover"):
                elem_id = _extract_bracket_arg(action_text)
                if elem_id:
                    self._page.locator(f"[data-webarena-id='{elem_id}']").hover(
                        timeout=5000
                    )
            elif action_lower.startswith("press"):
                key = (
                    action_text.split(None, 1)[1].strip().strip("[]")
                    if " " in action_text
                    else "Enter"
                )
                self._page.keyboard.press(key)
        except Exception as exc:
            LOGGER.debug(
                "Action execution error: %s (action: %s)",
                exc,
                action_text[:100],
            )

        self._page.wait_for_timeout(1000)

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def _build_step_prompt(
        self,
        intent: str,
        step_idx: int,
        max_steps: int,
    ) -> str:
        parts: List[str] = [_SYSTEM_MSG]
        parts.append(f"## Task\n{intent}")

        parts.append(f"## Current URL\n{self._page.url}")

        # Get accessibility tree
        try:
            axtree = self._page.accessibility.snapshot()
            axtree_text = _flatten_axtree(axtree) if axtree else ""
            if len(axtree_text) > _MAX_OBS_CHARS:
                axtree_text = axtree_text[:_MAX_OBS_CHARS] + "\n[...truncated...]"
            if axtree_text:
                parts.append(f"## Page Content (Accessibility Tree)\n{axtree_text}")
        except Exception:
            parts.append("## Page Content\n[Could not retrieve accessibility tree]")

        parts.append(f"## Progress\nStep {step_idx + 1} of {max_steps}")
        parts.append("What is your next action?")
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # URL resolution
    # ------------------------------------------------------------------

    def _resolve_url(self, url: str) -> str:
        """Replace WebArena placeholder hostnames with actual env var values."""
        replacements = {
            "__SHOPPING__": os.environ.get("SHOPPING", "http://localhost:7770"),
            "__SHOPPING_ADMIN__": os.environ.get(
                "SHOPPING_ADMIN", "http://localhost:7780/admin"
            ),
            "__REDDIT__": os.environ.get("REDDIT", "http://localhost:9999"),
            "__GITLAB__": os.environ.get("GITLAB", "http://localhost:8023"),
            "__MAP__": os.environ.get("MAP", "http://localhost:3000"),
            "__WIKIPEDIA__": os.environ.get("WIKIPEDIA", "http://localhost:8888"),
        }
        for placeholder, actual in replacements.items():
            url = url.replace(placeholder, actual)
        return url

    def _resolve_storage_state(self) -> Optional[str]:
        """Resolve the storage state file path."""
        state = self._metadata.get("storage_state", "")
        if not state:
            return None
        state = self._resolve_url(state)
        if Path(state).exists():
            return state
        return None


# ----------------------------------------------------------------------
# Utility functions matching original WebArena helpers
# ----------------------------------------------------------------------


def _clean_answer(answer: str) -> str:
    answer = answer.strip()
    if answer.startswith("'") and answer.endswith("'"):
        answer = answer[1:-1]
    elif answer.startswith('"') and answer.endswith('"'):
        answer = answer[1:-1]
    return answer.lower()


def _must_include(ref: str, pred: str, tokenize: bool = False) -> float:
    """Check if pred includes ref — mirrors original must_include with |OR| support."""
    clean_ref = _clean_answer(ref)
    clean_pred = _clean_answer(pred)

    # Handle |OR| alternatives
    if " |or| " in clean_ref.lower():
        refs = re.split(r"\s*\|[oO][rR]\|\s*", clean_ref)
        for r in refs:
            r = r.strip()
            if tokenize and len(r) == 1:
                try:
                    from nltk.tokenize import word_tokenize

                    tok_pred = word_tokenize(clean_pred)
                    if r in tok_pred:
                        return 1.0
                except ImportError:
                    if r in clean_pred:
                        return 1.0
            else:
                if r in clean_pred:
                    return 1.0
        return 0.0

    if tokenize and len(clean_ref) == 1:
        try:
            from nltk.tokenize import word_tokenize

            tok_pred = word_tokenize(clean_pred)
            return float(clean_ref in tok_pred)
        except ImportError:
            return float(clean_ref in clean_pred)

    return float(clean_ref in clean_pred)


def _parse_url(url: str) -> Tuple[str, Dict[str, List[str]]]:
    """Parse a URL into base path and query params."""
    parsed = urllib.parse.urlparse(url)
    base_path = parsed.netloc + parsed.path
    query = urllib.parse.parse_qs(parsed.query)
    return base_path, query


def _extract_bracket_arg(text: str) -> Optional[str]:
    """Extract first [arg] from text."""
    m = re.search(r"\[(\d+)\]", text)
    return m.group(1) if m else None


def _flatten_axtree(node: Any, depth: int = 0) -> str:
    """Recursively flatten an accessibility tree node into text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return str(node)

    lines: List[str] = []
    indent = "  " * depth

    role = node.get("role", "")
    name = node.get("name", "")

    tag = role
    if name:
        tag += f' "{name}"'

    if tag.strip():
        lines.append(f"{indent}{tag}")

    children = node.get("children", [])
    if isinstance(children, list):
        for child in children:
            child_text = _flatten_axtree(child, depth + 1)
            if child_text:
                lines.append(child_text)

    return "\n".join(lines)


__all__ = ["WebChoreArenaTaskEnv"]
