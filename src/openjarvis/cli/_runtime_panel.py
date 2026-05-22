"""Interactive runtime panel: GPU offload and context window (Ollama)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

MAX_NUM_CTX = 200_000
MAX_NUM_GPU_LAYERS = 999


@dataclass(frozen=True, slots=True)
class ChatRuntimeOptions:
    """Per-session inference options chosen after model pick."""

    num_ctx: Optional[int] = None
    num_gpu: Optional[int] = None

    def to_engine_kwargs(self) -> dict[str, Any]:
        """Kwargs forwarded to ``InferenceEngine.generate()``."""
        out: dict[str, Any] = {}
        if self.num_ctx is not None and self.num_ctx > 0:
            out["num_ctx"] = min(int(self.num_ctx), MAX_NUM_CTX)
        if self.num_gpu is not None:
            # Ollama: large num_gpu = offload all layers; -1 means "all".
            if self.num_gpu < 0:
                out["num_gpu"] = MAX_NUM_GPU_LAYERS
            else:
                out["num_gpu"] = min(int(self.num_gpu), MAX_NUM_GPU_LAYERS)
        return out

    def summary(self, *, engine_name: str) -> str:
        parts: list[str] = []
        if self.num_ctx is not None and self.num_ctx > 0:
            parts.append(f"ctx={self.num_ctx:,}")
        else:
            parts.append("ctx=default")
        if engine_name == "ollama":
            if self.num_gpu is None:
                parts.append("gpu=default")
            elif self.num_gpu < 0:
                parts.append("gpu=all layers")
            elif self.num_gpu == 0:
                parts.append("gpu=0 (CPU)")
            else:
                parts.append(f"gpu={self.num_gpu} layers")
        return ", ".join(parts)


def tty_wants_runtime_panel(cli_skip: bool = False) -> bool:
    """Show runtime panel on TTY unless skipped."""
    import sys

    if cli_skip:
        return False
    skip = (os.environ.get("JARVIS_SKIP_RUNTIME_PANEL", "") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    return sys.stdin.isatty() and not skip


def _parse_int(raw: str, *, default: Optional[int]) -> Optional[int]:
    text = (raw or "").strip()
    if not text:
        return default
    try:
        return int(text.replace("_", "").replace(",", ""))
    except ValueError:
        return default


def interactive_pick_runtime_options(
    console: Any,
    *,
    engine_name: str,
    cli_num_ctx: Optional[int] = None,
    cli_num_gpu: Optional[int] = None,
) -> ChatRuntimeOptions:
    """Prompt for context size and GPU offload after model selection."""
    if cli_num_ctx is not None or cli_num_gpu is not None:
        return ChatRuntimeOptions(num_ctx=cli_num_ctx, num_gpu=cli_num_gpu)

    console.print(
        "\n[bold]Runtime[/bold] "
        "[dim](Enter = engine default; applies this session)[/dim]",
    )
    if engine_name == "ollama":
        console.print(
            "  [dim]num_ctx[/dim] — context window (tokens, max "
            f"{MAX_NUM_CTX:,}). [dim]num_gpu[/dim] — layers on GPU "
            "(-1 = all, 0 = CPU only).",
        )
    else:
        console.print(
            f"  [dim]num_ctx[/dim] only "
            f"([cyan]{engine_name}[/cyan] ignores GPU offload).",
        )

    try:
        raw_ctx = input(
            f"Max context tokens [0–{MAX_NUM_CTX}, 0=default]: ",
        )
    except (EOFError, KeyboardInterrupt):
        return ChatRuntimeOptions()

    num_ctx = _parse_int(raw_ctx, default=None)
    if num_ctx is not None:
        if num_ctx <= 0:
            num_ctx = None
        else:
            num_ctx = min(num_ctx, MAX_NUM_CTX)

    num_gpu: Optional[int] = None
    if engine_name == "ollama":
        try:
            raw_gpu = input(
                "GPU layer offload [-1=all, 0=CPU, N=layers, Enter=default]: ",
            )
        except (EOFError, KeyboardInterrupt):
            return ChatRuntimeOptions(num_ctx=num_ctx)
        parsed = _parse_int(raw_gpu, default=None)
        if parsed is not None:
            num_gpu = parsed

    opts = ChatRuntimeOptions(num_ctx=num_ctx, num_gpu=num_gpu)
    console.print(f"[dim]Runtime: {opts.summary(engine_name=engine_name)}[/dim]\n")
    return opts


def runtime_cli_options(command: Any) -> Any:
    """Click decorator: ``--num-ctx``, ``--num-gpu``, ``--skip-runtime-panel``."""
    import click

    command = click.option(
        "--num-ctx",
        type=int,
        default=None,
        help="Context window (tokens, max 200k). Skips runtime panel when set.",
    )(command)
    command = click.option(
        "--num-gpu",
        type=int,
        default=None,
        help="Ollama GPU layers (-1=all, 0=CPU). Skips runtime panel when set.",
    )(command)
    command = click.option(
        "--skip-runtime-panel",
        is_flag=True,
        default=False,
        help="Do not prompt for context/GPU after model pick.",
    )(command)
    return command


__all__ = [
    "MAX_NUM_CTX",
    "MAX_NUM_GPU_LAYERS",
    "ChatRuntimeOptions",
    "interactive_pick_runtime_options",
    "runtime_cli_options",
    "tty_wants_runtime_panel",
]
