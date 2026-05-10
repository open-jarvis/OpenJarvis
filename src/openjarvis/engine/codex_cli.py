"""Codex CLI inference engine.

This backend uses the locally authenticated Codex CLI, so it can work with a
ChatGPT login instead of an OpenAI API key.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any, Dict, List

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message
from openjarvis.engine._base import EngineConnectionError, estimate_prompt_tokens
from openjarvis.engine._stubs import InferenceEngine

_DEFAULT_MODEL = "gpt-5.5"
_DEFAULT_TIMEOUT_SECONDS = 90.0


def _resolve_codex_path() -> str | None:
    configured = os.environ.get("OPENJARVIS_CODEX_COMMAND") or os.environ.get(
        "CODEX_CLI"
    )
    candidates: list[str] = []
    if configured:
        candidates.append(configured)

    for candidate in candidates:
        if os.path.isabs(candidate) and Path(candidate).exists():
            return candidate
        path = shutil.which(candidate)
        if path:
            return path

    extension_root = Path.home() / ".vscode" / "extensions"
    extension_matches = sorted(
        extension_root.glob("openai.chatgpt-*/bin/windows-x86_64/codex.exe"),
        reverse=True,
    )
    for candidate in extension_matches:
        if candidate.exists():
            return str(candidate)

    for candidate in ["codex", "codex.cmd", "codex.exe"]:
        path = shutil.which(candidate)
        if path:
            return path
    return None


def _format_prompt(messages: Sequence[Message]) -> str:
    blocks: list[str] = [
        "You are running as the OpenJarvis brain via Codex CLI.",
        "Answer the user directly. Do not modify files or run shell commands.",
        "Keep spoken-assistant answers concise unless the user asks for detail.",
    ]
    for message in messages:
        role = message.role.value.upper()
        if message.content:
            blocks.append(f"{role}:\n{message.content}")
        if message.tool_calls:
            for tool_call in message.tool_calls:
                blocks.append(
                    f"{role} TOOL CALL {tool_call.name}:\n{tool_call.arguments}"
                )
    return "\n\n".join(blocks).strip()


def _shorten_error(text: str) -> str:
    clean = " ".join((text or "").split())
    if not clean:
        return "unknown Codex CLI error"
    return clean[:400]


def _run_codex_exec(
    prompt: str,
    *,
    command: str,
    model: str,
    timeout_seconds: float,
) -> str:
    out_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".txt",
            prefix="openjarvis-codex-",
            delete=False,
            mode="w",
            encoding="utf-8",
        ) as out_file:
            out_path = out_file.name

        sandbox = os.environ.get("OPENJARVIS_CODEX_SANDBOX", "read-only")
        reasoning = os.environ.get("OPENJARVIS_CODEX_REASONING", "low")
        cmd = [
            command,
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "-m",
            model,
            "-s",
            sandbox,
            "-c",
            f'model_reasoning_effort="{reasoning}"',
            "-o",
            out_path,
            prompt,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            raise EngineConnectionError(
                f"Codex CLI failed: {_shorten_error(result.stderr or result.stdout)}"
            )

        output = Path(out_path).read_text(encoding="utf-8", errors="replace").strip()
        return output or result.stdout.strip()
    except subprocess.TimeoutExpired as exc:
        raise EngineConnectionError("Codex CLI timed out") from exc
    finally:
        if out_path:
            try:
                Path(out_path).unlink()
            except OSError:
                pass


@EngineRegistry.register("codex_cli")
class CodexCLIEngine(InferenceEngine):
    """Inference through the locally authenticated Codex CLI."""

    engine_id = "codex_cli"
    is_cloud = False

    def __init__(self, *, command: str | None = None) -> None:
        self._command = _resolve_codex_path() if command is None else command

    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if not self._command:
            raise EngineConnectionError("Codex CLI not found")

        prompt = _format_prompt(messages)
        selected_model = model or os.environ.get("OPENJARVIS_CODEX_MODEL", "")
        selected_model = selected_model or _DEFAULT_MODEL
        timeout_seconds = float(
            os.environ.get("OPENJARVIS_CODEX_TIMEOUT", _DEFAULT_TIMEOUT_SECONDS)
        )
        content = _run_codex_exec(
            prompt,
            command=self._command,
            model=selected_model,
            timeout_seconds=timeout_seconds,
        )
        prompt_tokens = estimate_prompt_tokens(messages)
        completion_tokens = max(1, len(content) // 4)
        return {
            "content": content,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "prompt_tokens_evaluated": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "model": selected_model,
            "finish_reason": "stop",
        }

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        result = await asyncio.to_thread(
            self.generate,
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        yield result.get("content", "")

    def list_models(self) -> List[str]:
        return ["gpt-5.5", "gpt-5.4", "gpt-5.3-codex", "gpt-5.2"]

    def health(self) -> bool:
        return bool(self._command)
