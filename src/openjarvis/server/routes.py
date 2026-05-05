"""Route handlers for the OpenAI-compatible API server."""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from openjarvis.core.types import Message, Role
from openjarvis.server.models import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    Choice,
    ChoiceMessage,
    ComplexityInfo,
    DeltaMessage,
    ModelListResponse,
    ModelObject,
    StreamChoice,
    UsageInfo,
)

router = APIRouter()


class CloudKeyRequest(BaseModel):
    """Cloud API key update request from the local console."""

    key_name: str
    key_value: str = ""


_ALLOWED_CLOUD_KEYS = {
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENROUTER_API_KEY",
    "MINIMAX_API_KEY",
}


def _cloud_keys_path() -> Path:
    return Path.home() / ".openjarvis" / "cloud-keys.env"


def _read_cloud_keys(path: Path) -> dict[str, str]:
    keys: dict[str, str] = {}
    if not path.exists():
        return keys
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            keys[key.strip()] = value.strip()
    return keys


def _to_messages(chat_messages) -> list[Message]:
    """Convert Pydantic ChatMessage objects to core Message objects."""
    messages = []
    for m in chat_messages:
        role = Role(m.role) if m.role in {r.value for r in Role} else Role.USER
        messages.append(
            Message(
                role=role,
                content=m.content or "",
                name=m.name,
                tool_call_id=m.tool_call_id,
            )
        )
    return messages


def _component(
    component_id: str,
    label: str,
    status: str,
    detail: str,
    *,
    action: str = "",
    group: str = "runtime",
    critical: bool = False,
) -> dict[str, Any]:
    return {
        "id": component_id,
        "label": label,
        "status": status,
        "detail": detail,
        "action": action,
        "group": group,
        "critical": critical,
    }


def _http_json(url: str, *, timeout: float = 1.5) -> tuple[bool, Any, str]:
    try:
        with urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
        return True, json.loads(body), ""
    except (OSError, URLError, json.JSONDecodeError) as exc:
        return False, None, str(exc)


def _port_listening(host: str, port: int, *, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _run_command(cmd: list[str], *, cwd: Path | None = None, timeout: float = 6.0) -> tuple[int, str]:
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.returncode, result.stdout
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout if isinstance(exc.stdout, str) else ""
        return 124, output + f"\nTimed out after {timeout:.0f}s"
    except OSError as exc:
        return 127, str(exc)


def _read_latest_openclaw_report(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "exists": False,
            "path": str(path),
            "modified_at": None,
            "age_seconds": None,
            "security": {"critical": 0, "warn": 0, "info": 0},
            "highlights": [],
        }

    stat = path.stat()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""

    security = {"critical": 0, "warn": 0, "info": 0}
    for line in text.splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("summary:") and any(word in stripped for word in ("critical", "warn", "info")):
            for number, name in re.findall(r"(\d+)\s+(critical|warn|info)", stripped):
                security[name] = int(number)

    highlights: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("CRITICAL ", "WARN ")):
            highlights.append(stripped)
        if len(highlights) >= 4:
            break

    return {
        "exists": True,
        "path": str(path),
        "modified_at": stat.st_mtime,
        "age_seconds": max(0, int(time.time() - stat.st_mtime)),
        "security": security,
        "highlights": highlights,
    }


def _atop_python(atop_root: Path) -> str:
    candidates = [
        os.environ.get("ATOP_DEV_PYTHON", ""),
        str(atop_root / ".venv" / "bin" / "python"),
        "/opt/homebrew/bin/python3",
        "python3",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if candidate == "python3" or Path(candidate).exists():
            return candidate
    return "python3"


def _load_atop_agent_performance(atop_root: Path) -> dict[str, Any]:
    """Read ATOP_Dev's own agent scorecards without mutating its ledger."""
    result: dict[str, Any] = {
        "project_id": "atop_dev",
        "project_name": "ATOP_Dev",
        "root": str(atop_root),
        "status": "unavailable",
        "summary": {
            "agents": 0,
            "healthy": 0,
            "attention": 0,
            "no_data": 0,
            "runs_last_24h": 0,
            "avg_success_rate": 0.0,
        },
        "agents": [],
        "error": "",
    }
    if not atop_root.exists():
        result["error"] = f"ATOP_Dev root missing: {atop_root}"
        return result

    python_bin = _atop_python(atop_root)
    code, output = _run_command(
        [python_bin, "-m", "atop_agent_manager", "list", "--format", "json"],
        cwd=atop_root,
        timeout=8.0,
    )
    if code != 0:
        result["error"] = output.strip()[:800]
        return result

    try:
        profiles = json.loads(output)
    except json.JSONDecodeError as exc:
        result["error"] = f"ATOP_Dev agent list returned invalid JSON: {exc}"
        return result

    agents: list[dict[str, Any]] = []
    for profile in profiles if isinstance(profiles, list) else []:
        agent_id = profile.get("agent_id") if isinstance(profile, dict) else ""
        if not agent_id:
            continue
        score_code, score_output = _run_command(
            [
                python_bin,
                "-m",
                "atop_agent_manager",
                "scorecard",
                str(agent_id),
                "--format",
                "json",
            ],
            cwd=atop_root,
            timeout=8.0,
        )
        if score_code != 0:
            agents.append(
                {
                    "agent_id": agent_id,
                    "display_name": profile.get("display_name", agent_id),
                    "scorecard_status": "unavailable",
                    "catalog_status": profile.get("status", ""),
                    "stage": profile.get("stage", ""),
                    "runs_last_24h": 0,
                    "success_rate_last_20_runs": 0.0,
                    "median_duration_ms_last_20_runs": 0,
                    "last_run_status": "",
                    "last_run_started_at": "",
                    "latest_artifact_path": "",
                    "latest_failure_status": "scorecard_error",
                }
            )
            continue

        try:
            scorecard = json.loads(score_output)
        except json.JSONDecodeError:
            continue

        catalog = scorecard.get("catalog", {})
        run_summary = scorecard.get("run_summary", {})
        latest_failure = run_summary.get("latest_failure", {})
        agents.append(
            {
                "agent_id": agent_id,
                "display_name": catalog.get(
                    "display_name",
                    profile.get("display_name", agent_id),
                ),
                "scorecard_status": scorecard.get("scorecard_status", "unknown"),
                "catalog_status": catalog.get("status", profile.get("status", "")),
                "stage": catalog.get("stage", profile.get("stage", "")),
                "runs_last_24h": int(run_summary.get("runs_last_24h", 0) or 0),
                "success_rate_last_20_runs": float(
                    run_summary.get("success_rate_last_20_runs", 0.0) or 0.0
                ),
                "median_duration_ms_last_20_runs": int(
                    run_summary.get("median_duration_ms_last_20_runs", 0) or 0
                ),
                "last_run_status": run_summary.get("last_run_status", ""),
                "last_run_started_at": run_summary.get("last_run_started_at", ""),
                "latest_artifact_path": run_summary.get("latest_artifact_path", ""),
                "latest_failure_status": latest_failure.get("status", "")
                if isinstance(latest_failure, dict)
                else "",
            }
        )

    rates = [a["success_rate_last_20_runs"] for a in agents]
    healthy = sum(1 for a in agents if a["scorecard_status"] == "healthy")
    no_data = sum(1 for a in agents if a["scorecard_status"] == "no_data")
    attention = sum(
        1
        for a in agents
        if a["scorecard_status"] not in {"healthy", "no_data"}
    )
    result["agents"] = agents
    result["summary"] = {
        "agents": len(agents),
        "healthy": healthy,
        "attention": attention,
        "no_data": no_data,
        "runs_last_24h": sum(a["runs_last_24h"] for a in agents),
        "avg_success_rate": round(sum(rates) / len(rates), 4) if rates else 0.0,
    }
    result["status"] = "healthy" if attention == 0 else "attention"
    return result


@router.post("/v1/chat/completions")
async def chat_completions(request_body: ChatCompletionRequest, request: Request):
    """Handle chat completion requests (streaming and non-streaming)."""
    engine = request.app.state.engine
    agent = getattr(request.app.state, "agent", None)
    model = request_body.model

    # Inject memory context into messages before dispatching
    config = getattr(request.app.state, "config", None)
    memory_backend = getattr(request.app.state, "memory_backend", None)
    if (
        config is not None
        and memory_backend is not None
        and config.agent.context_from_memory
        and request_body.messages
    ):
        try:
            from openjarvis.tools.storage.context import ContextConfig, inject_context

            # Extract query from the last user message
            query_text = ""
            for m in reversed(request_body.messages):
                if m.role == "user" and m.content:
                    query_text = m.content
                    break

            if query_text:
                messages = _to_messages(request_body.messages)
                ctx_cfg = ContextConfig(
                    top_k=config.memory.context_top_k,
                    min_score=config.memory.context_min_score,
                    max_context_tokens=config.memory.context_max_tokens,
                )
                enriched = inject_context(
                    query_text,
                    messages,
                    memory_backend,
                    config=ctx_cfg,
                )
                # Rebuild request messages from enriched Message objects
                if len(enriched) > len(messages):
                    from openjarvis.server.models import ChatMessage

                    new_msgs = []
                    for msg in enriched:
                        new_msgs.append(
                            ChatMessage(
                                role=msg.role.value,
                                content=msg.content,
                                name=msg.name,
                                tool_call_id=getattr(msg, "tool_call_id", None),
                            )
                        )
                    request_body.messages = new_msgs
        except Exception:
            logging.getLogger("openjarvis.server").debug(
                "Memory context injection failed",
                exc_info=True,
            )

    # Run complexity analysis on the last user message
    complexity_info = None
    query_text_for_complexity = ""
    for m in reversed(request_body.messages):
        if m.role == "user" and m.content:
            query_text_for_complexity = m.content
            break
    if query_text_for_complexity:
        try:
            from openjarvis.learning.routing.complexity import (
                adjust_tokens_for_model,
                score_complexity,
            )

            cr = score_complexity(query_text_for_complexity)
            suggested = adjust_tokens_for_model(
                cr.suggested_max_tokens,
                model,
            )
            complexity_info = ComplexityInfo(
                score=cr.score,
                tier=cr.tier,
                suggested_max_tokens=suggested,
            )
            # Bump max_tokens when complexity suggests more than what
            # the client requested — never reduce below the request value.
            if suggested > request_body.max_tokens:
                request_body.max_tokens = suggested
        except Exception:
            logging.getLogger("openjarvis.server").debug(
                "Complexity analysis failed",
                exc_info=True,
            )

    if request_body.stream:
        bus = getattr(request.app.state, "bus", None)
        # Use the agent stream bridge only when tools are present (the
        # bridge runs agent.run() synchronously and word-splits the result,
        # so it can't stream tokens in real-time).  For plain chat, stream
        # directly from the engine for true token-by-token output.
        if agent is not None and bus is not None and request_body.tools:
            return await _handle_agent_stream(agent, bus, model, request_body)
        return await _handle_stream(engine, model, request_body, complexity_info)

    # Non-streaming: use agent if available, otherwise direct engine call
    if agent is not None:
        return _handle_agent(agent, model, request_body, complexity_info)

    bus = getattr(request.app.state, "bus", None)
    return _handle_direct(
        engine,
        model,
        request_body,
        bus=bus,
        complexity_info=complexity_info,
    )


def _handle_direct(
    engine,
    model: str,
    req: ChatCompletionRequest,
    bus=None,
    complexity_info=None,
) -> ChatCompletionResponse:
    """Direct engine call without agent."""
    messages = _to_messages(req.messages)
    kwargs: dict[str, Any] = {}
    if req.tools:
        kwargs["tools"] = req.tools
    if bus:
        from openjarvis.telemetry.wrapper import instrumented_generate

        result = instrumented_generate(
            engine,
            messages,
            model=model,
            bus=bus,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            **kwargs,
        )
    else:
        result = engine.generate(
            messages,
            model=model,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            **kwargs,
        )
    content = result.get("content", "")
    usage = result.get("usage", {})

    choice_msg = ChoiceMessage(role="assistant", content=content)
    # Include tool calls if present
    tool_calls = result.get("tool_calls")
    if tool_calls:
        choice_msg.tool_calls = [
            {
                "id": tc.get("id", ""),
                "type": "function",
                "function": {
                    "name": tc.get("name", ""),
                    "arguments": tc.get("arguments", "{}"),
                },
            }
            for tc in tool_calls
        ]

    return ChatCompletionResponse(
        model=model,
        choices=[
            Choice(
                message=choice_msg,
                finish_reason=result.get("finish_reason", "stop"),
            )
        ],
        usage=UsageInfo(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        ),
        complexity=complexity_info,
    )


def _handle_agent(
    agent,
    model: str,
    req: ChatCompletionRequest,
    complexity_info=None,
) -> ChatCompletionResponse:
    """Run through agent."""
    from openjarvis.agents._stubs import AgentContext

    # Build context from prior messages
    ctx = AgentContext()
    if len(req.messages) > 1:
        prior = _to_messages(req.messages[:-1])
        for m in prior:
            ctx.conversation.add(m)

    # Last message is the input
    input_text = req.messages[-1].content if req.messages else ""

    # Override agent model for this request if the caller specified one
    original_model = agent._model
    if model:
        agent._model = model
    try:
        result = agent.run(input_text, context=ctx)
    finally:
        agent._model = original_model

    usage = UsageInfo(
        prompt_tokens=result.metadata.get("prompt_tokens", 0),
        completion_tokens=result.metadata.get("completion_tokens", 0),
        total_tokens=result.metadata.get("total_tokens", 0),
    )

    # Include audio metadata if the agent produced audio (e.g. morning digest)
    audio_meta = None
    audio_path = result.metadata.get("audio_path", "")
    if audio_path:
        from pathlib import Path

        from openjarvis.server.models import AudioMeta

        if Path(audio_path).exists():
            audio_meta = AudioMeta(url="/api/digest/audio")

    return ChatCompletionResponse(
        model=model,
        choices=[
            Choice(
                message=ChoiceMessage(
                    role="assistant",
                    content=result.content,
                    audio=audio_meta,
                ),
                finish_reason="stop",
            )
        ],
        usage=usage,
        complexity=complexity_info,
    )


async def _handle_agent_stream(agent, bus, model, req):
    """Stream agent response with EventBus events via SSE."""
    from openjarvis.server.stream_bridge import create_agent_stream

    return await create_agent_stream(agent, bus, model, req)


async def _handle_stream(
    engine,
    model: str,
    req: ChatCompletionRequest,
    complexity_info=None,
):
    """Stream response using SSE format."""
    from openjarvis.server.cloud_router import (
        is_cloud_model,
        list_local_models,
        stream_cloud,
        stream_local,
    )

    messages = _to_messages(req.messages)
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    # Route directly to the right backend — bypasses engine routing entirely
    # so broken MultiEngine state can never misdirect requests.
    use_cloud = is_cloud_model(model)

    async def generate():
        # Send role chunk first
        first_chunk = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[
                StreamChoice(
                    delta=DeltaMessage(role="assistant"),
                )
            ],
        )
        yield f"data: {first_chunk.model_dump_json()}\n\n"

        try:
            # Cloud models → direct cloud API (reads keys from disk).
            # Local models → engine.stream() first so mock engines work in
            # tests.  Fall back to stream_local() only when the engine would
            # mis-route the request to a cloud backend (MultiEngine routing
            # confusion), which is detected by checking the routed engine's
            # is_cloud attribute.
            if use_cloud:
                token_iter = stream_cloud(
                    model, messages, req.temperature, req.max_tokens
                )
            else:
                # Use engine.stream() by default (preserves mock-engine
                # compatibility in tests).  Only fall back to stream_local()
                # when a real MultiEngine would mis-route the local model to a
                # cloud backend — detected via isinstance so mocks are not
                # accidentally matched.
                _use_local_fallback = False
                try:
                    from openjarvis.engine.multi import MultiEngine

                    _inner = getattr(engine, "_inner", engine)
                    if isinstance(_inner, MultiEngine):
                        _routed = _inner._engine_for(model)
                        if _routed is not None and getattr(_routed, "is_cloud", False):
                            _use_local_fallback = True
                except Exception:
                    pass
                if _use_local_fallback:
                    token_iter = stream_local(
                        model, messages, req.temperature, req.max_tokens
                    )
                else:
                    # If the selected model is installed in Ollama, route it
                    # to Ollama directly. This prevents the default MLX engine
                    # from receiving Ollama model IDs such as qwen3.5:latest.
                    if model in await list_local_models():
                        token_iter = stream_local(
                            model, messages, req.temperature, req.max_tokens
                        )
                    else:
                        token_iter = engine.stream(
                            messages,
                            model=model,
                            temperature=req.temperature,
                            max_tokens=req.max_tokens,
                        )
            async for token in token_iter:
                chunk = ChatCompletionChunk(
                    id=chunk_id,
                    model=model,
                    choices=[
                        StreamChoice(
                            delta=DeltaMessage(content=token),
                        )
                    ],
                )
                yield f"data: {chunk.model_dump_json()}\n\n"
        except Exception as exc:
            # Surface errors as a content chunk so the frontend can
            # display them instead of silently failing.
            import logging

            logging.getLogger("openjarvis.server").error(
                "Stream error: %s",
                exc,
                exc_info=True,
            )
            error_chunk = ChatCompletionChunk(
                id=chunk_id,
                model=model,
                choices=[
                    StreamChoice(
                        delta=DeltaMessage(
                            content=f"\n\nError during generation: {exc}",
                        ),
                        finish_reason="stop",
                    )
                ],
            )
            yield f"data: {error_chunk.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"
            return

        # Send finish chunk with usage data if available
        import json as _json

        finish_data = ChatCompletionChunk(
            id=chunk_id,
            model=model,
            choices=[
                StreamChoice(
                    delta=DeltaMessage(),
                    finish_reason="stop",
                )
            ],
        )
        finish_dict = _json.loads(finish_data.model_dump_json())

        # Tag the finish chunk with the correct engine label.
        # We use the routing decision (use_cloud) directly rather than
        # unwrapping the engine chain, which can be in a broken state.
        finish_dict.setdefault("telemetry", {})
        finish_dict["telemetry"]["engine"] = "cloud" if use_cloud else "ollama"

        if complexity_info is not None:
            finish_dict["complexity"] = complexity_info.model_dump()

        yield f"data: {_json.dumps(finish_dict)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/v1/models")
async def list_models(request: Request) -> ModelListResponse:
    """List locally installed models (Ollama).

    Cloud models are not included here — they live in the Cloud Models tab
    of the UI and are selected there, not from this endpoint.
    """
    from openjarvis.server.cloud_router import is_cloud_model, list_local_models

    # Prefer engine.list_models() so mock engines work in tests.
    # Filter out any cloud model IDs that may appear via MultiEngine.
    # Fall back to direct Ollama query only when the engine returns nothing.
    engine = request.app.state.engine
    all_ids = engine.list_models()
    model_ids = [m for m in all_ids if not is_cloud_model(m)]
    if not model_ids:
        model_ids = await list_local_models()

    return ModelListResponse(
        data=[ModelObject(id=mid) for mid in model_ids],
    )


@router.post("/v1/models/pull")
async def pull_model(request: Request):
    """Pull / download a model from the Ollama registry."""
    body = await request.json()
    model_name = body.get("model", "").strip()
    if not model_name:
        raise HTTPException(status_code=400, detail="'model' field is required")

    engine = request.app.state.engine
    engine_name = getattr(request.app.state, "engine_name", "")
    # Only Ollama supports pulling
    if engine_name != "ollama" and getattr(engine, "engine_id", "") != "ollama":
        raise HTTPException(
            status_code=501,
            detail="Model pulling is only supported with the Ollama engine",
        )

    import httpx as _httpx

    host = getattr(engine, "_host", "http://localhost:11434")
    client = _httpx.Client(base_url=host, timeout=600.0)
    try:
        resp = client.post(
            "/api/pull",
            json={"name": model_name, "stream": False},
        )
        resp.raise_for_status()
    except (_httpx.ConnectError, _httpx.TimeoutException) as exc:
        raise HTTPException(status_code=502, detail=f"Ollama unreachable: {exc}")
    except _httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Ollama error: {exc.response.text[:300]}",
        )
    finally:
        client.close()

    return {"status": "ok", "model": model_name}


@router.delete("/v1/models/{model_name:path}")
async def delete_model(model_name: str, request: Request):
    """Delete a model from Ollama."""
    engine = request.app.state.engine
    engine_name = getattr(request.app.state, "engine_name", "")
    if engine_name != "ollama" and getattr(engine, "engine_id", "") != "ollama":
        raise HTTPException(status_code=501, detail="Only supported with Ollama engine")

    import httpx as _httpx

    host = getattr(engine, "_host", "http://localhost:11434")
    client = _httpx.Client(base_url=host, timeout=30.0)
    try:
        resp = client.request(
            "DELETE",
            "/api/delete",
            json={"name": model_name},
        )
        resp.raise_for_status()
    except (_httpx.ConnectError, _httpx.TimeoutException) as exc:
        raise HTTPException(status_code=502, detail=f"Ollama unreachable: {exc}")
    except _httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Ollama error: {exc.response.text[:300]}",
        )
    finally:
        client.close()

    return {"status": "deleted", "model": model_name}


@router.post("/v1/cloud/reload")
async def reload_cloud_engine(request: Request):
    """Hot-reload cloud API keys and (re-)initialize the cloud engine.

    Called by the desktop app immediately after the user saves a cloud API
    key so that cloud models become available without a full app restart.
    """
    import os
    from pathlib import Path

    # Re-read ~/.openjarvis/cloud-keys.env and update the running process env.
    keys_path = Path.home() / ".openjarvis" / "cloud-keys.env"
    if keys_path.exists():
        for raw_line in keys_path.read_text().splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

    # Try to build a fresh CloudEngine.
    try:
        from openjarvis.engine.cloud import CloudEngine
        from openjarvis.engine.multi import MultiEngine

        cloud = CloudEngine()
        if not cloud.health():
            return {
                "status": "no_cloud",
                "message": "No cloud models available (check API keys)",
            }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

    # Locate the innermost engine, working through InstrumentedEngine layers.
    outer = request.app.state.engine
    inner = getattr(outer, "_inner", outer)

    if isinstance(inner, MultiEngine):
        # Replace or insert the cloud entry in the existing MultiEngine.
        new_engines = [(k, e) for k, e in inner._engines if k != "cloud"]
        new_engines.append(("cloud", cloud))
        inner._engines = new_engines
        inner._refresh_map()
    else:
        # Wrap the existing engine (which may be security-wrapped) with a new
        # MultiEngine that includes the cloud engine.
        engine_name = getattr(request.app.state, "engine_name", "local")
        new_multi = MultiEngine([(engine_name, inner), ("cloud", cloud)])
        if hasattr(outer, "_inner"):
            outer._inner = new_multi
        else:
            request.app.state.engine = new_multi
        request.app.state.engine_name = "multi"

    return {"status": "ok", "message": "Cloud engine reloaded"}


@router.post("/v1/cloud/keys")
async def save_cloud_key(payload: CloudKeyRequest, request: Request):
    """Persist a cloud API key for the local OpenJarvis server.

    Browser localStorage is not visible to the backend process. Store keys in
    ~/.openjarvis/cloud-keys.env, the file read by cloud_router.py at request
    time, and update the current process environment immediately.
    """
    key_name = payload.key_name.strip()
    key_value = payload.key_value.strip()
    if key_name not in _ALLOWED_CLOUD_KEYS:
        raise HTTPException(status_code=400, detail=f"Unsupported key: {key_name}")

    path = _cloud_keys_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = _read_cloud_keys(path)
    if key_value:
        keys[key_name] = key_value
        os.environ[key_name] = key_value
    else:
        keys.pop(key_name, None)
        os.environ.pop(key_name, None)

    content = "".join(f"{key}={value}\n" for key, value in sorted(keys.items()))
    path.write_text(content)
    try:
        path.chmod(0o600)
    except OSError:
        pass

    # Rebuild the cloud engine map if possible. Direct cloud_router requests
    # already read this file every call, so a reload failure should not block
    # key persistence.
    reload_status: dict[str, Any]
    try:
        reload_status = await reload_cloud_engine(request)
    except Exception as exc:
        reload_status = {"status": "error", "message": str(exc)}

    return {
        "status": "saved" if key_value else "removed",
        "key_name": key_name,
        "cloud_reload": reload_status,
    }


@router.get("/v1/savings")
async def savings(request: Request):
    """Return savings summary compared to cloud providers.

    Only includes telemetry from the current server session so that
    counters start at zero each time a new model + agent is launched.
    """
    from openjarvis.core.config import DEFAULT_CONFIG_DIR
    from openjarvis.server.savings import compute_savings, savings_to_dict
    from openjarvis.telemetry.aggregator import TelemetryAggregator

    db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
    if not db_path.exists():
        empty = compute_savings(0, 0, 0)
        return savings_to_dict(empty)

    session_start = getattr(request.app.state, "session_start", None)

    agg = TelemetryAggregator(db_path)
    try:
        summary = agg.summary(since=session_start)
        # Exclude cloud model tokens from savings — only local
        # inference counts toward cost savings.
        _cloud_prefixes = (
            "gpt-",
            "o1-",
            "o3-",
            "o4-",
            "claude-",
            "gemini-",
            "openrouter/",
        )
        local_models = [
            m
            for m in summary.per_model
            if not any(m.model_id.startswith(p) for p in _cloud_prefixes)
        ]
        result = compute_savings(
            prompt_tokens=sum(m.prompt_tokens for m in local_models),
            completion_tokens=sum(m.completion_tokens for m in local_models),
            total_calls=sum(m.call_count for m in local_models),
            session_start=session_start if session_start else 0.0,
            prompt_tokens_evaluated=sum(
                m.prompt_tokens_evaluated for m in local_models
            ),
        )
        return savings_to_dict(result)
    finally:
        agg.close()


@router.post("/v1/telemetry/reset")
async def reset_telemetry():
    """Clear all stored telemetry records.

    Useful after updating token-counting methodology — clears
    historical records that were computed under the old rules so
    that the savings dashboard and leaderboard submissions start
    fresh with corrected values.
    """
    from openjarvis.core.config import DEFAULT_CONFIG_DIR
    from openjarvis.telemetry.aggregator import TelemetryAggregator

    db_path = DEFAULT_CONFIG_DIR / "telemetry.db"
    if not db_path.exists():
        return {"status": "ok", "records_cleared": 0}

    agg = TelemetryAggregator(db_path)
    try:
        count = agg.clear()
    finally:
        agg.close()
    return {"status": "ok", "records_cleared": count}


@router.get("/v1/info")
async def server_info(request: Request):
    """Return server configuration: model, agent, engine."""
    configured_agent = getattr(request.app.state, "agent_name", None)
    if configured_agent:
        agent_id = configured_agent
    else:
        agent = getattr(request.app.state, "agent", None)
        agent_id = getattr(agent, "agent_id", None) if agent else None
    return {
        "model": getattr(request.app.state, "model", ""),
        "agent": agent_id,
        "engine": getattr(request.app.state, "engine_name", ""),
    }


@router.get("/v1/openclaw/health")
async def openclaw_health():
    """Return a fast OpenClaw operations health snapshot for the dashboard."""
    openjarvis_root = Path("/Users/paulsunny/Documents/OpenJarvis")
    openclaw_root = Path("/Users/paulsunny/Documents/openclaw-workspace")
    openclaw_home = Path("/Users/paulsunny/.openclaw")
    atop_root = Path("/Users/paulsunny/Documents/ATOP_Dev")
    report_path = Path("/Users/paulsunny/.openjarvis/reports/openclaw-management-latest.md")
    ollama_host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    local_model = os.environ.get("OPENJARVIS_LOCAL_MODEL", "gemma4-agent:e4b")
    legacy_mlx_expected = os.environ.get("OPENJARVIS_LEGACY_MLX_EXPECTED", "0") == "1"

    components: list[dict[str, Any]] = []
    recommendations: list[str] = []

    paths_ok = openjarvis_root.exists() and openclaw_root.exists() and openclaw_home.exists()
    components.append(
        _component(
            "paths",
            "Control Paths",
            "pass" if paths_ok else "fail",
            "OpenJarvis, OpenClaw workspace, and OpenClaw home are present."
            if paths_ok
            else "One or more required OpenJarvis/OpenClaw paths are missing.",
            action="Restore the missing workspace/home path before running recovery.",
            group="control-plane",
            critical=True,
        )
    )

    ok, tags, error = _http_json(f"{ollama_host}/api/tags")
    model_names = [m.get("name") for m in tags.get("models", [])] if ok and isinstance(tags, dict) else []
    components.append(
        _component(
            "ollama",
            "Local LLM Server",
            "pass" if ok else "fail",
            f"Ollama API is reachable at {ollama_host}."
            if ok
            else f"Ollama API is not reachable at {ollama_host}: {error}",
            action="Start Ollama or verify the local model service on port 11434.",
            group="local-llm",
            critical=True,
        )
    )
    model_ok = local_model in model_names
    components.append(
        _component(
            "local-model",
            "Primary Local Model",
            "pass" if model_ok else "fail",
            f"{local_model} is available in Ollama."
            if model_ok
            else f"{local_model} is not listed by Ollama.",
            action=f"Pull or recreate {local_model}, then rerun the health check.",
            group="local-llm",
            critical=True,
        )
    )

    gateway_ok = _port_listening("127.0.0.1", 18789)
    components.append(
        _component(
            "openclaw-gateway",
            "OpenClaw Gateway",
            "pass" if gateway_ok else "fail",
            "Gateway is listening on 127.0.0.1:18789."
            if gateway_ok
            else "Gateway is not listening on 127.0.0.1:18789.",
            action="Use OpenClaw's gateway restart path, then rerun gateway probes.",
            group="openclaw",
            critical=True,
        )
    )

    runtime_script = openclaw_root / "scripts" / "openclaw_runtime_status_fast.sh"
    if runtime_script.exists():
        code, output = _run_command([str(runtime_script)], timeout=8.0)
        runtime_ok = code == 0 and "gateway_state=running" in output and "port_18789=listening" in output
        detail = "Runtime fast check confirms gateway_state=running and port_18789=listening."
        if not runtime_ok:
            detail = "Runtime fast check did not confirm the expected gateway state."
        components.append(
            _component(
                "runtime-fast",
                "Runtime Fast Check",
                "pass" if runtime_ok else "warn",
                detail,
                action="Open the latest management report and inspect OpenClaw runtime output.",
                group="openclaw",
            )
        )
    else:
        components.append(
            _component(
                "runtime-fast",
                "Runtime Fast Check",
                "warn",
                "openclaw_runtime_status_fast.sh is missing.",
                action="Restore OpenClaw runtime status script in the OpenClaw workspace.",
                group="openclaw",
            )
        )

    pi_config = Path.home() / ".pi" / "agent" / "models.json"
    pi_ok = False
    pi_detail = "Pi model config is missing."
    if pi_config.exists():
        try:
            pi_data = json.loads(pi_config.read_text(encoding="utf-8"))
            provider = pi_data.get("providers", {}).get("openjarvis-ollama", {})
            models = provider.get("models", [])
            pi_ok = (
                provider.get("baseUrl") == "http://127.0.0.1:11434/v1"
                and any(m.get("id") == local_model for m in models if isinstance(m, dict))
            )
            pi_detail = f"Pi is routed to openjarvis-ollama / {local_model}." if pi_ok else "Pi config exists but is not routed to the primary local model."
        except (OSError, json.JSONDecodeError):
            pi_detail = "Pi model config could not be parsed."
    components.append(
        _component(
            "pi-routing",
            "Pi Coding Agent Route",
            "pass" if pi_ok else "warn",
            pi_detail,
            action=f"Point provider openjarvis-ollama to http://127.0.0.1:11434/v1 with {local_model}.",
            group="coding-agent",
        )
    )

    legacy_mlx_ok = _port_listening("127.0.0.1", 11435)
    legacy_mlx_status = "pass" if legacy_mlx_ok or not legacy_mlx_expected else "warn"
    if legacy_mlx_ok:
        legacy_mlx_detail = "Legacy MLX endpoint is listening on 127.0.0.1:11435."
    elif legacy_mlx_expected:
        legacy_mlx_detail = "Legacy MLX endpoint is expected but is not listening on 127.0.0.1:11435."
    else:
        legacy_mlx_detail = "Legacy MLX endpoint is intentionally inactive. Ollama/Gemma4 is the primary local runtime."
    components.append(
        _component(
            "legacy-mlx",
            "Legacy MLX Endpoint",
            legacy_mlx_status,
            legacy_mlx_detail,
            action="Set OPENJARVIS_LEGACY_MLX_EXPECTED=1 only if MLX is intentionally restored as a required runtime.",
            group="legacy",
        )
    )

    fatal_logs = ""
    gateway_log = openclaw_home / "logs" / "gateway.err.log"
    if gateway_log.exists():
        try:
            lines = gateway_log.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
            fatal_logs = "\n".join(
                line for line in lines if any(term in line.lower() for term in ("traceback", "fatal", "crash", "panic"))
            )
        except OSError:
            fatal_logs = ""
    components.append(
        _component(
            "fatal-logs",
            "Recent Fatal Signals",
            "pass" if not fatal_logs else "warn",
            "No recent fatal/crash/panic/traceback signals in gateway stderr."
            if not fatal_logs
            else "Recent fatal-class signals were found in gateway stderr.",
            action="Inspect OpenClaw gateway logs before restarting broad services.",
            group="observability",
        )
    )

    atop_agents = _load_atop_agent_performance(atop_root)
    atop_summary = atop_agents.get("summary", {})
    atop_status = atop_agents.get("status")
    if atop_status == "healthy":
        atop_component_status = "pass"
        atop_detail = (
            f"ATOP_Dev reports {atop_summary.get('healthy', 0)}/"
            f"{atop_summary.get('agents', 0)} managed agents healthy, "
            f"{atop_summary.get('runs_last_24h', 0)} run(s) in the last 24h."
        )
    elif atop_status == "attention":
        atop_component_status = "warn"
        atop_detail = (
            f"ATOP_Dev has {atop_summary.get('attention', 0)} agent(s) needing "
            f"attention across {atop_summary.get('agents', 0)} managed agents."
        )
    else:
        atop_component_status = "warn"
        atop_detail = atop_agents.get("error") or "ATOP_Dev agent scorecards are unavailable."
    components.append(
        _component(
            "atop-dev-agents",
            "ATOP_Dev Agent Performance",
            atop_component_status,
            atop_detail,
            action="Open ATOP_Dev scorecards before changing schedules, models, or promotion status.",
            group="project-agents",
        )
    )

    latest_report = _read_latest_openclaw_report(report_path)
    security = latest_report["security"]
    if security["critical"] > 0:
        components.append(
            _component(
                "security-audit",
                "OpenClaw Security Audit",
                "warn",
                f"Latest report contains {security['critical']} critical security finding(s).",
                action="Keep small local models sandboxed and web tools disabled for untrusted/tool-using OpenClaw work.",
                group="safety",
            )
        )
    elif latest_report["exists"]:
        components.append(
            _component(
                "security-audit",
                "OpenClaw Security Audit",
                "pass",
                "Latest report has no critical security findings.",
                action="Continue using the report before recovery actions.",
                group="safety",
            )
        )
    else:
        components.append(
            _component(
                "security-audit",
                "OpenClaw Security Audit",
                "warn",
                "No management report exists yet.",
                action="Run scripts/openclaw-management-check.sh to create the baseline report.",
                group="safety",
            )
        )

    failures = sum(1 for c in components if c["status"] == "fail")
    warnings = sum(1 for c in components if c["status"] == "warn")
    passes = sum(1 for c in components if c["status"] == "pass")
    critical_failures = sum(1 for c in components if c["status"] == "fail" and c["critical"])
    score = max(0, 100 - critical_failures * 30 - (failures - critical_failures) * 20 - warnings * 7)
    status = "healthy" if failures == 0 and warnings <= 1 else "degraded"
    if critical_failures:
        status = "critical"

    if critical_failures:
        recommendations.append("Fix critical runtime failures first: paths, Ollama/Gemma4, or Gateway.")
    if security["critical"] > 0:
        recommendations.append("Keep OpenClaw tool-using sessions sandboxed when local small models are enabled.")
    if not legacy_mlx_ok and legacy_mlx_expected:
        recommendations.append("Restore MLX only if it is intentionally configured as a required runtime.")
    if failures == 0:
        recommendations.append("Use the fast health summary as the daily gate; run the full report before repair or restart work.")

    return {
        "status": status,
        "score": score,
        "generated_at": time.time(),
        "summary": {"passes": passes, "warnings": warnings, "failures": failures},
        "primary_local_llm": {"host": ollama_host, "model": local_model},
        "paths": {
            "openjarvis_root": str(openjarvis_root),
            "openclaw_root": str(openclaw_root),
            "openclaw_home": str(openclaw_home),
        },
        "components": components,
        "recommendations": recommendations,
        "latest_report": latest_report,
        "project_agents": {
            "atop_dev": atop_agents,
        },
    }


@router.get("/health")
async def health(request: Request):
    """Health check endpoint."""
    engine = request.app.state.engine
    healthy = engine.health()
    if not healthy:
        raise HTTPException(status_code=503, detail="Engine unhealthy")
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Channel endpoints
# ---------------------------------------------------------------------------


@router.get("/v1/channels")
async def list_channels(request: Request):
    """List available messaging channels."""
    bridge = getattr(request.app.state, "channel_bridge", None)
    if bridge is None:
        return {"channels": [], "message": "Channel bridge not configured"}
    channels = bridge.list_channels()
    return {"channels": channels, "status": bridge.status().value}


@router.post("/v1/channels/send")
async def channel_send(request: Request):
    """Send a message to a channel."""
    bridge = getattr(request.app.state, "channel_bridge", None)
    if bridge is None:
        raise HTTPException(status_code=503, detail="Channel bridge not configured")

    body = await request.json()
    channel_name = body.get("channel", "")
    content = body.get("content", "")
    conversation_id = body.get("conversation_id", "")

    if not channel_name or not content:
        raise HTTPException(
            status_code=400,
            detail="'channel' and 'content' are required",
        )

    ok = bridge.send(channel_name, content, conversation_id=conversation_id)
    if not ok:
        raise HTTPException(status_code=502, detail="Failed to send message")
    return {"status": "sent", "channel": channel_name}


@router.get("/v1/channels/status")
async def channel_status(request: Request):
    """Return channel bridge connection status."""
    bridge = getattr(request.app.state, "channel_bridge", None)
    if bridge is None:
        return {"status": "not_configured"}
    return {"status": bridge.status().value}


# ---------------------------------------------------------------------------
# Security scan endpoint
# ---------------------------------------------------------------------------


@router.get("/v1/security/scan")
async def security_scan():
    """Run a read-only security environment audit and return findings."""
    from openjarvis.cli.scan_cmd import PrivacyScanner

    scanner = PrivacyScanner()
    results = scanner.run_all()
    return {
        "has_warnings": any(r.status == "warn" for r in results),
        "has_failures": any(r.status == "fail" for r in results),
        "findings": [
            {
                "name": r.name,
                "status": r.status,
                "message": r.message,
                "platform": r.platform,
            }
            for r in results
        ],
    }


__all__ = ["router"]
