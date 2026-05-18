"""Cloud inference engine — OpenAI, Anthropic, Google, and MiniMax API backends."""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any, Dict, List, Tuple

import httpx

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message
from openjarvis.engine._base import (
    EngineConnectionError,
    InferenceEngine,
    messages_to_dicts,
)
from openjarvis.engine._stubs import StreamChunk

logger = logging.getLogger(__name__)

# Pricing per million tokens (input, output)
PRICING: Dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-5": (10.00, 30.00),
    "gpt-5.4": (15.00, 60.00),
    "gpt-5-mini": (0.25, 2.00),
    "o3-mini": (1.10, 4.40),
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-opus-4-20250514": (15.00, 75.00),
    "claude-haiku-3-5-20241022": (0.80, 4.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-3-pro": (2.00, 12.00),
    "gemini-3-flash": (0.50, 3.00),
    "gemini-3.1-pro-preview": (2.50, 15.00),
    "gemini-3.1-flash-lite-preview": (0.30, 2.50),
    "gemini-3-flash-preview": (0.50, 3.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "MiniMax-M2.7": (0.30, 1.20),
    "MiniMax-M2.7-highspeed": (0.60, 2.40),
    "MiniMax-M2.5": (0.30, 1.20),
    "MiniMax-M2.5-highspeed": (0.60, 2.40),
}

# Well-known model IDs per provider
_OPENAI_MODELS = [
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-5",
    "gpt-5.4",
    "gpt-5-mini",
    "o3-mini",
]
_ANTHROPIC_MODELS = [
    "claude-sonnet-4-20250514",
    "claude-opus-4-20250514",
    "claude-haiku-3-5-20241022",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
    "claude-haiku-4-5-20251001",
]
_GOOGLE_MODELS = [
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-3-pro",
    "gemini-3-flash",
    "gemini-3.1-pro-preview",
    "gemini-3.1-flash-lite-preview",
    "gemini-3-flash-preview",
]
_MINIMAX_MODELS = [
    "MiniMax-M2.7",
    "MiniMax-M2.7-highspeed",
    "MiniMax-M2.5",
    "MiniMax-M2.5-highspeed",
]

# OpenRouter models — prefixed with "openrouter/" so they can be identified
_OPENROUTER_POPULAR = [
    "openrouter/auto",
    "openrouter/openai/gpt-4o",
    "openrouter/anthropic/claude-sonnet-4",
    "openrouter/google/gemini-2.5-pro",
    "openrouter/meta-llama/llama-3.3-70b-instruct",
    "openrouter/mistralai/mistral-large",
    "openrouter/deepseek/deepseek-r1",
    "openrouter/qwen/qwen3-235b-a22b",
]

# Codex models — prefixed with "codex/" for ChatGPT Plus/Pro subscribers.
# Uses the Responses API at chatgpt.com, not the standard OpenAI API.
_CODEX_MODELS = [
    "codex/gpt-4o",
    "codex/gpt-4o-mini",
    "codex/o3-mini",
    "codex/gpt-5-mini",
    "codex/gpt-5-mini-2025-08-07",
]


def _is_minimax_model(model: str) -> bool:
    return model.lower().startswith("minimax")


def _is_openrouter_model(model: str) -> bool:
    return model.startswith("openrouter/")


def _is_codex_model(model: str) -> bool:
    return model.startswith("codex/")


def _is_anthropic_model(model: str) -> bool:
    return "claude" in model.lower() and not _is_openrouter_model(model)


def _is_google_model(model: str) -> bool:
    return "gemini" in model.lower() and not _is_openrouter_model(model)


def _is_openai_reasoning_model(model: str) -> bool:
    """Check if model is an OpenAI reasoning model that restricts temperature."""
    m = model.lower()
    # o1/o3 series and gpt-5-mini (all variants) are reasoning models
    if m.startswith(("o1", "o3")):
        return True
    return m == "gpt-5-mini" or m.startswith("gpt-5-mini-")


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate USD cost based on the hardcoded pricing table."""
    # Try exact match first, then prefix match
    prices = PRICING.get(model)
    if prices is None:
        for key, val in PRICING.items():
            if model.startswith(key):
                prices = val
                break
    if prices is None:
        return 0.0
    input_cost = (prompt_tokens / 1_000_000) * prices[0]
    output_cost = (completion_tokens / 1_000_000) * prices[1]
    return input_cost + output_cost


def _serialize_anthropic_block(block: Any) -> Dict[str, Any]:
    """Turn an Anthropic content block into a JSON-safe dict for tracing.

    Handles every block type Anthropic returns today (text, tool_use,
    server_tool_use, web_search_tool_result, tool_result, thinking). Nested
    content (e.g. ``web_search_tool_result.content`` is itself a list of
    citation/result blocks) recurses so the trace has the full payload, not
    a truncated summary.
    """
    out: Dict[str, Any] = {
        "type": getattr(block, "type", None) or type(block).__name__,
    }
    for attr in (
        "id", "name", "input", "text", "thinking", "signature",
        "tool_use_id", "content",
    ):
        if not hasattr(block, attr):
            continue
        val = getattr(block, attr)
        if attr == "content" and isinstance(val, list):
            out[attr] = [_serialize_anthropic_block(b) for b in val]
        elif hasattr(val, "model_dump"):
            try:
                out[attr] = val.model_dump()
            except Exception:
                out[attr] = str(val)
        else:
            out[attr] = val
    return out


def _annotate_anthropic_cache(messages: list[dict]) -> list[dict]:
    """Add cache_control to system message for Anthropic prompt caching."""
    result = []
    for msg in messages:
        if msg.get("role") == "system":
            content = msg["content"]
            if isinstance(content, str):
                content = [
                    {
                        "type": "text",
                        "text": content,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
            elif isinstance(content, list):
                content = [
                    {**block, "cache_control": {"type": "ephemeral"}}
                    for block in content
                ]
            result.append({**msg, "content": content})
        else:
            result.append(msg)
    return result


def _convert_tools_to_anthropic(
    openai_tools: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Convert OpenAI function-calling tools to Anthropic tool format."""
    result = []
    for tool in openai_tools:
        func = tool.get("function", {})
        result.append(
            {
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {}),
            }
        )
    return result


def _convert_tools_to_google(
    openai_tools: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Convert OpenAI function-calling tools to Google function declarations."""
    declarations = []
    for tool in openai_tools:
        func = tool.get("function", {})
        declarations.append(
            {
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "parameters": func.get("parameters", {}),
            }
        )
    return declarations


@EngineRegistry.register("cloud")
class CloudEngine(InferenceEngine):
    """Cloud inference via OpenAI, Anthropic, Google, and MiniMax SDKs."""

    engine_id = "cloud"
    is_cloud = True

    def __init__(self) -> None:
        self._openai_client: Any = None
        self._anthropic_client: Any = None
        self._google_client: Any = None
        self._openrouter_client: Any = None
        self._minimax_client: Any = None
        self._codex_client: Any = None
        # Gemini thought_signatures: tool_call_id -> signature bytes
        self._thought_sigs: Dict[str, bytes] = {}
        self._init_clients()

    def _init_clients(self) -> None:
        if os.environ.get("OPENAI_API_KEY"):
            try:
                import openai

                self._openai_client = openai.OpenAI()
            except ImportError:
                pass
        if os.environ.get("ANTHROPIC_API_KEY"):
            try:
                import anthropic

                self._anthropic_client = anthropic.Anthropic()
            except ImportError:
                pass
        gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get(
            "GOOGLE_API_KEY"
        )
        if gemini_key:
            try:
                from google import genai

                self._google_client = genai.Client(api_key=gemini_key)
            except ImportError:
                pass
        openrouter_key = os.environ.get("OPENROUTER_API_KEY")
        if openrouter_key:
            try:
                import openai

                self._openrouter_client = openai.OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=openrouter_key,
                )
            except ImportError:
                pass
        minimax_key = os.environ.get("MINIMAX_API_KEY")
        if minimax_key:
            try:
                import openai

                self._minimax_client = openai.OpenAI(
                    base_url="https://api.minimax.io/v1",
                    api_key=minimax_key,
                )
            except ImportError:
                pass
        # Codex — uses the OpenAI Responses API.
        # Supports both standard API keys (api.openai.com) and ChatGPT
        # OAuth tokens (chatgpt.com) via OPENAI_CODEX_BASE_URL override.
        codex_token = os.environ.get("OPENAI_CODEX_API_KEY")
        if codex_token:
            codex_url = os.environ.get(
                "OPENAI_CODEX_BASE_URL",
                "https://api.openai.com/v1",
            ).rstrip("/")
            if not codex_url.endswith("/responses"):
                codex_url += "/responses"
            self._codex_client = {
                "token": codex_token,
                "url": codex_url,
            }

    def _prepare_anthropic_messages(
        self,
        messages: Sequence[Message],
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Extract system text and convert messages to Anthropic format."""
        system_text = ""
        chat_msgs: List[Dict[str, Any]] = []
        for m in messages:
            if m.role.value == "system":
                system_text = m.content
            elif m.role.value == "tool":
                tool_result_block = {
                    "type": "tool_result",
                    "tool_use_id": m.tool_call_id or "",
                    "content": m.content,
                }
                if (
                    chat_msgs
                    and chat_msgs[-1]["role"] == "user"
                    and isinstance(chat_msgs[-1]["content"], list)
                    and chat_msgs[-1]["content"]
                    and chat_msgs[-1]["content"][-1].get("type") == "tool_result"
                ):
                    chat_msgs[-1]["content"].append(tool_result_block)
                else:
                    chat_msgs.append(
                        {
                            "role": "user",
                            "content": [tool_result_block],
                        }
                    )
            elif m.role.value == "assistant" and m.tool_calls:
                content_blocks: List[Dict[str, Any]] = []
                if m.content:
                    content_blocks.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    args = tc.arguments
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except (json.JSONDecodeError, TypeError):
                            args = {"input": args}
                    content_blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": args if isinstance(args, dict) else {},
                        }
                    )
                chat_msgs.append({"role": "assistant", "content": content_blocks})
            else:
                chat_msgs.append({"role": m.role.value, "content": m.content})
        return system_text, chat_msgs

    @staticmethod
    def _codex_build_input(
        messages: Sequence[Message],
    ) -> tuple[str, List[Dict[str, Any]]]:
        """Convert Message list to Codex Responses API format.

        Returns (system_instructions, input_messages).
        """
        instructions = ""
        input_msgs: List[Dict[str, Any]] = []
        for m in messages:
            if m.role.value == "system":
                instructions = m.content
            elif m.role.value in ("user", "assistant"):
                input_msgs.append(
                    {
                        "role": m.role.value,
                        "content": [{"type": "input_text", "text": m.content}],
                    }
                )
        return instructions, input_msgs

    def _generate_codex(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Generate via Codex Responses API (ChatGPT Plus/Pro)."""
        if self._codex_client is None:
            raise EngineConnectionError(
                "Codex client not available — set OPENAI_CODEX_API_KEY"
            )
        actual_model = model.removeprefix("codex/")
        instructions, input_msgs = self._codex_build_input(messages)

        body: Dict[str, Any] = {
            "model": actual_model,
            "input": input_msgs,
            "store": False,
            "stream": False,
        }
        if instructions:
            body["instructions"] = instructions

        headers = {
            "Authorization": f"Bearer {self._codex_client['token']}",
            "Content-Type": "application/json",
            "OpenAI-Beta": "responses=experimental",
        }

        t0 = time.monotonic()
        resp = httpx.post(
            self._codex_client["url"],
            json=body,
            headers=headers,
            timeout=120.0,
        )
        elapsed = time.monotonic() - t0
        resp.raise_for_status()
        data = resp.json()

        # Extract text from Responses API output.
        # The output array contains items of type "reasoning" and "message";
        # we want the "message" item's content blocks.
        content = data.get("output_text", "")
        if not content:
            for item in data.get("output", []):
                if item.get("type") not in ("message", None):
                    continue
                for block in item.get("content", []):
                    if block.get("type") == "output_text":
                        content = block.get("text", "")
                        break
                if content:
                    break

        usage_data = data.get("usage", {})
        prompt_tokens = usage_data.get("input_tokens", 0)
        completion_tokens = usage_data.get("output_tokens", 0)

        return {
            "content": content,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "model": actual_model,
            "finish_reason": "stop",
            "cost_usd": 0.0,
            "ttft": elapsed,
        }

    def _generate_openai(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if self._openai_client is None:
            raise EngineConnectionError(
                "OpenAI client not available — set "
                "OPENAI_API_KEY and install "
                "openjarvis[inference-cloud]"
            )
        # Extract response_format before spreading kwargs into create_kwargs
        response_format = kwargs.pop("response_format", None)
        create_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages_to_dicts(messages),
            "max_completion_tokens": max_tokens,
            **kwargs,
        }
        if not _is_openai_reasoning_model(model):
            create_kwargs["temperature"] = temperature

        # Apply structured output / JSON mode
        if response_format is not None:
            from openjarvis.engine._stubs import ResponseFormat

            if isinstance(response_format, ResponseFormat):
                if response_format.type == "json_schema" and response_format.schema:
                    create_kwargs["response_format"] = {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "response",
                            "schema": response_format.schema,
                        },
                    }
                else:
                    create_kwargs["response_format"] = {"type": "json_object"}
            else:
                # Raw dict pass-through for backward compatibility
                create_kwargs["response_format"] = response_format

        t0 = time.monotonic()
        resp = self._openai_client.chat.completions.create(**create_kwargs)
        elapsed = time.monotonic() - t0
        choice = resp.choices[0]
        usage = resp.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        result = {
            "content": choice.message.content or "",
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": (usage.total_tokens if usage else 0),
            },
            "model": resp.model,
            "finish_reason": choice.finish_reason or "stop",
            "cost_usd": estimate_cost(model, prompt_tokens, completion_tokens),
            "ttft": elapsed,
        }

        # Extract tool_calls if present
        if hasattr(choice.message, "tool_calls") and choice.message.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                }
                for tc in choice.message.tool_calls
            ]

        return result

    def _generate_anthropic(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if self._anthropic_client is None:
            raise EngineConnectionError(
                "Anthropic client not available — set "
                "ANTHROPIC_API_KEY and install "
                "openjarvis[inference-cloud]"
            )
        system_text, chat_msgs = self._prepare_anthropic_messages(messages)
        create_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": chat_msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system_text:
            create_kwargs["system"] = system_text

        # Convert and pass tools in Anthropic format
        raw_tools = kwargs.pop("tools", None)
        if raw_tools:
            create_kwargs["tools"] = _convert_tools_to_anthropic(raw_tools)

        # Apply structured output via Anthropic's tool_choice pattern
        response_format = kwargs.pop("response_format", None)
        if response_format is not None:
            from openjarvis.engine._stubs import ResponseFormat

            if isinstance(response_format, ResponseFormat):
                json_tool = {
                    "name": "json_output",
                    "description": "Output structured JSON response",
                    "input_schema": response_format.schema or {"type": "object"},
                }
                if "tools" not in create_kwargs:
                    create_kwargs["tools"] = [json_tool]
                else:
                    create_kwargs["tools"].append(json_tool)
                create_kwargs["tool_choice"] = {
                    "type": "tool",
                    "name": "json_output",
                }

        t0 = time.monotonic()
        resp = self._anthropic_client.messages.create(**create_kwargs)
        elapsed = time.monotonic() - t0

        # Walk every block in resp.content. Anthropic returns several kinds:
        #   - text                       (plain assistant text)
        #   - tool_use                   (model wants the caller to run a tool)
        #   - server_tool_use            (model invoked a server-side tool,
        #                                 e.g. web_search; carries the actual
        #                                 query the model issued)
        #   - web_search_tool_result     (server-tool result body)
        #   - tool_result                (caller-side tool result echo)
        #   - thinking                   (Opus reasoning trace)
        # ``content_blocks`` keeps the full serialized list for trace
        # observability. ``tool_calls`` is the narrow caller-executable
        # surface — only ``tool_use`` blocks (server_tool_use lives in
        # content_blocks since Anthropic already ran it server-side).
        # ``tool_results`` aggregates both result kinds.
        content_parts: list[str] = []
        tool_calls: list[Dict[str, Any]] = []
        tool_results: list[Dict[str, Any]] = []
        content_blocks: list[Dict[str, Any]] = []
        for block in resp.content:
            btype = getattr(block, "type", None) or type(block).__name__
            serialized = _serialize_anthropic_block(block)
            content_blocks.append(serialized)
            if btype == "tool_use":
                block_id = getattr(block, "id", None)
                if not block_id:
                    logger.warning(
                        "Anthropic tool_use block without an id; skipping. "
                        "Round-trip into the next assistant turn would fail "
                        "Anthropic's tool_use_id matching."
                    )
                    continue
                tool_calls.append(
                    {
                        "id": block_id,
                        "name": getattr(block, "name", ""),
                        "arguments": json.dumps(getattr(block, "input", None))
                        if isinstance(getattr(block, "input", None), dict)
                        else str(getattr(block, "input", "")),
                    }
                )
            elif btype in ("web_search_tool_result", "tool_result"):
                tool_results.append(serialized)
            elif hasattr(block, "text"):
                content_parts.append(block.text)

        content = "\n".join(content_parts) if content_parts else ""
        prompt_tokens = resp.usage.input_tokens if resp.usage else 0
        completion_tokens = resp.usage.output_tokens if resp.usage else 0

        result: Dict[str, Any] = {
            "content": content,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "model": resp.model,
            "finish_reason": resp.stop_reason or "stop",
            "cost_usd": estimate_cost(model, prompt_tokens, completion_tokens),
            "ttft": elapsed,
            "content_blocks": content_blocks,
        }

        if tool_calls:
            result["tool_calls"] = tool_calls
        if tool_results:
            result["tool_results"] = tool_results

        return result

    def _generate_google(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if self._google_client is None:
            raise EngineConnectionError(
                "Google client not available — set "
                "GEMINI_API_KEY or GOOGLE_API_KEY and install "
                "openjarvis[inference-google]"
            )
        # Build contents from messages, converting tool roles for Gemini
        system_text = ""
        contents: List[Dict[str, Any]] = []
        for m in messages:
            if m.role.value == "system":
                system_text = m.content
            elif m.role.value == "tool":
                # Gemini expects function responses as role="user" with
                # function_response parts
                fn_resp_part = {
                    "function_response": {
                        "name": m.name or "unknown",
                        "response": {"result": m.content},
                    }
                }
                # Merge consecutive tool results into a single user message
                if (
                    contents
                    and contents[-1]["role"] == "user"
                    and contents[-1]["parts"]
                    and "function_response" in contents[-1]["parts"][-1]
                ):
                    contents[-1]["parts"].append(fn_resp_part)
                else:
                    contents.append({"role": "user", "parts": [fn_resp_part]})
            elif m.role.value == "assistant" and m.tool_calls:
                # Convert assistant tool_calls to function_call parts
                parts: List[Dict[str, Any]] = []
                if m.content:
                    parts.append({"text": m.content})
                for tc in m.tool_calls:
                    args = tc.arguments
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except (json.JSONDecodeError, TypeError):
                            args = {"input": args}
                    fc_part: Dict[str, Any] = {
                        "function_call": {
                            "name": tc.name,
                            "args": args if isinstance(args, dict) else {},
                        }
                    }
                    # Replay thought_signature for Gemini reasoning models
                    sig = self._thought_sigs.get(tc.id)
                    if sig is not None:
                        fc_part["thought_signature"] = sig
                    parts.append(fc_part)
                contents.append({"role": "model", "parts": parts})
            elif m.role.value == "assistant":
                contents.append({"role": "model", "parts": [{"text": m.content}]})
            else:
                contents.append({"role": "user", "parts": [{"text": m.content}]})

        from google.genai import types as genai_types

        config = genai_types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        if system_text:
            config.system_instruction = system_text

        # Convert and pass tools in Google format
        raw_tools = kwargs.pop("tools", None)
        if raw_tools:
            declarations = _convert_tools_to_google(raw_tools)
            config.tools = [{"function_declarations": declarations}]

        # Apply structured output / JSON mode for Google
        response_format = kwargs.pop("response_format", None)
        if response_format is not None:
            from openjarvis.engine._stubs import ResponseFormat

            if isinstance(response_format, ResponseFormat):
                config.response_mime_type = "application/json"
                if response_format.schema:
                    config.response_schema = response_format.schema

        t0 = time.monotonic()
        resp = self._google_client.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )
        elapsed = time.monotonic() - t0

        # Extract text and function_call parts from response
        text_parts: list[str] = []
        tool_calls: list[Dict[str, Any]] = []
        candidates = getattr(resp, "candidates", None)
        if candidates:
            parts = getattr(candidates[0].content, "parts", [])
            for part in parts:
                if hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    fc_args = dict(fc.args) if hasattr(fc.args, "items") else {}
                    tc_dict: Dict[str, Any] = {
                        "id": f"google_{fc.name}",
                        "name": fc.name,
                        "arguments": json.dumps(fc_args),
                    }
                    # Preserve thought_signature for Gemini reasoning models
                    sig = getattr(part, "thought_signature", None)
                    if sig is not None:
                        tc_dict["thought_signature"] = sig
                        self._thought_sigs[tc_dict["id"]] = sig
                    tool_calls.append(tc_dict)
                elif hasattr(part, "text") and part.text:
                    text_parts.append(part.text)

        # Guard against resp.text ValueError when only function_call parts
        if text_parts:
            content = "\n".join(text_parts)
        else:
            try:
                content = resp.text or ""
            except (ValueError, AttributeError):
                content = ""

        um = resp.usage_metadata
        prompt_tokens = getattr(um, "prompt_token_count", 0) if um else 0
        completion_tokens = getattr(um, "candidates_token_count", 0) if um else 0

        result: Dict[str, Any] = {
            "content": content,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "model": model,
            "finish_reason": "stop",
            "cost_usd": estimate_cost(model, prompt_tokens, completion_tokens),
            "ttft": elapsed,
        }

        if tool_calls:
            result["tool_calls"] = tool_calls

        return result

    def _generate_openrouter(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if self._openrouter_client is None:
            raise EngineConnectionError(
                "OpenRouter client not available — set OPENROUTER_API_KEY"
            )
        # Strip the "openrouter/" prefix to get the actual model ID
        actual_model = model.removeprefix("openrouter/")
        kwargs.pop("response_format", None)
        create_kwargs: Dict[str, Any] = {
            "model": actual_model,
            "messages": messages_to_dicts(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        t0 = time.monotonic()
        resp = self._openrouter_client.chat.completions.create(**create_kwargs)
        elapsed = time.monotonic() - t0
        choice = resp.choices[0]
        usage = resp.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        return {
            "content": choice.message.content or "",
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": (usage.total_tokens if usage else 0),
            },
            "model": resp.model,
            "finish_reason": choice.finish_reason or "stop",
            "ttft": elapsed,
        }

    def _generate_minimax(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if self._minimax_client is None:
            raise EngineConnectionError(
                "MiniMax client not available — set MINIMAX_API_KEY"
            )
        # MiniMax requires temperature in (0.0, 1.0]; clamp zero
        temperature = max(temperature, 0.01)
        temperature = min(temperature, 1.0)
        kwargs.pop("response_format", None)
        create_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages_to_dicts(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        t0 = time.monotonic()
        resp = self._minimax_client.chat.completions.create(**create_kwargs)
        elapsed = time.monotonic() - t0
        choice = resp.choices[0]
        usage = resp.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        result: Dict[str, Any] = {
            "content": choice.message.content or "",
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": (usage.total_tokens if usage else 0),
            },
            "model": resp.model,
            "finish_reason": choice.finish_reason or "stop",
            "cost_usd": estimate_cost(model, prompt_tokens, completion_tokens),
            "ttft": elapsed,
        }
        if hasattr(choice.message, "tool_calls") and choice.message.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                }
                for tc in choice.message.tool_calls
            ]
        return result

    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        kw = dict(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        if _is_codex_model(model):
            return self._generate_codex(messages, **kw)
        if _is_openrouter_model(model):
            return self._generate_openrouter(messages, **kw)
        if _is_minimax_model(model):
            return self._generate_minimax(messages, **kw)
        if _is_anthropic_model(model):
            return self._generate_anthropic(messages, **kw)
        if _is_google_model(model):
            return self._generate_google(messages, **kw)
        return self._generate_openai(messages, **kw)

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        kw = dict(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        if _is_codex_model(model):
            async for token in self._stream_codex(messages, **kw):
                yield token
        elif _is_openrouter_model(model):
            async for token in self._stream_openrouter(messages, **kw):
                yield token
        elif _is_minimax_model(model):
            async for token in self._stream_minimax(messages, **kw):
                yield token
        elif _is_anthropic_model(model):
            async for token in self._stream_anthropic(messages, **kw):
                yield token
        elif _is_google_model(model):
            async for token in self._stream_google(messages, **kw):
                yield token
        else:
            async for token in self._stream_openai(messages, **kw):
                yield token

    async def _stream_codex(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream via Codex Responses API (SSE)."""
        if self._codex_client is None:
            raise EngineConnectionError("Codex client not available")
        actual_model = model.removeprefix("codex/")
        instructions, input_msgs = self._codex_build_input(messages)

        body: Dict[str, Any] = {
            "model": actual_model,
            "input": input_msgs,
            "store": False,
            "stream": True,
        }
        if instructions:
            body["instructions"] = instructions

        headers = {
            "Authorization": f"Bearer {self._codex_client['token']}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "OpenAI-Beta": "responses=experimental",
        }

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                self._codex_client["url"],
                json=body,
                headers=headers,
                timeout=120.0,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload == "[DONE]":
                        break
                    try:
                        event = json.loads(payload)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    etype = event.get("type", "")
                    if etype == "response.output_text.delta":
                        delta = event.get("delta", "")
                        if delta:
                            yield delta

    async def _stream_openai(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        if self._openai_client is None:
            raise EngineConnectionError("OpenAI client not available")
        create_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages_to_dicts(messages),
            "max_completion_tokens": max_tokens,
            "stream": True,
            **kwargs,
        }
        if not _is_openai_reasoning_model(model):
            create_kwargs["temperature"] = temperature
        resp = self._openai_client.chat.completions.create(**create_kwargs)
        for chunk in resp:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content

    async def _stream_anthropic(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        if self._anthropic_client is None:
            raise EngineConnectionError("Anthropic client not available")
        system_text = ""
        chat_msgs: List[Dict[str, Any]] = []
        for m in messages:
            if m.role.value == "system":
                system_text = m.content
            else:
                chat_msgs.append({"role": m.role.value, "content": m.content})
        create_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": chat_msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system_text:
            create_kwargs["system"] = system_text
        with self._anthropic_client.messages.stream(**create_kwargs) as stream:
            for text in stream.text_stream:
                yield text

    async def _stream_google(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        if self._google_client is None:
            raise EngineConnectionError("Google client not available")
        system_text = ""
        contents: List[Dict[str, Any]] = []
        for m in messages:
            if m.role.value == "system":
                system_text = m.content
            elif m.role.value == "assistant":
                contents.append({"role": "model", "parts": [{"text": m.content}]})
            else:
                contents.append({"role": "user", "parts": [{"text": m.content}]})

        from google.genai import types as genai_types

        config = genai_types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        if system_text:
            config.system_instruction = system_text

        for chunk in self._google_client.models.generate_content_stream(
            model=model,
            contents=contents,
            config=config,
        ):
            if chunk.text:
                yield chunk.text

    async def _stream_openrouter(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        if self._openrouter_client is None:
            raise EngineConnectionError("OpenRouter client not available")
        actual_model = model.removeprefix("openrouter/")
        create_kwargs: Dict[str, Any] = {
            "model": actual_model,
            "messages": messages_to_dicts(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        resp = self._openrouter_client.chat.completions.create(**create_kwargs)
        for chunk in resp:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content

    async def _stream_minimax(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        if self._minimax_client is None:
            raise EngineConnectionError("MiniMax client not available")
        temperature = max(temperature, 0.01)
        temperature = min(temperature, 1.0)
        create_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages_to_dicts(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        resp = self._minimax_client.chat.completions.create(**create_kwargs)
        for chunk in resp:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content

    # -- stream_full: rich streaming with tool_calls support ----------------

    async def _stream_full_openai(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Yield StreamChunks from an OpenAI-compatible streaming response.

        Works for OpenAI, OpenRouter, MiniMax, and Codex.
        """
        if _is_codex_model(model):
            # Codex uses Responses API — fall back to base stream_full wrapper
            async for chunk in super().stream_full(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            ):
                yield chunk
            return
        if _is_openrouter_model(model):
            client = self._openrouter_client
            if client is None:
                raise EngineConnectionError("OpenRouter client not available")
            actual_model = model.removeprefix("openrouter/")
            create_kwargs: Dict[str, Any] = {
                "model": actual_model,
                "messages": messages_to_dicts(messages),
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": True,
                **kwargs,
            }
        elif _is_minimax_model(model):
            client = self._minimax_client
            if client is None:
                raise EngineConnectionError("MiniMax client not available")
            temperature = max(temperature, 0.01)
            temperature = min(temperature, 1.0)
            create_kwargs = {
                "model": model,
                "messages": messages_to_dicts(messages),
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": True,
                **kwargs,
            }
        else:
            client = self._openai_client
            if client is None:
                raise EngineConnectionError("OpenAI client not available")
            create_kwargs = {
                "model": model,
                "messages": messages_to_dicts(messages),
                "max_completion_tokens": max_tokens,
                "stream": True,
                **kwargs,
            }
            if not _is_openai_reasoning_model(model):
                create_kwargs["temperature"] = temperature
        resp = client.chat.completions.create(**create_kwargs)
        for chunk in resp:
            choice = chunk.choices[0] if chunk.choices else None
            if not choice:
                continue
            delta = choice.delta
            content = delta.content if delta else None
            tool_calls = None
            if delta and delta.tool_calls:
                tool_calls = [
                    {
                        "index": tc.index,
                        "id": tc.id or "",
                        "function": {
                            "name": (tc.function.name or "") if tc.function else "",
                            "arguments": (
                                (tc.function.arguments or "") if tc.function else ""
                            ),
                        },
                    }
                    for tc in delta.tool_calls
                ]
            finish = choice.finish_reason
            if content or tool_calls or finish:
                yield StreamChunk(
                    content=content,
                    tool_calls=tool_calls,
                    finish_reason=finish,
                )

    async def _stream_full_anthropic(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Yield StreamChunks from an Anthropic streaming response."""
        if self._anthropic_client is None:
            raise EngineConnectionError("Anthropic client not available")
        system_text, chat_msgs = self._prepare_anthropic_messages(messages)
        create_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": chat_msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system_text:
            create_kwargs["system"] = system_text
        raw_tools = kwargs.pop("tools", None)
        if raw_tools:
            create_kwargs["tools"] = _convert_tools_to_anthropic(raw_tools)
        kwargs.pop("tool_choice", None)

        with self._anthropic_client.messages.stream(**create_kwargs) as stream:
            tool_index = -1
            for event in stream:
                if event.type == "content_block_start":
                    block = event.content_block
                    if block.type == "tool_use":
                        tool_index += 1
                        yield StreamChunk(
                            tool_calls=[
                                {
                                    "index": tool_index,
                                    "id": block.id,
                                    "function": {"name": block.name, "arguments": ""},
                                }
                            ]
                        )
                elif event.type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "text_delta":
                        yield StreamChunk(content=delta.text)
                    elif delta.type == "input_json_delta":
                        yield StreamChunk(
                            tool_calls=[
                                {
                                    "index": tool_index,
                                    "function": {"arguments": delta.partial_json},
                                }
                            ]
                        )
                elif event.type == "message_delta":
                    stop_reason = event.delta.stop_reason
                    finish = "tool_calls" if stop_reason == "tool_use" else "stop"
                    yield StreamChunk(finish_reason=finish)

            # End-of-stream parity with ``_generate_anthropic``: emit
            # ``content_blocks`` (every block kind, including server_tool_use
            # and thinking) and ``tool_results`` (web_search_tool_result +
            # tool_result) so streaming traces see what non-streaming traces
            # see.
            try:
                final_msg = stream.get_final_message()
            except Exception as exc:  # noqa: BLE001 — SDK shape varies
                logger.debug("Anthropic stream.get_final_message() failed: %s", exc)
                final_msg = None
            if final_msg is not None and getattr(final_msg, "content", None):
                content_blocks: list[Dict[str, Any]] = []
                tool_results: list[Dict[str, Any]] = []
                for block in final_msg.content:
                    btype = getattr(block, "type", None) or type(block).__name__
                    serialized = _serialize_anthropic_block(block)
                    content_blocks.append(serialized)
                    if btype in ("web_search_tool_result", "tool_result"):
                        tool_results.append(serialized)
                if content_blocks or tool_results:
                    yield StreamChunk(
                        content_blocks=content_blocks or None,
                        tool_results=tool_results or None,
                    )

    async def stream_full(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Yield StreamChunks with content, tool_calls, and finish_reason."""
        kw = dict(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        if _is_anthropic_model(model):
            async for chunk in self._stream_full_anthropic(messages, **kw):
                yield chunk
        elif _is_google_model(model):
            async for chunk in super().stream_full(messages, **kw):
                yield chunk
        else:
            async for chunk in self._stream_full_openai(messages, **kw):
                yield chunk

    def list_models(self) -> List[str]:
        models: List[str] = []
        if self._openai_client is not None:
            models.extend(_OPENAI_MODELS)
        if self._anthropic_client is not None:
            models.extend(_ANTHROPIC_MODELS)
        if self._google_client is not None:
            models.extend(_GOOGLE_MODELS)
        if self._openrouter_client is not None:
            models.extend(_OPENROUTER_POPULAR)
        if self._minimax_client is not None:
            models.extend(_MINIMAX_MODELS)
        if self._codex_client is not None:
            models.extend(_CODEX_MODELS)
        return models

    def health(self) -> bool:
        return (
            self._openai_client is not None
            or self._anthropic_client is not None
            or self._google_client is not None
            or self._openrouter_client is not None
            or self._minimax_client is not None
            or self._codex_client is not None
        )

    def close(self) -> None:
        if self._openai_client is not None:
            if hasattr(self._openai_client, "close"):
                self._openai_client.close()
            self._openai_client = None
        if self._anthropic_client is not None:
            if hasattr(self._anthropic_client, "close"):
                self._anthropic_client.close()
            self._anthropic_client = None
        if self._google_client is not None:
            self._google_client = None
        if self._openrouter_client is not None:
            if hasattr(self._openrouter_client, "close"):
                self._openrouter_client.close()
            self._openrouter_client = None
        if self._minimax_client is not None:
            if hasattr(self._minimax_client, "close"):
                self._minimax_client.close()
            self._minimax_client = None
        if self._codex_client is not None:
            self._codex_client = None


__all__ = ["CloudEngine", "PRICING", "_annotate_anthropic_cache", "estimate_cost"]
