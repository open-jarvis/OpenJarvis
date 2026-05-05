"""Parallel LLM router for OpenJarvis.

Orchestrates simultaneous calls to multiple LLM providers (OpenAI, Anthropic,
Gemini, DeepSeek, Groq, Cerebras, SambaNova, etc.) with chat history support.
Implements Option C Hybrid: wait 2-4s for fast responses, fallback to 10s timeout.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import aiohttp

logger = logging.getLogger("openjarvis.orchestrator.router")

# System prompt for J.A.R.V.I.S.
JARVIS_SYSTEM_PROMPT = """You are J.A.R.V.I.S., an advanced AI assistant inspired by the Marvel universe. You are highly intelligent, polite, succinct, and formal. You address the user as "Sir" or "Ma'am". You provide precise, actionable information without unnecessary filler. You maintain a calm, sophisticated demeanor at all times."""

# Configuration for enabled APIs
ENABLED = {
    "openai_api": bool(os.environ.get("OPENAI_API_KEY")),
    "anthropic_api": bool(os.environ.get("ANTHROPIC_API_KEY")),
    "gemini_api": bool(os.environ.get("GEMINI_API_KEY")),
    "deepseek_api": bool(os.environ.get("DEEPSEEK_API_KEY")),
    "groq_api": bool(os.environ.get("GROQ_API_KEY")),
    "cerebras_api": bool(os.environ.get("CEREBRAS_API_KEY")),
    "sambanova_api": bool(os.environ.get("SAMBANOVA_API_KEY")),
    "kimi_api": bool(os.environ.get("KIMI_API_KEY")),
    "github_api": bool(os.environ.get("GITHUB_TOKEN")),
    "glm_api": bool(os.environ.get("GLM_API_KEY")),
    "openrouter_api": bool(os.environ.get("OPENROUTER_API_KEY")),
}


# ---------------------------------------------------------------------------
# OpenAI Compatible API Handler
# ---------------------------------------------------------------------------


async def call_openai_compatible(
    session: aiohttp.ClientSession,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    timeout: int = 10,
) -> dict[str, Any]:
    """Call OpenAI-compatible endpoints (OpenAI, OpenRouter, etc.)."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "messages": messages}

    try:
        async with session.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as r:
            data = await r.json()
            if r.status == 200 and "choices" in data:
                return {
                    "model": model,
                    "text": data["choices"][0]["message"]["content"],
                }
            else:
                return {"model": model, "text": f"Error: {data.get('error', 'Unknown')}"}
    except Exception as e:
        return {"model": model, "text": f"Error: {str(e)}"}


# ---------------------------------------------------------------------------
# Anthropic Handler
# ---------------------------------------------------------------------------


async def call_anthropic(
    session: aiohttp.ClientSession,
    messages: list[dict[str, Any]],
    timeout: int = 10,
) -> dict[str, Any]:
    """Call Anthropic Claude API with messages format."""
    if not ENABLED["anthropic_api"]:
        return {"model": "claude", "text": "Error: Anthropic API not enabled"}

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"model": "claude", "text": "Error: ANTHROPIC_API_KEY not set"}

    # Extract system prompt and chat messages
    system_msg = JARVIS_SYSTEM_PROMPT
    chat_msgs = [m for m in messages if m["role"] != "system"]

    payload = {
        "model": "claude-3-5-sonnet-20241022",
        "max_tokens": 1024,
        "system": system_msg,
        "messages": chat_msgs,
    }

    try:
        async with session.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as r:
            data = await r.json()
            if r.status == 200 and "content" in data:
                return {
                    "model": "claude-3-5-sonnet-20241022",
                    "text": data["content"][0]["text"],
                }
            else:
                return {"model": "claude", "text": f"Error: {data.get('error', {})}"}
    except Exception as e:
        return {"model": "claude", "text": f"Error: {str(e)}"}


# ---------------------------------------------------------------------------
# Google Gemini Handler
# ---------------------------------------------------------------------------


async def call_gemini_api(
    session: aiohttp.ClientSession,
    messages: list[dict[str, Any]],
    timeout: int = 10,
) -> dict[str, Any]:
    """Call Google Gemini API with messages format."""
    if not ENABLED["gemini_api"]:
        return {"model": "gemini", "text": "Error: Gemini API not enabled"}

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"model": "gemini", "text": "Error: GEMINI_API_KEY not set"}

    # Convert messages to Gemini format
    contents = []
    for m in messages:
        role = m["role"]
        if role == "system":
            contents.append({"role": "user", "parts": [{"text": m["content"]}]})
            contents.append({"role": "model", "parts": [{"text": "Understood."}]})
        elif role == "assistant":
            contents.append({"role": "model", "parts": [{"text": m["content"]}]})
        else:
            contents.append({"role": "user", "parts": [{"text": m["content"]}]})

    payload = {
        "contents": contents,
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1024},
    }

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={api_key}"
        async with session.post(
            url,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as r:
            data = await r.json()
            if r.status == 200 and "candidates" in data:
                return {
                    "model": "gemini-pro",
                    "text": data["candidates"][0]["content"]["parts"][0]["text"],
                }
            else:
                return {"model": "gemini", "text": f"Error: {data.get('error', {})}"}
    except Exception as e:
        return {"model": "gemini", "text": f"Error: {str(e)}"}


# ---------------------------------------------------------------------------
# DeepSeek Handler
# ---------------------------------------------------------------------------


async def call_deepseek(
    session: aiohttp.ClientSession,
    messages: list[dict[str, Any]],
    timeout: int = 10,
) -> dict[str, Any]:
    """Call DeepSeek API."""
    if not ENABLED["deepseek_api"]:
        return {"model": "deepseek", "text": "Error: DeepSeek API not enabled"}

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return {"model": "deepseek", "text": "Error: DEEPSEEK_API_KEY not set"}

    return await call_openai_compatible(
        session,
        "https://api.deepseek.com/v1",
        api_key,
        "deepseek-chat",
        messages,
        timeout,
    )


# ---------------------------------------------------------------------------
# Groq Handler
# ---------------------------------------------------------------------------


async def call_groq(
    session: aiohttp.ClientSession,
    messages: list[dict[str, Any]],
    timeout: int = 10,
) -> dict[str, Any]:
    """Call Groq API."""
    if not ENABLED["groq_api"]:
        return {"model": "groq", "text": "Error: Groq API not enabled"}

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return {"model": "groq", "text": "Error: GROQ_API_KEY not set"}

    return await call_openai_compatible(
        session,
        "https://api.groq.com/openai/v1",
        api_key,
        "mixtral-8x7b-32768",
        messages,
        timeout,
    )


# ---------------------------------------------------------------------------
# Cerebras Handler
# ---------------------------------------------------------------------------


async def call_cerebras(
    session: aiohttp.ClientSession,
    messages: list[dict[str, Any]],
    timeout: int = 10,
) -> dict[str, Any]:
    """Call Cerebras API."""
    if not ENABLED["cerebras_api"]:
        return {"model": "cerebras", "text": "Error: Cerebras API not enabled"}

    api_key = os.environ.get("CEREBRAS_API_KEY")
    if not api_key:
        return {"model": "cerebras", "text": "Error: CEREBRAS_API_KEY not set"}

    return await call_openai_compatible(
        session,
        "https://api.cerebras.ai/v1",
        api_key,
        "llama3.1-70b",
        messages,
        timeout,
    )


# ---------------------------------------------------------------------------
# SambaNova Handler
# ---------------------------------------------------------------------------


async def call_sambanova(
    session: aiohttp.ClientSession,
    messages: list[dict[str, Any]],
    timeout: int = 10,
) -> dict[str, Any]:
    """Call SambaNova API."""
    if not ENABLED["sambanova_api"]:
        return {"model": "sambanova", "text": "Error: SambaNova API not enabled"}

    api_key = os.environ.get("SAMBANOVA_API_KEY")
    if not api_key:
        return {"model": "sambanova", "text": "Error: SAMBANOVA_API_KEY not set"}

    return await call_openai_compatible(
        session,
        "https://api.sambanova.ai/v1",
        api_key,
        "Meta-Llama-3.1-70B-Instruct",
        messages,
        timeout,
    )


# ---------------------------------------------------------------------------
# Kimi Handler
# ---------------------------------------------------------------------------


async def call_kimi(
    session: aiohttp.ClientSession,
    messages: list[dict[str, Any]],
    timeout: int = 10,
) -> dict[str, Any]:
    """Call Kimi API."""
    if not ENABLED["kimi_api"]:
        return {"model": "kimi", "text": "Error: Kimi API not enabled"}

    api_key = os.environ.get("KIMI_API_KEY")
    if not api_key:
        return {"model": "kimi", "text": "Error: KIMI_API_KEY not set"}

    return await call_openai_compatible(
        session,
        "https://api.moonshot.cn/v1",
        api_key,
        "moonshot-v1-8k",
        messages,
        timeout,
    )


# ---------------------------------------------------------------------------
# GitHub Models Handler
# ---------------------------------------------------------------------------


async def call_github(
    session: aiohttp.ClientSession,
    messages: list[dict[str, Any]],
    timeout: int = 10,
) -> dict[str, Any]:
    """Call GitHub Models API."""
    if not ENABLED["github_api"]:
        return {"model": "github", "text": "Error: GitHub API not enabled"}

    api_key = os.environ.get("GITHUB_TOKEN")
    if not api_key:
        return {"model": "github", "text": "Error: GITHUB_TOKEN not set"}

    return await call_openai_compatible(
        session,
        "https://models.inference.ai.azure.com",
        api_key,
        "gpt-4o-mini",
        messages,
        timeout,
    )


# ---------------------------------------------------------------------------
# GLM Handler
# ---------------------------------------------------------------------------


async def call_glm(
    session: aiohttp.ClientSession,
    messages: list[dict[str, Any]],
    timeout: int = 10,
) -> dict[str, Any]:
    """Call GLM (Zhipu) API."""
    if not ENABLED["glm_api"]:
        return {"model": "glm", "text": "Error: GLM API not enabled"}

    api_key = os.environ.get("GLM_API_KEY")
    if not api_key:
        return {"model": "glm", "text": "Error: GLM_API_KEY not set"}

    return await call_openai_compatible(
        session,
        "https://open.bigmodel.cn/api/paas/v4",
        api_key,
        "glm-4-flash",
        messages,
        timeout,
    )


# ---------------------------------------------------------------------------
# OpenRouter Handler
# ---------------------------------------------------------------------------


async def call_openrouter(
    session: aiohttp.ClientSession,
    messages: list[dict[str, Any]],
    timeout: int = 10,
) -> dict[str, Any]:
    """Call OpenRouter API."""
    if not ENABLED["openrouter_api"]:
        return {"model": "openrouter", "text": "Error: OpenRouter API not enabled"}

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return {"model": "openrouter", "text": "Error: OPENROUTER_API_KEY not set"}

    return await call_openai_compatible(
        session,
        "https://openrouter.ai/api/v1",
        api_key,
        "meta-llama/llama-3-70b-instruct",
        messages,
        timeout,
    )


# ---------------------------------------------------------------------------
# Ollama Local Handler
# ---------------------------------------------------------------------------


async def call_ollama(
    session: aiohttp.ClientSession,
    messages: list[dict[str, Any]],
    timeout: int = 10,
) -> dict[str, Any]:
    """Call Ollama local model."""
    try:
        payload = {
            "model": "neural-chat",  # Default Ollama model
            "messages": messages,
            "stream": False,
        }

        async with session.post(
            "http://localhost:11434/api/chat",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as r:
            data = await r.json()
            if r.status == 200:
                return {
                    "model": "ollama-neural-chat",
                    "text": data.get("message", {}).get("content", ""),
                }
            else:
                return {"model": "ollama", "text": f"Error: {data}"}
    except Exception as e:
        return {"model": "ollama", "text": f"Error: {str(e)}"}


# ---------------------------------------------------------------------------
# CLI-based Handlers
# ---------------------------------------------------------------------------


async def call_claude_cli(user_message: str) -> dict[str, Any]:
    """Call Claude via CLI if installed (async, non-blocking)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude",
            "-p",  # Print output, non-interactive
            user_message,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        if proc.returncode == 0:
            return {"model": "claude-cli", "text": stdout.decode("utf-8", errors="ignore")}
        else:
            return {"model": "claude-cli", "text": f"Error: {stderr.decode('utf-8', errors='ignore')}"}
    except asyncio.TimeoutError:
        return {"model": "claude-cli", "text": "Error: Claude CLI timeout"}
    except Exception as e:
        return {"model": "claude-cli", "text": f"Error: {str(e)}"}


async def call_gemini_cli(user_message: str) -> dict[str, Any]:
    """Call Gemini via CLI if installed (async, non-blocking)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "gemini",
            user_message,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        if proc.returncode == 0:
            return {"model": "gemini-cli", "text": stdout.decode("utf-8", errors="ignore")}
        else:
            return {"model": "gemini-cli", "text": f"Error: {stderr.decode('utf-8', errors='ignore')}"}
    except asyncio.TimeoutError:
        return {"model": "gemini-cli", "text": "Error: Gemini CLI timeout"}
    except Exception as e:
        return {"model": "gemini-cli", "text": f"Error: {str(e)}"}


# ---------------------------------------------------------------------------
# Default OpenJarvis LLM Handler
# ---------------------------------------------------------------------------


async def call_openjarvis_default(
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Call the default OpenJarvis LLM handler."""
    return {
        "model": "openjarvis-default",
        "text": "Error: Default engine not wired yet. Please configure OpenJarvis engine backend.",
    }


# ---------------------------------------------------------------------------
# Response Selection
# ---------------------------------------------------------------------------


def pick_best(responses: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the best response from the list.

    Prioritizes:
    1. Responses without errors
    2. Longest responses (more complete)
    3. First successful response
    """
    # Filter out error responses
    clean = [r for r in responses if r and "Error" not in r.get("text", "")]
    if not clean:
        # If all failed, return the first one with less error overhead
        return responses[0] if responses else {"model": "unknown", "text": "Error: All models failed"}

    # Return the longest response (most complete)
    return max(clean, key=lambda r: len(r.get("text", "")))


# ---------------------------------------------------------------------------
# Main Orchestrator
# ---------------------------------------------------------------------------


async def run_all(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run all LLM providers in parallel using Option C Hybrid.

    Waits 4 seconds to collect ALL responses, then picks the best one.
    Falls back to 10s timeout if no responses arrive in 4s.

    Args:
        messages: List of message dicts with 'role' and 'content' keys

    Returns:
        List of responses with 'model' and 'text' keys
    """
    # Ensure system prompt is present
    if not messages or messages[0].get("role") != "system":
        messages = [{"role": "system", "content": JARVIS_SYSTEM_PROMPT}] + messages

    async with aiohttp.ClientSession() as session:
        tasks = []

        # Cloud APIs
        if ENABLED["openai_api"]:
            tasks.append(
                call_openai_compatible(
                    session,
                    "https://api.openai.com/v1",
                    os.environ.get("OPENAI_API_KEY", ""),
                    "gpt-4o-mini",
                    messages,
                )
            )
        if ENABLED["anthropic_api"]:
            tasks.append(call_anthropic(session, messages))
        if ENABLED["gemini_api"]:
            tasks.append(call_gemini_api(session, messages))
        if ENABLED["deepseek_api"]:
            tasks.append(call_deepseek(session, messages))
        if ENABLED["groq_api"]:
            tasks.append(call_groq(session, messages))
        if ENABLED["cerebras_api"]:
            tasks.append(call_cerebras(session, messages))
        if ENABLED["sambanova_api"]:
            tasks.append(call_sambanova(session, messages))
        if ENABLED["kimi_api"]:
            tasks.append(call_kimi(session, messages))
        if ENABLED["github_api"]:
            tasks.append(call_github(session, messages))
        if ENABLED["glm_api"]:
            tasks.append(call_glm(session, messages))
        if ENABLED["openrouter_api"]:
            tasks.append(call_openrouter(session, messages))

        # Local models
        tasks.append(call_ollama(session, messages))

        # CLI-based (non-blocking async)
        if messages:
            last_user_msg = ""
            for m in reversed(messages):
                if m["role"] == "user":
                    last_user_msg = m["content"]
                    break
            if last_user_msg:
                tasks.append(call_claude_cli(last_user_msg))
                tasks.append(call_gemini_cli(last_user_msg))

        # Default OpenJarvis model
        tasks.append(call_openjarvis_default(messages))

        # OPTION C HYBRID: Wait 4s to gather ALL responses (not just the first)
        done, pending = await asyncio.wait(
            tasks, timeout=4.0, return_when=asyncio.ALL_COMPLETED
        )

        # If we have some responses, use them; otherwise wait longer
        if done:
            for t in pending:
                t.cancel()
        else:
            # No responses in 4s, wait up to 10s more
            done_2, pending = await asyncio.wait(
                pending, timeout=10.0, return_when=asyncio.FIRST_COMPLETED
            )
            done.update(done_2)
            for t in pending:
                t.cancel()

        # Collect results
        clean = []
        for task in done:
            try:
                result = task.result()
                if result and "Error" not in result.get("text", "") and result.get("text"):
                    clean.append(result)
            except Exception as e:
                logger.debug(f"Task failed: {e}")

        return clean if clean else [{"model": "unknown", "text": "All models failed or timed out"}]


# ---------------------------------------------------------------------------
# Integration with OpenJarvis Backend
# ---------------------------------------------------------------------------


async def handle_chat_request(
    user_message: str,
    chat_history: list[dict[str, str]] | None = None,
) -> str:
    """Handle a chat request with full message history support.

    Args:
        user_message: The current user message
        chat_history: Prior conversation history (optional)

    Returns:
        The best response text
    """
    # Build full messages array
    messages = [{"role": "system", "content": JARVIS_SYSTEM_PROMPT}]

    # Add existing chat history
    if chat_history:
        for msg in chat_history:
            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})

    # Add the new user message
    messages.append({"role": "user", "content": user_message})

    # Run parallel routing
    responses = await run_all(messages)

    # Pick the best response
    best = pick_best(responses)

    return best["text"]


__all__ = [
    "JARVIS_SYSTEM_PROMPT",
    "run_all",
    "pick_best",
    "handle_chat_request",
]
