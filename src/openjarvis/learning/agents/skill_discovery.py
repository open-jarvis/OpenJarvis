"""Skill discovery -- mine recurring tool sequences from traces."""

from __future__ import annotations

import json
import re
import urllib.parse
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from typing import Any, Dict, List, Tuple

from openjarvis.skills.types import SkillManifest, SkillStep

_BOOKKEEPING_TOOLS = {"skill_manage", "memory_store"}
_SECRET_HEADER_NAMES = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "proxy-authorization",
}
_MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_READ_METHODS = {"GET", "HEAD"}
_MISSING = object()


@dataclass(slots=True)
class DiscoveredSkill:
    """A skill discovered from trace analysis."""

    name: str
    description: str
    tool_sequence: List[str]  # ordered tool names
    frequency: int  # how often this sequence appeared
    avg_outcome: float  # average outcome score
    example_inputs: List[str] = field(default_factory=list)


class SkillDiscovery:
    """Mine recurring tool sequences from trace data to auto-generate skills.

    Analyzes TraceStore data for patterns like:
    - "web_search -> file_write" (research-then-save)
    - "file_read -> calculator -> file_write" (read-compute-save)

    When a sequence appears >= min_frequency times with positive outcomes,
    it's surfaced as a DiscoveredSkill that can be registered.
    """

    def __init__(
        self,
        *,
        min_frequency: int = 3,
        min_sequence_length: int = 2,
        max_sequence_length: int = 4,
        min_outcome: float = 0.5,
    ) -> None:
        self._min_freq = min_frequency
        self._min_len = min_sequence_length
        self._max_len = max_sequence_length
        self._min_outcome = min_outcome
        self._discovered: List[DiscoveredSkill] = []

    def analyze_traces(self, traces: List[Any]) -> List[DiscoveredSkill]:
        """Analyze a list of traces for recurring tool sequences.

        Parameters
        ----------
        traces:
            List of Trace objects (or dicts with 'steps' and 'outcome' keys).
            Each trace should have steps with 'step_type' and 'tool_name'.

        Returns
        -------
        List of DiscoveredSkill objects meeting frequency and outcome thresholds.
        """
        # Extract tool sequences from traces
        sequence_data: Dict[Tuple[str, ...], List[float]] = defaultdict(list)
        sequence_inputs: Dict[Tuple[str, ...], List[str]] = defaultdict(list)

        for trace in traces:
            metadata = self._trace_value(trace, "metadata", {}) or {}
            if metadata.get("status", "completed") != "completed":
                continue
            tool_calls = self._extract_tool_sequence(trace)
            outcome = self._extract_outcome(trace)
            query = self._extract_query(trace)

            if len(tool_calls) < self._min_len:
                continue

            # Generate all subsequences of valid length
            upper = min(self._max_len + 1, len(tool_calls) + 1)
            for length in range(self._min_len, upper):
                for start in range(len(tool_calls) - length + 1):
                    seq = tuple(tool_calls[start : start + length])
                    sequence_data[seq].append(outcome)
                    if query and len(sequence_inputs[seq]) < 3:
                        sequence_inputs[seq].append(query)

        # Filter by frequency and outcome
        discovered = []
        for seq, outcomes in sequence_data.items():
            freq = len(outcomes)
            avg_outcome = sum(outcomes) / len(outcomes) if outcomes else 0.0

            if freq >= self._min_freq and avg_outcome >= self._min_outcome:
                name = "_".join(seq)
                desc = f"Auto-discovered skill: {' -> '.join(seq)} (seen {freq} times)"
                discovered.append(
                    DiscoveredSkill(
                        name=name,
                        description=desc,
                        tool_sequence=list(seq),
                        frequency=freq,
                        avg_outcome=avg_outcome,
                        example_inputs=sequence_inputs.get(seq, []),
                    )
                )

        # Sort by frequency * outcome (quality score)
        discovered.sort(key=lambda s: s.frequency * s.avg_outcome, reverse=True)
        self._discovered = discovered
        return discovered

    def _extract_tool_sequence(self, trace: Any) -> List[str]:
        """Extract ordered list of tool names from a trace."""
        if isinstance(trace, dict):
            steps = trace.get("steps", [])
        elif hasattr(trace, "steps"):
            steps = trace.steps
        else:
            return []

        tools = []
        for step in steps:
            if isinstance(step, dict):
                if step.get("step_type") == "tool_call":
                    name = step.get("tool_name", step.get("name", ""))
                    if name:
                        tools.append(name)
            elif hasattr(step, "step_type"):
                st = step.step_type
                is_tool = str(st) == "tool_call" or (
                    hasattr(st, "value") and st.value == "tool_call"
                )
                if is_tool:
                    name = getattr(
                        step,
                        "tool_name",
                        getattr(step, "name", ""),
                    )
                    # Also check step.input dict for tool name (TraceStep format)
                    if not name:
                        step_input = getattr(step, "input", {}) or {}
                        if isinstance(step_input, dict):
                            name = step_input.get("tool", "") or ""
                    if name:
                        tools.append(name)
        return tools

    def _extract_outcome(self, trace: Any) -> float:
        """Extract outcome score from a trace.

        Handles both numeric outcome scores and string labels
        ("success" / "failure").  Falls back to the ``feedback`` field when
        present, then defaults to 0.0.
        """
        if isinstance(trace, dict):
            raw = trace.get("outcome")
            if raw is None:
                return float(trace.get("feedback", 0.0) or 0.0)
        else:
            raw = getattr(trace, "outcome", None)
            if raw is None:
                return float(getattr(trace, "feedback", 0.0) or 0.0)

        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, str):
            lraw = raw.lower()
            if lraw == "success":
                return 1.0
            if lraw == "failure":
                return 0.0
            try:
                return float(raw)
            except ValueError:
                return 0.0
        return 0.0

    def _extract_query(self, trace: Any) -> str:
        """Extract the original query from a trace."""
        if isinstance(trace, dict):
            return trace.get("query", "")
        return getattr(trace, "query", "")

    @property
    def discovered_skills(self) -> List[DiscoveredSkill]:
        """Return the most recently discovered skills."""
        return list(self._discovered)

    def to_skill_manifests(self) -> List[Dict[str, Any]]:
        """Convert discovered skills to TOML-compatible manifest dicts."""
        manifests = []
        for skill in self._discovered:
            manifests.append(
                {
                    "name": skill.name,
                    "description": skill.description,
                    "steps": [
                        {"tool": tool, "params": {}} for tool in skill.tool_sequence
                    ],
                    "metadata": {
                        "auto_discovered": True,
                        "frequency": skill.frequency,
                        "avg_outcome": skill.avg_outcome,
                    },
                }
            )
        return manifests

    def is_successful_transaction(self, trace: Any) -> bool:
        """Return whether *trace* is safe to learn as a verified transaction.

        This classifier is intentionally side-effect-free: a trace must contain
        a non-empty completed answer, every tool call must have succeeded, and
        a successful HTTP mutation must be followed by a successful HTTP read.
        """
        if not str(self._trace_value(trace, "result", "") or "").strip():
            return False
        outcome = self._trace_value(trace, "outcome", None)
        if outcome is not None and str(outcome).lower() != "success":
            return False

        mutation_seen = False
        verification_seen = False
        for step in self._tool_steps(trace):
            if not self._step_output(step).get("success", False):
                return False
            tool_name = self._tool_name(step)
            arguments = self._step_arguments(step)
            if tool_name == "repl" or self._has_secret_headers(arguments):
                return False
            if tool_name != "http_request":
                continue
            method = str(arguments.get("method", "GET")).upper()
            if method in _MUTATION_METHODS:
                mutation_seen = True
            elif mutation_seen and method in _READ_METHODS:
                verification_seen = True
        return mutation_seen and verification_seen

    def parameterize_trace(self, trace: Any) -> SkillManifest | None:
        """Convert one eligible trace into a generic executable manifest.

        The resulting steps retain their captured generic-tool arguments, except
        scalar output values reused later in the trace become dotted references
        to the preceding step's JSON result.
        """
        is_transaction = self.is_successful_transaction(trace)
        is_read = self.is_successful_read_display(trace)
        if not is_transaction and not is_read:
            return None

        query = self._normalized_intent(str(self._trace_value(trace, "query", "")))
        kind = "transaction" if is_transaction else "read"
        name = f"learned-{kind}-{sha256(query.encode()).hexdigest()[:12]}"

        if is_read:
            return self._parameterize_read_display(trace, name=name, query=query)

        learned_steps: List[SkillStep] = []
        previous_scalars: List[Tuple[str, Any]] = []

        for step in self._tool_steps(trace):
            tool_name = self._tool_name(step)
            if tool_name in _BOOKKEEPING_TOOLS or tool_name.startswith("browser_"):
                continue
            arguments = self._parameterize_arguments(
                self._step_arguments(step), previous_scalars
            )
            output_key = f"step_{len(learned_steps)}"
            learned_steps.append(
                SkillStep(
                    tool_name=tool_name,
                    arguments_template=json.dumps(arguments, ensure_ascii=False),
                    output_key=output_key,
                )
            )
            previous_scalars.extend(
                self._json_scalars(self._step_output(step).get("result"), output_key)
            )

        return SkillManifest(
            name=name,
            description=f"Learned {kind}: {query}",
            steps=learned_steps,
            metadata={
                "openjarvis": {"source": "learned"},
                "intent": query,
                "requires_fresh_confirmation": is_transaction,
            },
        )

    def _parameterize_read_display(
        self, trace: Any, *, name: str, query: str
    ) -> SkillManifest | None:
        evidence = self._validated_read_evidence(trace)
        if evidence is None:
            return None
        read, display, request_arguments, input_schema, recipe = evidence
        reads = [read]
        learned_steps: List[SkillStep] = []
        source_values: List[Tuple[str, Any]] = []
        for index, read in enumerate(reads):
            output_key = f"step_{index}"
            learned_steps.append(
                SkillStep(
                    tool_name="http_request",
                    arguments_template=json.dumps(
                        self._parameterize_current_date(request_arguments),
                        ensure_ascii=False,
                    ),
                    output_key=output_key,
                )
            )
            source_values.extend(
                self._json_values(self._step_output(read).get("result"), output_key)
            )

        raw_display_arguments = self._step_arguments(display)
        evidence_native_menu = (
            len(reads) == 1 and self._tool_name(display) == "display_menu"
            and raw_display_arguments == {"all_from_latest_http": True}
        )
        if evidence_native_menu:
            display_arguments, grounded = raw_display_arguments, True
        else:
            display_arguments, grounded = self._ground_display_arguments(
                raw_display_arguments,
                source_values,
            )
        if not grounded:
            return None
        display_arguments["result_complete"] = True

        learned_steps.append(
            SkillStep(
                tool_name=self._tool_name(display),
                arguments_template=json.dumps(display_arguments, ensure_ascii=False),
                output_key=f"step_{len(learned_steps)}",
            )
        )

        return SkillManifest(
            name=name,
            description=f"Learned read: {query}",
            steps=learned_steps,
            input_schema=input_schema,
            metadata={
                "openjarvis": {
                    "source": "learned",
                    "request_recipe": recipe,
                },
                "intent": query,
                "requires_fresh_confirmation": False,
            },
        )

    def is_successful_read_display(self, trace: Any) -> bool:
        """Return whether a displayed live read is safe to reuse as a recipe."""
        if not str(self._trace_value(trace, "result", "") or "").strip():
            return False
        outcome = self._trace_value(trace, "outcome", None)
        if outcome is not None and str(outcome).lower() != "success":
            return False

        return self._validated_read_evidence(trace) is not None

    def _validated_read_evidence(
        self, trace: Any
    ) -> Tuple[Any, Any, Dict[str, Any], Dict[str, Any], Dict[str, Any]] | None:
        steps = [
            step
            for step in self._tool_steps(trace)
            if self._tool_name(step) not in _BOOKKEEPING_TOOLS
        ]
        names = [self._tool_name(step) for step in steps]
        if (
            len(steps) != 6
            or names[0] != "browser_network_requests"
            or names[1] not in {"browser_fill_form", "browser_click"}
            or names[2] != "browser_network_requests"
            or names[3:] != [
                "http_request",
                "browser_verify_list_visible",
                "display_menu",
            ]
        ):
            return None
        if any(not self._step_output(step).get("success", False) for step in steps):
            return None
        if any(self._has_secret_headers(self._step_arguments(step)) for step in steps):
            return None

        before = self._network_requests(steps[0])
        after = self._network_requests(steps[2])
        if before is None or after is None:
            return None
        before_keys = {self._request_key(request) for request in before}
        changed = [
            request
            for request in after
            if self._request_key(request) not in before_keys
        ]
        if len(changed) != 1:
            return None
        observed = changed[0]
        observed_method = str(observed.get("method", "")).upper()
        observed_url = observed.get("url")
        if observed_method not in _READ_METHODS or not isinstance(observed_url, str):
            return None

        changed_parameter = self._changed_query_parameter(before, observed)
        if changed_parameter is None:
            return None
        parameter_name, parameter_value = changed_parameter
        interaction_strings = {
            value
            for value in self._step_arguments(steps[1]).values()
            if isinstance(value, str)
        }
        if parameter_value not in interaction_strings:
            return None

        read = steps[3]
        replay = self._step_arguments(read)
        if (
            str(replay.get("method", "")).upper() != observed_method
            or replay.get("url") != observed_url
            or self._has_secret_headers(replay)
        ):
            return None
        read_metadata = self._step_metadata(read)
        status_code = read_metadata.get("status_code")
        content_type = read_metadata.get("content_type")
        final_url = read_metadata.get("final_url")
        if (
            type(status_code) is not int
            or not 200 <= status_code < 300
            or not isinstance(content_type, str)
            or not content_type.startswith("application/json")
            or read_metadata.get("truncated") is not False
            or self._origin(final_url) != self._origin(observed_url)
        ):
            return None
        response = self._json_output(read)
        verification = self._json_output(steps[4])
        display_arguments = self._step_arguments(steps[5])
        display_items = display_arguments.get("items")
        if (
            response is _MISSING
            or not isinstance(verification, dict)
            or verification.get("has_pagination") is not False
            or not isinstance(display_items, list)
            or display_arguments.get("result_complete") is not True
        ):
            return None
        browser_items = verification.get("items")
        browser_count = verification.get("count")
        completeness = verification.get("complete")
        if (
            not isinstance(browser_items, list)
            or type(browser_count) is not int
            or browser_count != len(browser_items)
            or browser_count != len(display_items)
            or not isinstance(completeness, dict)
            or set(completeness) != {"path", "equals"}
            or not isinstance(completeness["path"], str)
            or self._resolve_path(response, completeness["path"])
            is not completeness["equals"]
        ):
            return None
        browser_ids = [
            item.get("id") if isinstance(item, dict) else None for item in browser_items
        ]
        display_ids = [
            item.get("id") if isinstance(item, dict) else None for item in display_items
        ]
        if (
            any(not isinstance(item, str) or not item for item in browser_ids)
            or len(browser_ids) != len(set(browser_ids))
            or browser_ids != display_ids
        ):
            return None

        response_list = self._corresponding_list(response, browser_ids)
        if response_list is None:
            return None
        list_path, _rows = response_list

        parameterized_request = dict(replay)
        parameterized_request["url"] = self._parameterized_url(
            observed_url, parameter_name
        )
        required_paths = [{"path": list_path, "type": "array"}]
        required_paths.extend(self._boolean_paths(response))
        recipe = {
            "origin": self._origin(observed_url),
            "method": observed_method,
            "read_only": True,
            "captured_from": "browser_network_requests",
            "allowed_content_types": ["application/json"],
            "required_paths_json": json.dumps(required_paths),
        }
        input_schema = {
            "type": "object",
            "properties": {
                parameter_name: {"type": "string", "minLength": 1}
            },
            "required": [parameter_name],
            "additionalProperties": False,
        }
        return read, steps[5], parameterized_request, input_schema, recipe

    @classmethod
    def _network_requests(cls, step: Any) -> List[Dict[str, Any]] | None:
        payload = cls._json_output(step)
        if not isinstance(payload, dict) or not isinstance(
            payload.get("requests"), list
        ):
            return None
        requests = payload["requests"]
        return requests if all(isinstance(item, dict) for item in requests) else None

    @staticmethod
    def _request_key(request: Dict[str, Any]) -> Tuple[str, str]:
        return str(request.get("method", "")).upper(), str(request.get("url", ""))

    @classmethod
    def _changed_query_parameter(
        cls, before: List[Dict[str, Any]], observed: Dict[str, Any]
    ) -> Tuple[str, str] | None:
        observed_url = observed.get("url")
        if not isinstance(observed_url, str):
            return None
        observed_parts = urllib.parse.urlsplit(observed_url)
        observed_query = dict(
            urllib.parse.parse_qsl(observed_parts.query, keep_blank_values=True)
        )
        for request in before:
            url = request.get("url")
            if (
                not isinstance(url, str)
                or str(request.get("method", "")).upper()
                != str(observed.get("method", "")).upper()
            ):
                continue
            parts = urllib.parse.urlsplit(url)
            if (parts.scheme, parts.netloc, parts.path) != (
                observed_parts.scheme,
                observed_parts.netloc,
                observed_parts.path,
            ):
                continue
            prior_query = dict(
                urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
            )
            changed = [
                key
                for key in set(prior_query) | set(observed_query)
                if prior_query.get(key) != observed_query.get(key)
            ]
            if len(changed) == 1 and observed_query.get(changed[0]):
                return changed[0], observed_query[changed[0]]
        return None

    @staticmethod
    def _parameterized_url(url: str, parameter_name: str) -> str:
        parts = urllib.parse.urlsplit(url)
        pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        query = "&".join(
            f"{urllib.parse.quote(name, safe='')}="
            + (
                f"{{{name}|urlencode}}"
                if name == parameter_name
                else urllib.parse.quote(value, safe="")
            )
            for name, value in pairs
        )
        return urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc, parts.path, query, parts.fragment)
        )

    @staticmethod
    def _origin(url: Any) -> str:
        if not isinstance(url, str):
            return ""
        try:
            parts = urllib.parse.urlsplit(url)
            port = parts.port
        except ValueError:
            return ""
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
        ):
            return ""
        return f"{parts.scheme}://{parts.hostname}{f':{port}' if port else ''}"

    @classmethod
    def _json_output(cls, step: Any) -> Any:
        result = cls._step_output(step).get("result")
        if not isinstance(result, str):
            return _MISSING
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return _MISSING

    @classmethod
    def _corresponding_list(
        cls, response: Any, identities: List[str]
    ) -> Tuple[str, List[Any]] | None:
        candidates: List[Tuple[str, List[Any]]] = []

        def visit(value: Any, path: str) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    visit(child, f"{path}.{key}" if path else key)
            elif isinstance(value, list):
                candidates.append((path, value))
                for index, child in enumerate(value):
                    visit(child, f"{path}.{index}")

        visit(response, "")
        for path, rows in candidates:
            if len(rows) != len(identities):
                continue
            if all(
                any(
                    identity == value
                    or (
                        isinstance(value, str)
                        and identity.strip() == value.strip()
                    )
                    for value in cls._scalar_values(row)
                )
                for identity, row in zip(identities, rows)
            ):
                return path, rows
        return None

    @staticmethod
    def _scalar_values(value: Any) -> set[Any]:
        values: set[Any] = set()

        def visit(child: Any) -> None:
            if isinstance(child, dict):
                for nested in child.values():
                    visit(nested)
            elif isinstance(child, list):
                for nested in child:
                    visit(nested)
            elif isinstance(child, (str, int, float, bool)):
                values.add(child)

        visit(value)
        return values

    @staticmethod
    def _resolve_path(value: Any, path: str) -> Any:
        current = value
        for segment in path.split("."):
            if isinstance(current, dict) and segment in current:
                current = current[segment]
            elif (
                isinstance(current, list)
                and segment.isdigit()
                and int(segment) < len(current)
            ):
                current = current[int(segment)]
            else:
                return _MISSING
        return current

    @staticmethod
    def _boolean_paths(response: Any) -> List[Dict[str, str]]:
        paths: List[Dict[str, str]] = []

        def visit(value: Any, path: str) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    visit(child, f"{path}.{key}" if path else key)
            elif isinstance(value, bool):
                paths.append({"path": path, "type": "boolean"})

        visit(response, "")
        return paths

    @staticmethod
    def _normalized_intent(query: str) -> str:
        return re.sub(r"\s+", " ", query.strip().lower())

    @staticmethod
    def _trace_value(trace: Any, key: str, default: Any) -> Any:
        if isinstance(trace, dict):
            return trace.get(key, default)
        return getattr(trace, key, default)

    @classmethod
    def _tool_steps(cls, trace: Any) -> List[Any]:
        steps = cls._trace_value(trace, "steps", []) or []
        return [step for step in steps if cls._is_tool_step(step)]

    @staticmethod
    def _is_tool_step(step: Any) -> bool:
        if isinstance(step, dict):
            step_type = step.get("step_type")
        else:
            step_type = getattr(step, "step_type", "")
        return str(getattr(step_type, "value", step_type)) == "tool_call"

    @staticmethod
    def _step_input(step: Any) -> Dict[str, Any]:
        if isinstance(step, dict):
            raw = step.get("input", {})
        else:
            raw = getattr(step, "input", {})
        return raw if isinstance(raw, dict) else {}

    @classmethod
    def _tool_name(cls, step: Any) -> str:
        if isinstance(step, dict):
            return str(
                step.get("tool_name")
                or step.get("name")
                or cls._step_input(step).get("tool", "")
            )
        return str(
            getattr(step, "tool_name", "")
            or getattr(step, "name", "")
            or cls._step_input(step).get("tool", "")
        )

    @classmethod
    def _step_arguments(cls, step: Any) -> Dict[str, Any]:
        metadata = cls._step_metadata(step)
        raw = metadata.get("arguments")
        if not isinstance(raw, (dict, str)):
            raw = cls._step_input(step).get("arguments", {})
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    @staticmethod
    def _step_metadata(step: Any) -> Dict[str, Any]:
        if isinstance(step, dict):
            raw = step.get("metadata", {})
        else:
            raw = getattr(step, "metadata", {})
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    def _parameterize_current_date(arguments: Dict[str, Any]) -> Dict[str, Any]:
        today = datetime.now().astimezone().date().isoformat()

        def replace(value: Any) -> Any:
            if isinstance(value, dict):
                return {key: replace(child) for key, child in value.items()}
            if isinstance(value, list):
                return [replace(child) for child in value]
            if isinstance(value, str):
                return value.replace(today, "{today}")
            return value

        return replace(arguments)

    @staticmethod
    def _step_output(step: Any) -> Dict[str, Any]:
        if isinstance(step, dict):
            raw = step.get("output", {})
        else:
            raw = getattr(step, "output", {})
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    def _has_secret_headers(arguments: Dict[str, Any]) -> bool:
        headers = arguments.get("headers", {})
        if isinstance(headers, dict):
            return any(str(name).lower() in _SECRET_HEADER_NAMES for name in headers)
        if isinstance(headers, list):
            return any(
                isinstance(item, (list, tuple))
                and item
                and str(item[0]).lower() in _SECRET_HEADER_NAMES
                for item in headers
            )
        return False

    @classmethod
    def _json_scalars(cls, result: Any, root: str) -> List[Tuple[str, Any]]:
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                return []

        scalars: List[Tuple[str, Any]] = []

        def visit(value: Any, path: str) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    visit(child, f"{path}.{key}")
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, f"{path}.{index}")
            elif isinstance(value, str) and value:
                scalars.append((path, value))

        visit(result, root)
        return scalars

    @classmethod
    def _json_values(cls, result: Any, root: str) -> List[Tuple[str, Any]]:
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                return []

        values: List[Tuple[str, Any]] = []

        def visit(value: Any, path: str) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    visit(child, f"{path}.{key}")
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, f"{path}.{index}")
            elif value is not None:
                values.append((path, value))

        visit(result, root)
        return values

    @classmethod
    def _ground_display_arguments(
        cls,
        arguments: Dict[str, Any],
        source_values: List[Tuple[str, Any]],
    ) -> Tuple[Dict[str, Any], bool]:
        replacements = 0

        def scalar_equal(value: Any, source_value: Any) -> bool:
            if isinstance(value, str) and isinstance(source_value, str):
                return value.strip() == source_value.strip()
            return value == source_value

        def candidates(value: Any) -> List[str]:
            return [
                path
                for path, source_value in source_values
                if type(value) is type(source_value)
                and scalar_equal(value, source_value)
            ]

        def common_prefix(left: str, right: str) -> int:
            count = 0
            for left_part, right_part in zip(left.split("."), right.split(".")):
                if left_part != right_part:
                    break
                count += 1
            return count

        def best_path(value: Any, anchor: str, target_key: str = "") -> str | None:
            paths = candidates(value)
            if len(paths) == 1:
                return paths[0]
            if not paths or not anchor:
                return None
            scored = [(common_prefix(path, anchor), path) for path in paths]
            best_score = max(score for score, _path in scored)
            best = [path for score, path in scored if score == best_score]
            if target_key:
                semantic_matches = [
                    path for path in best if path.rsplit(".", 1)[-1] == target_key
                ]
                if len(semantic_matches) == 1:
                    return semantic_matches[0]
            return best[0] if best_score > 0 and len(best) == 1 else None

        def composed_string(
            value: str, anchor: str, target_key: str
        ) -> str | None:
            matches: List[Tuple[int, int, str]] = []
            source_strings = {
                source_value
                for _path, source_value in source_values
                if isinstance(source_value, str) and source_value
            }
            for source_value in source_strings:
                path = best_path(source_value, anchor)
                if path is None:
                    continue
                source_text = source_value.strip()
                if not source_text:
                    continue
                matches.extend(
                    (match.start(), match.end(), path)
                    for match in re.finditer(
                        re.escape(source_text), value, flags=re.IGNORECASE
                    )
                )

            def span_key(item: Tuple[int, int, str]) -> Tuple[int, int]:
                return (-(item[1] - item[0]), item[0])

            selected: List[Tuple[int, int, str]] = []
            for match in sorted(matches, key=span_key):
                overlaps = any(
                    match[0] < end and match[1] > start for start, end, _ in selected
                )
                if overlaps:
                    continue
                selected.append(match)
            if not selected:
                return None

            selected.sort()
            pieces: List[str] = []
            uncovered: List[str] = []
            cursor = 0
            for start, end, path in selected:
                pieces.append(value[cursor:start])
                uncovered.append(value[cursor:start])
                pieces.append(f"{{{path}}}")
                cursor = end
            pieces.append(value[cursor:])
            uncovered.append(value[cursor:])
            if any(character.isalnum() for character in "".join(uncovered)):
                if target_key == "name":
                    name_paths = [
                        (path, source_value)
                        for path, source_value in source_values
                        if path.endswith(".name")
                        and common_prefix(path, anchor) > 0
                        and isinstance(source_value, str)
                        and source_value.strip().casefold() in value.casefold()
                    ]
                    name_paths.sort(key=lambda item: len(item[1]), reverse=True)
                    if name_paths:
                        return f"{{{name_paths[0][0]}}}"
                return None
            return "".join(pieces)

        def record_anchor(value: Dict[str, Any], inherited: str) -> str:
            for key in ("id", "slug", "name"):
                if key not in value:
                    continue
                paths = candidates(value[key])
                if len(paths) == 1:
                    return paths[0].rsplit(".", 1)[0]
            return inherited

        def replace(value: Any, anchor: str = "", target_key: str = "") -> Any:
            nonlocal replacements
            if isinstance(value, dict):
                anchor = record_anchor(value, anchor)
                rendered: Dict[str, Any] = {}
                for key, child in value.items():
                    rendered_child = replace(child, anchor, key)
                    if rendered_child is not _MISSING:
                        rendered[key] = rendered_child
                return rendered
            if isinstance(value, list):
                rendered_list: List[Any] = []
                for child in value:
                    rendered_child = replace(child, anchor, target_key)
                    if rendered_child is not _MISSING:
                        rendered_list.append(rendered_child)
                return rendered_list
            path = best_path(value, anchor, target_key)
            if path is None:
                if isinstance(value, str):
                    rendered_string = composed_string(value, anchor, target_key)
                    if rendered_string is not None:
                        replacements += 1
                        return rendered_string
                return _MISSING
            replacements += 1
            return f"{{{path}}}"

        grounded_arguments = replace(arguments)
        return grounded_arguments, replacements > 0

    @classmethod
    def _parameterize_arguments(
        cls,
        arguments: Dict[str, Any],
        previous_scalars: List[Tuple[str, Any]],
    ) -> Dict[str, Any]:
        def replace(value: Any) -> Any:
            if isinstance(value, dict):
                return {key: replace(child) for key, child in value.items()}
            if isinstance(value, list):
                return [replace(child) for child in value]
            for path, scalar in previous_scalars:
                if value == scalar:
                    return f"{{{path}}}"
                if isinstance(value, str) and isinstance(scalar, str) and scalar:
                    value = value.replace(scalar, f"{{{path}}}")
            return value

        return replace(arguments)


__all__ = ["DiscoveredSkill", "SkillDiscovery"]
