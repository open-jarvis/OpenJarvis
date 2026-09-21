"""In-process Apple Foundation Models (AFM 3) engine.

Drives Apple's ``apple_fm_sdk`` against the on-device model behind Apple
Intelligence, with no HTTP hop and no second process — so the energy measured
around a request is the energy the request actually cost. (The
``apple_fm_shim`` + ``apple_fm`` engine pair remains available for pointing
external OpenAI-compatible clients at the same model.)

Requires an Apple Silicon Mac on macOS 26+ with Apple Intelligence enabled,
and a full Xcode — not just Command Line Tools — because the SDK compiles
Swift bindings at install time::

    DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \\
        uv pip install -e '.[afm]'

    jarvis ask --engine afm --model afm-3-core "..."

Measurement caveats specific to this backend — read before comparing numbers
against MLX or Ollama:

* ``session.stream_response`` yields **cumulative text snapshots**, each
  batching roughly 8-10 tokens. ``ttft`` is therefore time-to-first-*chunk*
  (an upper bound on true TTFT — around 450ms on an M1 Pro versus a few tens
  of ms of real first-token latency), and derived inter-token latencies are
  inter-*chunk* latencies. Neither is comparable to a backend that streams one
  token at a time. Token counts, throughput and per-token energy are
  unaffected.
* The SDK exposes no way to select AFM 3 Core (dense ~3B) versus AFM 3 Core
  Advanced (20B sparse MoE, 1-4B active per request); the framework's dynamic
  profile picks one from the host device's capabilities. ``model`` is a run
  label only — :meth:`AppleFMEngine.describe` records the SDK version, context
  size and host chip so a run can be attributed after the fact.
* There is no Private Cloud Compute path in the Python SDK, which suits
  OpenJarvis: off-device inference would make the on-device energy
  measurement meaningless.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import subprocess
import time
from collections.abc import AsyncIterator, Sequence
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version
from typing import Any, Dict, List, Optional

# Top-level import on purpose: it gates registration. ``engine/__init__.py``
# imports this module inside a try/except, so on a host without the SDK the
# engine simply does not register.
import apple_fm_sdk as fm

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._apple_fm_support import (
    MODEL_LABELS,
    SnapshotAccumulator,
    build_options_kwargs,
    parse_sampling_spec,
    validate_model_label,
)
from openjarvis.engine._async_loop import AsyncLoopRunner
from openjarvis.engine._base import (
    EngineConnectionError,
    EngineContextLengthError,
    InferenceEngine,
)
from openjarvis.engine._stubs import StreamChunk

logger = logging.getLogger(__name__)

DEFAULT_MODEL_LABEL = "afm-3"


def _require(path: str) -> Any:
    """Fetch a dotted attribute from the SDK, or fail as an ImportError.

    An SDK that imports but lacks the surface this engine needs (anything
    below 0.2.1, which introduced ``token_count`` and ``context_size``) is an
    unusable install, not a broken engine. Raising ImportError lets
    ``engine/__init__.py``'s guarded import skip registration instead of
    letting an AttributeError take down every other engine.
    """
    obj: Any = fm
    for part in path.split("."):
        try:
            obj = getattr(obj, part)
        except AttributeError as exc:
            raise ImportError(
                f"apple_fm_sdk is missing {path!r}. The AFM engine needs "
                "apple-fm-sdk>=0.2.1; upgrade with "
                "`uv pip install -U 'apple-fm-sdk>=0.2.1'`."
            ) from exc
    return obj


_USE_CASES = {
    "general": _require("SystemLanguageModelUseCase.GENERAL"),
    "content_tagging": _require("SystemLanguageModelUseCase.CONTENT_TAGGING"),
}
_GUARDRAILS = {
    "default": _require("SystemLanguageModelGuardrails.DEFAULT"),
    "permissive_content_transformations": _require(
        "SystemLanguageModelGuardrails.PERMISSIVE_CONTENT_TRANSFORMATIONS"
    ),
}
# token_count / context_size are the 0.2.1 additions the engine's whole token
# accounting rests on -- check them at import so a stale SDK degrades to "not
# registered" rather than to silently zeroed usage.
_require("SystemLanguageModel.token_count")
_require("SystemLanguageModel.context_size")


def _resolve_error(name: str) -> Optional[type]:
    """Look an SDK exception class up by name.

    Resolved by name rather than imported so a future SDK release renaming one
    of these degrades to a narrower catch instead of breaking import outright.
    """
    exc = getattr(fm, name, None)
    if isinstance(exc, type) and issubclass(exc, BaseException):
        return exc
    return None


def _error_tuple(*names: str) -> tuple[type[BaseException], ...]:
    found = tuple(e for e in (_resolve_error(n) for n in names) if e is not None)
    if not found:  # pragma: no cover - guards a wholesale SDK rename
        logger.warning(
            "No known apple_fm_sdk error classes found among %s; AFM failures "
            "will surface as generic errors.",
            ", ".join(names),
        )
    return found


# Overflow is routine at a 4096-token context, and callers already have a
# dedicated "conversation too long" path for it.
_CONTEXT_ERRORS = _error_tuple("ExceededContextWindowSizeError")
# Refusals and guardrail trips are per-query outcomes, not engine faults: a
# long eval run must not die because one prompt was declined.
_REFUSAL_ERRORS = _error_tuple(
    "GuardrailViolationError",
    "RefusalError",
    "UnsupportedLanguageOrLocaleError",
)


def _host_chip() -> str:
    """Identify the Apple Silicon chip, e.g. "Apple M1 Pro".

    ``platform.processor()`` returns a bare "arm" on every Apple Silicon Mac,
    which is useless for the one job this has: the executing AFM variant is
    not observable, so the host chip is how a run gets attributed later.
    """
    try:
        result = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - host dependent
        return platform.processor() or platform.machine()
    return result.stdout.strip() or platform.processor() or platform.machine()


@EngineRegistry.register("afm")
class AppleFMEngine(InferenceEngine):
    """Apple Foundation Models, driven in-process via ``apple_fm_sdk``."""

    engine_id = "afm"

    def __init__(
        self,
        instructions: str = "",
        use_case: str = "general",
        guardrails: str = "default",
        sampling: str = "greedy",
    ) -> None:
        self._instructions = str(instructions or "").strip()
        self._use_case_name = str(use_case or "general").strip().lower()
        self._guardrails_name = str(guardrails or "default").strip().lower()
        self._sampling = str(sampling or "greedy").strip().lower()

        if self._use_case_name not in _USE_CASES:
            raise ValueError(
                f"Unknown AFM use_case {use_case!r}. Expected one of: "
                f"{', '.join(_USE_CASES)}."
            )
        if self._guardrails_name not in _GUARDRAILS:
            raise ValueError(
                f"Unknown AFM guardrails {guardrails!r}. Expected one of: "
                f"{', '.join(_GUARDRAILS)}."
            )
        # Validate eagerly so a typo fails at construction rather than midway
        # through a run.
        parse_sampling_spec({"sampling": self._sampling})

        self._model: Any = None
        self._context_size: Optional[int] = None
        self._prepared = False
        self._loop: Optional[AsyncLoopRunner] = None
        self._skipped: Dict[str, int] = {}

    # ---- lifecycle -------------------------------------------------------

    def _ensure_model(self) -> Any:
        if self._model is None:
            self._model = fm.SystemLanguageModel(
                use_case=_USE_CASES[self._use_case_name],
                guardrails=_GUARDRAILS[self._guardrails_name],
            )
        return self._model

    def _ensure_loop(self) -> AsyncLoopRunner:
        if self._loop is None:
            self._loop = AsyncLoopRunner(name="openjarvis-afm")
        return self._loop

    def health(self) -> bool:
        """Report on-device model availability.

        Returns a bool for the ABC, but logs the SDK's reason first: a bare
        False would hide whether the cause is Apple Intelligence being switched
        off, an ineligible device, or assets still downloading.
        """
        try:
            available, reason = self._ensure_model().is_available()
        except Exception as exc:  # pragma: no cover - depends on host state
            logger.warning("Could not initialize Apple Foundation Models: %s", exc)
            return False
        if not available:
            logger.warning(
                "Apple Foundation Models unavailable: %s. Check that Apple "
                "Intelligence is enabled in System Settings, that this device "
                "is eligible, and that model assets have finished downloading.",
                getattr(reason, "name", reason),
            )
        return bool(available)

    def list_models(self) -> List[str]:
        return list(MODEL_LABELS)

    def can_serve(self, model: str) -> bool:
        """Only the AFM labels — this engine cannot serve arbitrary model ids.

        Unlike the other local engines, "is the model installed" is not a
        separate concern here: there is exactly one on-device model, so
        accepting any id would let engine selection route e.g. a Llama request
        to AFM and silently answer with a different model.
        """
        return (model or "").strip().lower() in MODEL_LABELS

    def prepare(self, model: str) -> None:
        """Validate the label, then warm up outside the first energy window.

        The first request after boot pays a large one-off cost for model asset
        load and XPC setup (~10s versus ~450ms warm on an M1 Pro). Burning it
        here keeps it out of the telemetry window of the first real request.
        """
        validate_model_label(model)
        language_model = self._ensure_model()

        available, reason = language_model.is_available()
        if not available:
            raise EngineConnectionError(
                "Apple Foundation Models is unavailable "
                f"({getattr(reason, 'name', reason)}). Enable Apple "
                "Intelligence in System Settings and wait for model assets to "
                "download."
            )

        self._context_size = int(language_model.context_size)
        self._ensure_loop().run(self._warmup())
        self._prepared = True

    def close(self) -> None:
        if self._skipped:
            logger.warning(
                "AFM declined %d requests: %s",
                sum(self._skipped.values()),
                ", ".join(f"{k}={v}" for k, v in sorted(self._skipped.items())),
            )
        if self._loop is not None:
            self._loop.shutdown()
            self._loop = None
        self._model = None
        self._prepared = False

    def describe(self) -> Dict[str, Any]:
        """Run metadata. The executing variant is not observable, so the host
        chip and SDK version are the only way to attribute a run later."""
        try:
            sdk_version: Optional[str] = _dist_version("apple-fm-sdk")
        except PackageNotFoundError:  # pragma: no cover - installed by definition
            sdk_version = None
        return {
            "engine_id": self.engine_id,
            "afm_sdk_version": sdk_version,
            "afm_context_size": self._context_size,
            "afm_use_case": self._use_case_name,
            "afm_guardrails": self._guardrails_name,
            "afm_instructions": self._instructions or None,
            "afm_sampling": self._sampling,
            "host_chip": _host_chip(),
            "host_os_version": platform.mac_ver()[0] or None,
            "variant_selection": (
                "device-chosen by the Foundation Models dynamic profile; "
                "the model name is a label only"
            ),
            "declined_requests": dict(self._skipped) or None,
        }

    # ---- prompt / options ------------------------------------------------

    def _split_messages(self, messages: Sequence[Message]) -> tuple[str, str]:
        """Split *messages* into (instructions, prompt).

        System messages become the session's ``instructions``, which is where
        the SDK wants them — folding them into the prompt text (as the shim
        historically did) both loses that distinction and inflates the
        prompt-token count.
        """
        system_parts: List[str] = []
        if self._instructions:
            system_parts.append(self._instructions)
        prompt_parts: List[str] = []
        for m in messages:
            if m.role == Role.SYSTEM:
                system_parts.append(m.content)
            elif m.role in (Role.USER, Role.ASSISTANT):
                prompt_parts.append(m.content)
        return "\n".join(p for p in system_parts if p), "\n".join(prompt_parts)

    def _build_options(self, temperature: float, max_tokens: int) -> Any:
        kwargs = build_options_kwargs(
            {"temperature": temperature, "max_tokens": max_tokens}
        )
        mode, mode_kwargs = parse_sampling_spec({"sampling": self._sampling})
        factory = getattr(fm.SamplingMode, mode, None)
        if callable(factory):
            kwargs["sampling"] = factory(**mode_kwargs)
        return fm.GenerationOptions(**kwargs)

    def _new_session(self, instructions: str) -> Any:
        """A fresh session per request.

        Sessions accumulate a transcript, so reusing one would grow the prompt
        until it overflows the 4096-token context after a handful of requests,
        and would make per-request energy depend on preceding requests.
        """
        return fm.LanguageModelSession(
            instructions=instructions or None,
            model=self._ensure_model(),
        )

    # ---- token accounting ------------------------------------------------

    async def _count(self, *args: Any, **kwargs: Any) -> Optional[int]:
        """``token_count`` that degrades to ``None`` rather than failing."""
        try:
            return int(await self._ensure_model().token_count(*args, **kwargs))
        except Exception:
            logger.debug("AFM token_count failed", exc_info=True)
            return None

    @staticmethod
    def _usage(
        prompt_tokens: Optional[int],
        completion_tokens: Optional[int],
    ) -> Dict[str, int]:
        prompt = prompt_tokens or 0
        completion = completion_tokens or 0
        return {
            "prompt_tokens": prompt,
            "prompt_tokens_evaluated": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        }

    # ---- error mapping ---------------------------------------------------

    @staticmethod
    def _sdk_detail(exc: BaseException) -> str:
        """The SDK's own message, minus its noise.

        The SDK formats messages as "<reason>: <detail>" and passes ``None``
        as the detail when it has none, so the raw text ends in a dangling
        ": None". Left alone that reads as a bug in the error path rather
        than a plain context overflow, and it lands in every affected eval
        row.
        """
        text = str(exc).strip()
        while text.endswith(": None"):
            text = text[: -len(": None")].strip()
        return text

    def _translate(self, exc: BaseException) -> BaseException:
        if _CONTEXT_ERRORS and isinstance(exc, _CONTEXT_ERRORS):
            size = self._context_size or "the model's"
            detail = self._sdk_detail(exc)
            message = (
                f"Prompt exceeds the {size}-token context window for Apple "
                "Foundation Models"
            )
            # Only append the SDK's text when it says something the sentence
            # above does not already convey.
            if detail and "context window size exceeded" not in detail.lower():
                message = f"{message}: {detail}"
            return EngineContextLengthError(message)
        return exc

    def _note_declined(self, exc: BaseException) -> None:
        reason = type(exc).__name__
        self._skipped[reason] = self._skipped.get(reason, 0) + 1
        logger.warning("AFM declined a request (%s): %s", reason, exc)

    # ---- inference -------------------------------------------------------

    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str = DEFAULT_MODEL_LABEL,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if not self._prepared:
            self.prepare(model)
        return self._ensure_loop().run(
            self._respond(messages, model, temperature, max_tokens)
        )

    async def _respond(
        self,
        messages: Sequence[Message],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> Dict[str, Any]:
        instructions, prompt = self._split_messages(messages)
        options = self._build_options(temperature, max_tokens)
        session = self._new_session(instructions)

        # Token accounting: `token_count` rejects a value and instructions
        # together ("Provide either a value or instructions"), and counting
        # instructions standalone does not match how the transcript encodes
        # them. So both ends are measured against the transcript instead:
        #   prompt_tokens     = <transcript before generating> + <prompt alone>
        #   completion_tokens = <transcript after generating> - prompt_tokens
        pre_tokens = await self._count(session.transcript)
        prompt_only = await self._count(prompt)

        accumulator = SnapshotAccumulator()
        start = time.time()
        ttft = 0.0

        try:
            async for snapshot in session.stream_response(prompt, options=options):
                if not accumulator.add(snapshot):
                    continue
                if ttft == 0.0:
                    ttft = time.time() - start
        except _REFUSAL_ERRORS as exc:
            self._note_declined(exc)
            return {
                "content": "",
                "usage": self._usage(prompt_only, 0),
                "model": model,
                "finish_reason": "content_filter",
                "ttft": 0.0,
            }
        except Exception as exc:
            raise self._translate(exc) from exc

        post_tokens = await self._count(session.transcript)
        prompt_tokens = (
            pre_tokens + prompt_only
            if pre_tokens is not None and prompt_only is not None
            else prompt_only
        )
        completion_tokens = (
            max(post_tokens - prompt_tokens, 0)
            if post_tokens is not None and prompt_tokens is not None
            else None
        )

        return {
            "content": accumulator.text,
            "usage": self._usage(prompt_tokens, completion_tokens),
            "model": model,
            "finish_reason": "stop",
            "ttft": ttft,
        }

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str = DEFAULT_MODEL_LABEL,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        async for chunk in self.stream_full(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        ):
            if chunk.content:
                yield chunk.content

    async def stream_full(
        self,
        messages: Sequence[Message],
        *,
        model: str = DEFAULT_MODEL_LABEL,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        if not self._prepared:
            # prepare() blocks for the ~10s cold start; off-thread so it does
            # not stall the caller's event loop.
            await asyncio.to_thread(self.prepare, model)

        instructions, prompt = self._split_messages(messages)
        options = self._build_options(temperature, max_tokens)
        session = self._new_session(instructions)

        pre_tokens = await self._count(session.transcript)
        prompt_only = await self._count(prompt)
        accumulator = SnapshotAccumulator()

        try:
            async for snapshot in session.stream_response(prompt, options=options):
                delta = accumulator.add(snapshot)
                if delta:
                    yield StreamChunk(content=delta)
        except _REFUSAL_ERRORS as exc:
            self._note_declined(exc)
            yield StreamChunk(
                finish_reason="content_filter",
                usage=self._usage(prompt_only, 0),
            )
            return
        except Exception as exc:
            raise self._translate(exc) from exc

        post_tokens = await self._count(session.transcript)
        prompt_tokens = (
            pre_tokens + prompt_only
            if pre_tokens is not None and prompt_only is not None
            else prompt_only
        )
        completion_tokens = (
            max(post_tokens - prompt_tokens, 0)
            if post_tokens is not None and prompt_tokens is not None
            else None
        )
        yield StreamChunk(
            finish_reason="stop",
            usage=self._usage(prompt_tokens, completion_tokens),
        )

    async def _warmup(self) -> None:
        session = self._new_session(self._instructions)
        options = fm.GenerationOptions(maximum_response_tokens=4)
        async for _ in session.stream_response("warmup", options=options):
            pass


__all__ = ["AppleFMEngine"]
