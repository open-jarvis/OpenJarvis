"""HTTP route: ``POST /api/research`` — agentic research over the knowledge store.

Drives :class:`openjarvis.agents.research_loop.ResearchAgent` and streams a
custom SSE event schema back to the client:

* ``search_call``     — about to invoke ``HybridSearch.search`` (with arguments)
* ``search_result``   — search returned (num_hits, top_titles)
* ``synthesis``       — final answer, emitted in word-window chunks for an
  incremental UX (the agent itself returns the full string in one shot;
  chunking happens in the router so we don't need to rewire the loop)
* ``done``            — sentinel marking the end of the stream

Clarify is **disabled for the web session** — the agent's clarify_handler is
overridden to return a fixed "no clarification available" string so the
loop never blocks waiting for terminal stdin. Bringing real clarify back
to the browser will require a two-step session protocol; that's a future
endpoint, not this one.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from openjarvis.agents.research_loop import (
    DEFAULT_PLANNER_MODEL,
    ResearchAgent,
)
from openjarvis.connectors.embeddings import OllamaEmbedder
from openjarvis.connectors.hybrid_search import HybridSearch
from openjarvis.connectors.store import KnowledgeStore
from openjarvis.core.config import DEFAULT_CONFIG_DIR, JarvisConfig, load_config
from openjarvis.core.types import TelemetryRecord
from openjarvis.engine._base import InferenceEngine
from openjarvis.engine._discovery import get_engine
from openjarvis.telemetry.store import TelemetryStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["research"])

_WEB_CLARIFY_RESPONSE = "no clarification available in web session"
_LEGACY_PLANNER_ENGINE = "ollama"

# Sentinel placed on the queue when the agent thread terminates.
_DONE = object()


def _first_nonempty(*values: str) -> str:
    for value in values:
        stripped = value.strip()
        if stripped:
            return stripped
    return ""


def _resolve_planner_config(
    config: JarvisConfig,
    *,
    active_engine_key: str = "",
    active_model: str = "",
    request_model: str = "",
) -> tuple[str, str]:
    """Resolve the planner engine/model for web Deep Research.

    Resolution order:

    1. explicit ``[deep_research]`` overrides,
    2. the active chat engine/request model,
    3. server/config defaults,
    4. legacy Ollama/gemma4 fallback for unconfigured installs.
    """
    engine_key = _first_nonempty(
        config.deep_research.engine,
        active_engine_key,
        config.engine.default,
        _LEGACY_PLANNER_ENGINE,
    )
    model = _first_nonempty(
        config.deep_research.model,
        request_model,
        active_model,
        config.server.model,
        config.intelligence.default_model,
        DEFAULT_PLANNER_MODEL,
    )
    return engine_key, model


def _build_planner_engine(
    config: JarvisConfig,
    *,
    active_engine: InferenceEngine | None = None,
    active_engine_key: str = "",
    active_model: str = "",
    request_model: str = "",
) -> tuple[str, InferenceEngine, str]:
    """Instantiate the exact configured planner engine.

    ``get_engine`` intentionally falls back to any healthy engine for general
    chat routing. Deep Research must not do that here: if the configured chat
    engine is LM Studio but unavailable, silently falling back to Ollama would
    recreate the issue this endpoint is fixing.
    """
    engine_key, model = _resolve_planner_config(
        config,
        active_engine_key=active_engine_key,
        active_model=active_model,
        request_model=request_model,
    )
    if active_engine is not None and not config.deep_research.engine.strip():
        if model and not active_engine.can_serve(model):
            raise RuntimeError(
                "Deep Research planner engine "
                f"{engine_key!r} cannot serve model {model!r}. "
                "Choose a compatible model or set [deep_research] engine/model "
                "in config.toml."
            )
        return engine_key, active_engine, model

    resolved = get_engine(config, engine_key=engine_key, model=model)
    if resolved is None or resolved[0] != engine_key:
        raise RuntimeError(
            "Deep Research planner engine "
            f"{engine_key!r} is unavailable or cannot serve model {model!r}. "
            "Start the configured engine, load the configured model, or set "
            "[deep_research] engine/model in config.toml."
        )
    resolved_key, engine = resolved
    return resolved_key, engine, model


def _record_research_telemetry(
    *,
    engine_key: str,
    model: str,
    usage: Dict[str, int],
    latency_seconds: float,
    energy_joules: float = 0.0,
    mean_power_watts: float = 0.0,
    peak_power_watts: float = 0.0,
    energy_method: str = "",
) -> None:
    """Persist a research run into the telemetry DB so /v1/savings includes it.

    GPU energy/power are sampled by ``_LiveGPUSampler`` during ``agent.run()``
    and passed through here. With these fields populated, the same
    ``/v1/telemetry/energy`` aggregation that powers the chat System panel
    rolls research into the same numbers — Power (W) and Energy (kJ) stop
    reading 0.0 after a research-only session.

    Failures are swallowed — telemetry persistence is best-effort and must
    never break the user-visible SSE stream.
    """
    if not usage:
        return
    db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
    try:
        store = TelemetryStore(db_path)
    except Exception as exc:  # noqa: BLE001
        logger.debug("research telemetry: cannot open %s: %s", db_path, exc)
        return
    try:
        rec = TelemetryRecord(
            timestamp=time.time(),
            model_id=model,
            engine=engine_key,
            agent="research",
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            prompt_tokens_evaluated=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            total_tokens=int(usage.get("total_tokens", 0)),
            latency_seconds=latency_seconds,
            energy_joules=energy_joules,
            gpu_energy_joules=energy_joules,
            power_watts=mean_power_watts,
            energy_method=energy_method,
            energy_vendor="nvidia" if energy_method else "",
            is_streaming=True,
            metadata={"peak_power_w": peak_power_watts} if peak_power_watts else {},
        )
        store.record(rec)
    except Exception as exc:  # noqa: BLE001
        logger.debug("research telemetry: failed to record: %s", exc)
    finally:
        try:
            store.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Live GPU sampler — streams power/energy events during agent.run()
# ---------------------------------------------------------------------------


class _LiveGPUSampler:
    """Background pynvml poller — emits live power and accumulated energy.

    Runs a small daemon thread for the lifetime of a research query.  Every
    ``interval_s`` seconds it samples instantaneous GPU power across all
    visible devices, rectangle-integrates it into a running energy total, and
    invokes ``on_sample`` so the SSE consumer can forward ``system_metrics``
    frames to the browser in real time.

    On systems without pynvml (or with no visible GPU), ``available`` is
    False and ``start()`` / ``stop()`` are no-ops — research still runs, the
    System panel just won't see live metrics for that session.
    """

    def __init__(
        self,
        on_sample: Callable[[float, float, float], None],
        interval_s: float = 0.75,
    ) -> None:
        self._on_sample = on_sample
        self._interval_s = interval_s
        self._handles: list = []
        self._pynvml = None
        self._available = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._energy_j = 0.0
        self._peak_w = 0.0
        self._power_sum = 0.0
        self._sample_count = 0
        self._t_start = 0.0
        self._t_last = 0.0
        try:
            # Suppress legacy pynvml deprecation FutureWarning (#389).
            import warnings as _warnings
            with _warnings.catch_warnings():
                _warnings.filterwarnings(
                    "ignore",
                    message=r"The pynvml package is deprecated.*",
                    category=FutureWarning,
                )
                import pynvml  # type: ignore

            pynvml.nvmlInit()
            count = pynvml.nvmlDeviceGetCount()
            self._handles = [
                pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(count)
            ]
            self._pynvml = pynvml
            self._available = bool(self._handles)
            if not self._available:
                pynvml.nvmlShutdown()
        except Exception as exc:  # noqa: BLE001
            logger.debug("research: pynvml unavailable, no live GPU metrics: %s", exc)
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def _poll_power_w(self) -> float:
        total = 0.0
        for h in self._handles:
            try:
                total += self._pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0
            except Exception:  # noqa: BLE001
                pass
        return total

    def _loop(self) -> None:
        while not self._stop.is_set():
            now = time.monotonic()
            p = self._poll_power_w()
            dt = now - self._t_last
            # Rectangle integration is fine at sub-second cadence; the chat
            # path uses the same approach in NvidiaEnergyMonitor's fallback.
            self._energy_j += p * dt
            self._t_last = now
            self._sample_count += 1
            self._power_sum += p
            if p > self._peak_w:
                self._peak_w = p
            try:
                self._on_sample(p, self._energy_j, now - self._t_start)
            except Exception as exc:  # noqa: BLE001
                logger.debug("research: on_sample callback raised: %s", exc)
            self._stop.wait(self._interval_s)

    def start(self) -> None:
        if not self._available:
            return
        self._t_start = time.monotonic()
        self._t_last = self._t_start
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> Dict[str, float]:
        if not self._available:
            return {
                "energy_j": 0.0,
                "mean_power_w": 0.0,
                "peak_power_w": 0.0,
                "duration_s": 0.0,
            }
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        duration = time.monotonic() - self._t_start
        mean = self._power_sum / self._sample_count if self._sample_count else 0.0
        try:
            self._pynvml.nvmlShutdown()
        except Exception:  # noqa: BLE001
            pass
        return {
            "energy_j": self._energy_j,
            "mean_power_w": mean,
            "peak_power_w": self._peak_w,
            "duration_s": duration,
        }


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class ResearchRequest(BaseModel):
    query: str = Field(..., description="Natural-language question to research.")
    # Preferred planner model from the active chat selector. Server-side
    # [deep_research] config can still override it when a dedicated planner is
    # desired.
    model: Optional[str] = Field(
        default=None, description="Preferred planner model for this request."
    )


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def _sse(event: Dict[str, Any]) -> str:
    """Serialize one event dict to an SSE ``data: ...\\n\\n`` frame."""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _chunk_synthesis(text: str, window_chars: int = 40) -> list[str]:
    """Slice synthesis text into client-streaming-friendly chunks.

    We break on word boundaries so partial deltas always render cleanly in
    the browser. Each chunk is roughly ``window_chars`` characters long.
    """
    if not text:
        return []
    tokens = re.findall(r"\S+\s*", text)
    chunks: list[str] = []
    buf = ""
    for tok in tokens:
        if len(buf) + len(tok) > window_chars and buf:
            chunks.append(buf)
            buf = tok
        else:
            buf += tok
    if buf:
        chunks.append(buf)
    return chunks


# ---------------------------------------------------------------------------
# Stream generator
# ---------------------------------------------------------------------------


async def _stream_research(
    query: str,
    *,
    active_engine: InferenceEngine | None = None,
    active_engine_key: str = "",
    active_model: str = "",
    request_model: str = "",
) -> AsyncGenerator[str, None]:
    """Drive ResearchAgent on a worker thread; yield SSE frames as they land.

    Three error envelopes — setup, worker, consumer — all funnel into the
    same two-frame contract: ``{"type": "error", ...}`` followed by
    ``{"type": "done", "usage": {...}}``. The client can rely on always
    seeing a ``done`` frame, even when the agent never started.
    """
    # Phase 1: setup. Failures here (planner engine down, DB locked, etc.)
    # yield error + done and return — nothing has been emitted yet so the
    # client gets a clean two-frame stream instead of a dangling connection.
    try:
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def on_event(event: Dict[str, Any]) -> None:
            # Called from the agent's worker thread; bounce onto the event loop.
            loop.call_soon_threadsafe(queue.put_nowait, event)

        config = load_config()
        engine_key, engine, model = _build_planner_engine(
            config,
            active_engine=active_engine,
            active_engine_key=active_engine_key,
            active_model=active_model,
            request_model=request_model,
        )

        # Each request gets its own thin set of connectors. Constructing them
        # is cheap (SQLite open + HTTP keepalive) and avoids state leaks
        # between concurrent requests.
        store = KnowledgeStore()
        embedder = OllamaEmbedder()
        if not embedder.is_available():
            logger.warning(
                "research: Ollama embedder unavailable; BM25-only retrieval."
            )
            embedder = None

        agent = ResearchAgent(
            engine=engine,
            search=HybridSearch(store, embedder),
            model=model,
            clarify_handler=lambda question: _WEB_CLARIFY_RESPONSE,
            on_event=on_event,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("research: setup failed before agent could run: %s", exc)
        yield _sse(
            {
                "type": "error",
                "message": f"Research failed: {type(exc).__name__}: {exc}",
            }
        )
        yield _sse({"type": "done", "usage": {}})
        return

    def _emit_live_sample(power_w: float, energy_j: float, duration_s: float) -> None:
        # Called from the sampler's worker thread — bounce onto the asyncio
        # loop so the SSE consumer sees the same queue ordering as agent
        # events. The frontend mirrors these into the System panel so Power
        # (W) and Energy (kJ) update live during the run.
        loop.call_soon_threadsafe(
            queue.put_nowait,
            {
                "type": "system_metrics",
                "power_w": round(power_w, 2),
                "energy_j": round(energy_j, 2),
                "duration_s": round(duration_s, 2),
            },
        )

    sampler = _LiveGPUSampler(on_sample=_emit_live_sample)

    def _run() -> None:
        t0 = time.time()
        sampler.start()
        try:
            result = agent.run(query)
            usage_dict = dict(result.usage)
            totals = sampler.stop()
            # Persist token usage *and* GPU energy/power so /v1/telemetry/energy
            # rolls research into the same Power/Energy numbers as chat —
            # this is what the launch-video System panel reads.
            _record_research_telemetry(
                engine_key=engine_key,
                model=model,
                usage=usage_dict,
                latency_seconds=time.time() - t0,
                energy_joules=totals["energy_j"],
                mean_power_watts=totals["mean_power_w"],
                peak_power_watts=totals["peak_power_w"],
                energy_method="polling" if sampler.available else "",
            )
            # Forward the aggregated token usage so the consumer can attach it
            # to the terminal `done` frame. Internal event type — never sent to
            # the client directly.
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "_usage", "usage": usage_dict},
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("research agent crashed: %s", exc)
            # Stop the sampler on failure too so we don't leak the polling thread
            # past the request lifetime.
            try:
                sampler.stop()
            except Exception:  # noqa: BLE001
                pass
            loop.call_soon_threadsafe(
                queue.put_nowait,
                {"type": "error", "message": f"{type(exc).__name__}: {exc}"},
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _DONE)

    task = asyncio.create_task(asyncio.to_thread(_run))

    final_answer: Optional[str] = None
    final_usage: Dict[str, int] = {}
    final_sources: List[Dict[str, Any]] = []
    try:
        while True:
            event = await queue.get()
            if event is _DONE:
                break
            if not isinstance(event, dict):
                continue

            etype = event.get("type")
            # Internal usage marker — capture for the done frame, don't forward.
            if etype == "_usage":
                final_usage = event.get("usage", {}) or {}
                continue
            # We translate the agent's `final_answer` event into a stream of
            # `synthesis` chunks so the client sees the answer materialize
            # incrementally rather than as a single blob. The accompanying
            # ``sources`` array is the renumbered, deduped citation list the
            # frontend should render under the final answer.
            if etype == "final_answer":
                final_answer = event.get("text", "")
                final_sources = list(event.get("sources") or [])
                for piece in _chunk_synthesis(final_answer or ""):
                    yield _sse({"type": "synthesis", "text": piece})
                if final_sources:
                    yield _sse(
                        {"type": "final_sources", "sources": final_sources}
                    )
                continue

            yield _sse(event)

        # If the agent thread crashed before producing a final answer, the
        # client still gets the error frame (emitted above) followed by done.
        # The done frame also carries the deduped sources so a client that
        # only listens for ``done`` still gets the canonical citation list.
        yield _sse(
            {"type": "done", "usage": final_usage, "sources": final_sources}
        )
    except Exception as exc:  # noqa: BLE001
        # Consumer loop crashed unexpectedly (e.g. JSON serialization fault,
        # logic bug). Surface a clean error frame rather than letting the
        # SSE connection die mid-stream.
        logger.exception("research: stream consumer crashed: %s", exc)
        yield _sse(
            {
                "type": "error",
                "message": f"Research failed: {type(exc).__name__}: {exc}",
            }
        )
        yield _sse(
            {"type": "done", "usage": final_usage, "sources": final_sources}
        )
    finally:
        # The worker may still be cleaning up (rarely) — make sure we don't
        # leak a dangling task. Swallow any straggler exception so a worker
        # failure during teardown doesn't escape the generator after we've
        # already emitted the terminal done frame.
        if not task.done():
            try:
                await task
            except Exception as exc:  # noqa: BLE001
                logger.debug("research: worker task ended with %s", exc)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.post("/research")
async def research(req: ResearchRequest, request: Request) -> StreamingResponse:
    """Run a research query and stream the agent's trace + synthesis via SSE.

    Response is ``text/event-stream`` with one JSON event per frame. See the
    module docstring for the schema; a final ``{"type": "done"}`` always
    terminates the stream so clients can detect end-of-response without
    parsing the underlying ``[DONE]`` sentinel used by OpenAI-style routes.
    """
    active_engine = getattr(request.app.state, "engine", None)
    active_model = str(getattr(request.app.state, "model", "") or "")
    active_engine_key = str(getattr(request.app.state, "engine_name", "") or "")
    if active_engine is not None and not active_engine_key:
        active_engine_key = str(getattr(active_engine, "engine_id", "") or "")
    return StreamingResponse(
        _stream_research(
            req.query,
            active_engine=active_engine,
            active_engine_key=active_engine_key,
            active_model=active_model,
            request_model=req.model or "",
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["router", "ResearchRequest"]
