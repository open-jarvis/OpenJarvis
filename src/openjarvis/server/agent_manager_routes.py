"""FastAPI routes for the Agent Manager."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from openjarvis.agents.manager import AgentManager

try:
    from fastapi import APIRouter, HTTPException, Request
    from pydantic import BaseModel
except ImportError:
    raise ImportError("fastapi and pydantic are required for server routes")


class CreateAgentRequest(BaseModel):
    name: str
    agent_type: str = "monitor_operative"
    config: Optional[Dict[str, Any]] = None
    template_id: Optional[str] = None


class UpdateAgentRequest(BaseModel):
    name: Optional[str] = None
    agent_type: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class CreateTaskRequest(BaseModel):
    description: str


class UpdateTaskRequest(BaseModel):
    description: Optional[str] = None
    status: Optional[str] = None
    progress: Optional[Dict[str, Any]] = None
    findings: Optional[List[Any]] = None


class BindChannelRequest(BaseModel):
    channel_type: str
    config: Optional[Dict[str, Any]] = None
    routing_mode: str = "dedicated"


class SendMessageRequest(BaseModel):
    content: str
    mode: str = "queued"


class FeedbackRequest(BaseModel):
    score: float
    reason: Optional[str] = None


_BROWSER_SUB_TOOLS = {
    "browser_navigate", "browser_click", "browser_type",
    "browser_screenshot", "browser_extract", "browser_axtree",
}


def _ensure_registries_populated() -> None:
    """Ensure ToolRegistry and ChannelRegistry are populated.

    If the registries are empty (e.g. cleared by test fixtures) but the
    modules are already cached in sys.modules, reload the individual
    submodules to re-execute their @register decorators.
    """
    import importlib
    import sys

    from openjarvis.core.registry import ChannelRegistry, ToolRegistry

    # First, try a normal import (works if modules haven't been imported yet)
    try:
        import openjarvis.channels  # noqa: F401
    except Exception:
        pass

    try:
        import openjarvis.tools  # noqa: F401
    except Exception:
        pass

    # Also try to import browser tools (not included in openjarvis.tools.__init__)
    for _browser_mod in ("openjarvis.tools.browser", "openjarvis.tools.browser_axtree"):
        try:
            importlib.import_module(_browser_mod)
        except Exception:
            pass

    # If registries are still empty, reload individual submodules from sys.modules
    if not ChannelRegistry.keys():
        for mod_name in list(sys.modules):
            if (
                mod_name.startswith("openjarvis.channels.")
                and not mod_name.endswith("_stubs")
            ):
                try:
                    importlib.reload(sys.modules[mod_name])
                except Exception:
                    pass

    if not ToolRegistry.keys():
        for mod_name in list(sys.modules):
            if (
                mod_name.startswith("openjarvis.tools.")
                and not mod_name.endswith("_stubs")
                and not mod_name.endswith("agent_tools")
            ):
                try:
                    importlib.reload(sys.modules[mod_name])
                except Exception:
                    pass

    # After reloading tools, also try browser tools if still not registered
    if not any(ToolRegistry.contains(n) for n in _BROWSER_SUB_TOOLS):
        for _browser_mod in (
            "openjarvis.tools.browser",
            "openjarvis.tools.browser_axtree",
        ):
            mod = sys.modules.get(_browser_mod)
            if mod is not None:
                try:
                    importlib.reload(mod)
                except Exception:
                    pass


def build_tools_list() -> List[Dict[str, Any]]:
    """Build unified tools list from ToolRegistry + ChannelRegistry."""
    import os

    from openjarvis.core.credentials import TOOL_CREDENTIALS
    from openjarvis.core.registry import ChannelRegistry, ToolRegistry

    _ensure_registries_populated()

    items: List[Dict[str, Any]] = []

    try:
        for name, tool_cls in ToolRegistry.items():
            if name in _BROWSER_SUB_TOOLS:
                continue
            spec = getattr(tool_cls, "spec", None)
            if callable(spec):
                try:
                    spec = spec(tool_cls)
                except Exception:
                    spec = None
            cred_keys = TOOL_CREDENTIALS.get(name, [])
            items.append({
                "name": name,
                "description": spec.description if spec else "",
                "category": spec.category if spec else "",
                "source": "tool",
                "requires_credentials": len(cred_keys) > 0,
                "credential_keys": cred_keys,
                "configured": (
                    all(bool(os.environ.get(k)) for k in cred_keys)
                    if cred_keys else True
                ),
            })
    except Exception:
        pass

    try:
        if any(ToolRegistry.contains(n) for n in _BROWSER_SUB_TOOLS):
            items.append({
                "name": "browser",
                "description": (
                    "Web browser automation"
                    " (navigate, click, type, screenshot, extract)"
                ),
                "category": "browser",
                "source": "tool",
                "requires_credentials": False,
                "credential_keys": [],
                "configured": True,
            })
    except Exception:
        pass

    try:
        for name, _cls in ChannelRegistry.items():
            cred_keys = TOOL_CREDENTIALS.get(name, [])
            items.append({
                "name": name,
                "description": f"{name.replace('_', ' ').title()} messaging channel",
                "category": "communication",
                "source": "channel",
                "requires_credentials": len(cred_keys) > 0,
                "credential_keys": cred_keys,
                "configured": (
                    all(bool(os.environ.get(k)) for k in cred_keys)
                    if cred_keys else True
                ),
            })
    except Exception:
        pass

    return items


def create_agent_manager_router(
    manager: AgentManager,
) -> Tuple[APIRouter, APIRouter, APIRouter, APIRouter]:
    """Create FastAPI routers with agent management endpoints.

    Returns a 4-tuple: (agents_router, templates_router, global_router, tools_router).
    """
    agents_router = APIRouter(prefix="/v1/managed-agents", tags=["managed-agents"])
    templates_router = APIRouter(prefix="/v1/templates", tags=["templates"])

    # ── Agent lifecycle ──────────────────────────────────────

    @agents_router.get("")
    async def list_agents():
        return {"agents": manager.list_agents()}

    @agents_router.post("")
    async def create_agent(req: CreateAgentRequest, request: Request):
        if req.template_id:
            agent = manager.create_from_template(
                req.template_id, req.name, overrides=req.config
            )
        else:
            agent = manager.create_agent(
                name=req.name, agent_type=req.agent_type, config=req.config
            )

        # Register with scheduler if cron/interval
        scheduler = getattr(request.app.state, "agent_scheduler", None)
        sched_type = (req.config or {}).get("schedule_type", "manual")
        if scheduler and sched_type in ("cron", "interval"):
            scheduler.register_agent(agent["id"])

        return agent

    @agents_router.get("/{agent_id}")
    async def get_agent(agent_id: str):
        agent = manager.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        return agent

    @agents_router.patch("/{agent_id}")
    async def update_agent(agent_id: str, req: UpdateAgentRequest):
        if not manager.get_agent(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        kwargs: Dict[str, Any] = {}
        if req.name is not None:
            kwargs["name"] = req.name
        if req.agent_type is not None:
            kwargs["agent_type"] = req.agent_type
        if req.config is not None:
            kwargs["config"] = req.config
        return manager.update_agent(agent_id, **kwargs)

    @agents_router.delete("/{agent_id}")
    async def delete_agent(agent_id: str):
        if not manager.get_agent(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        manager.delete_agent(agent_id)
        return {"status": "archived"}

    @agents_router.post("/{agent_id}/pause")
    async def pause_agent(agent_id: str):
        if not manager.get_agent(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        manager.pause_agent(agent_id)
        return {"status": "paused"}

    @agents_router.post("/{agent_id}/resume")
    async def resume_agent(agent_id: str):
        if not manager.get_agent(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        manager.resume_agent(agent_id)
        return {"status": "idle"}

    @agents_router.post("/{agent_id}/run")
    async def run_agent(agent_id: str):
        import threading

        agent = manager.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        if agent["status"] == "archived":
            raise HTTPException(status_code=400, detail="Agent is archived")

        # Auto-recover from error/needs_attention state
        if agent["status"] in ("error", "needs_attention"):
            manager.update_agent(agent_id, status="idle")

        # Acquire tick BEFORE spawning thread — prevents race
        try:
            manager.start_tick(agent_id)
        except ValueError:
            raise HTTPException(
                status_code=409, detail="Agent is already running"
            )

        def _run_tick():
            try:
                from openjarvis.agents.executor import AgentExecutor
                from openjarvis.core.events import get_event_bus
                from openjarvis.system import SystemBuilder

                executor = AgentExecutor(
                    manager=manager, event_bus=get_event_bus(),
                )
                try:
                    system = SystemBuilder().build()
                    executor.set_system(system)
                except Exception as build_err:
                    manager.end_tick(agent_id)
                    manager.update_agent(agent_id, status="error")
                    manager.update_summary_memory(
                        agent_id,
                        f"ERROR: Failed to build system: {build_err}",
                    )
                    return
                executor.execute_tick(agent_id)
            except Exception as exc:
                try:
                    manager.end_tick(agent_id)
                except Exception:
                    pass
                manager.update_agent(agent_id, status="error")
                manager.update_summary_memory(
                    agent_id,
                    f"ERROR: {exc}",
                )

        threading.Thread(target=_run_tick, daemon=True).start()
        return {"status": "running", "agent_id": agent_id}

    # ── Recover ──────────────────────────────────────────────

    @agents_router.post("/{agent_id}/recover")
    def recover_agent(agent_id: str):
        if not manager.get_agent(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        checkpoint = manager.recover_agent(agent_id)
        return {"recovered": True, "checkpoint": checkpoint}

    # ── Tasks ────────────────────────────────────────────────

    @agents_router.get("/{agent_id}/tasks")
    async def list_tasks(agent_id: str, status: Optional[str] = None):
        return {"tasks": manager.list_tasks(agent_id, status=status)}

    @agents_router.post("/{agent_id}/tasks")
    async def create_task(agent_id: str, req: CreateTaskRequest):
        if not manager.get_agent(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        return manager.create_task(agent_id, description=req.description)

    @agents_router.get("/{agent_id}/tasks/{task_id}")
    async def get_task(agent_id: str, task_id: str):
        task = manager._get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    @agents_router.patch("/{agent_id}/tasks/{task_id}")
    async def update_task(agent_id: str, task_id: str, req: UpdateTaskRequest):
        kwargs: Dict[str, Any] = {}
        if req.description is not None:
            kwargs["description"] = req.description
        if req.status is not None:
            kwargs["status"] = req.status
        if req.progress is not None:
            kwargs["progress"] = req.progress
        if req.findings is not None:
            kwargs["findings"] = req.findings
        return manager.update_task(task_id, **kwargs)

    @agents_router.delete("/{agent_id}/tasks/{task_id}")
    async def delete_task(agent_id: str, task_id: str):
        manager.delete_task(task_id)
        return {"status": "deleted"}

    # ── Channel bindings ─────────────────────────────────────

    @agents_router.get("/{agent_id}/channels")
    async def list_channels(agent_id: str):
        return {"bindings": manager.list_channel_bindings(agent_id)}

    @agents_router.post("/{agent_id}/channels")
    async def bind_channel(agent_id: str, req: BindChannelRequest):
        if not manager.get_agent(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        return manager.bind_channel(
            agent_id,
            channel_type=req.channel_type,
            config=req.config,
            routing_mode=req.routing_mode,
        )

    @agents_router.delete("/{agent_id}/channels/{binding_id}")
    async def unbind_channel(agent_id: str, binding_id: str):
        manager.unbind_channel(binding_id)
        return {"status": "unbound"}

    # ── Messaging ────────────────────────────────────────────

    @agents_router.get("/{agent_id}/messages")
    def list_messages(agent_id: str):
        return {"messages": manager.list_messages(agent_id)}

    @agents_router.post("/{agent_id}/messages")
    def send_message(agent_id: str, req: SendMessageRequest):
        agent = manager.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Auto-recover error-state agents on immediate messages
        if req.mode == "immediate" and agent["status"] in ("error", "needs_attention"):
            manager.update_agent(agent_id, status="idle")

        msg = manager.send_message(agent_id, req.content, mode=req.mode)
        return msg

    # ── State inspection ─────────────────────────────────────

    @agents_router.get("/{agent_id}/state")
    def get_agent_state(agent_id: str):
        agent = manager.get_agent(agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        return {
            "agent": agent,
            "tasks": manager.list_tasks(agent_id),
            "channels": manager.list_channel_bindings(agent_id),
            "messages": manager.list_messages(agent_id),
            "checkpoint": manager.get_latest_checkpoint(agent_id),
        }

    # ── Learning ─────────────────────────────────────────────

    @agents_router.get("/{agent_id}/learning")
    def get_learning_log(agent_id: str):
        if not manager.get_agent(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        return {"learning_log": manager.list_learning_log(agent_id)}

    @agents_router.post("/{agent_id}/learning/run")
    def trigger_learning(agent_id: str):
        if not manager.get_agent(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        from openjarvis.core.events import EventType, get_event_bus

        bus = get_event_bus()
        bus.publish(EventType.AGENT_LEARNING_STARTED, {"agent_id": agent_id})
        return {"status": "triggered"}

    # ── Traces ───────────────────────────────────────────────

    @agents_router.get("/{agent_id}/traces")
    def list_traces(agent_id: str, limit: int = 20):
        if not manager.get_agent(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        try:
            from openjarvis.core.config import load_config
            from openjarvis.traces.store import TraceStore

            config = load_config()
            store = TraceStore(config.traces.db_path or "~/.openjarvis/traces.db")
            traces = store.list_traces(agent=agent_id, limit=limit)
            return {
                "traces": [
                    {
                        "id": t.trace_id,
                        "outcome": t.outcome,
                        "duration": t.total_latency_seconds,
                        "started_at": t.started_at,
                        "steps": len(t.steps),
                        "metadata": t.metadata,
                    }
                    for t in traces
                ]
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @agents_router.get("/{agent_id}/traces/{trace_id}")
    def get_trace(agent_id: str, trace_id: str):
        try:
            from openjarvis.core.config import load_config
            from openjarvis.traces.store import TraceStore

            config = load_config()
            store = TraceStore(config.traces.db_path or "~/.openjarvis/traces.db")
            trace = store.get(trace_id)
            if trace is None:
                raise HTTPException(status_code=404, detail="Trace not found")
            return {
                "id": trace.trace_id,
                "agent": trace.agent,
                "outcome": trace.outcome,
                "duration": trace.total_latency_seconds,
                "started_at": trace.started_at,
                "steps": [
                    {
                        "step_type": s.step_type.value,
                        "input": s.input,
                        "output": s.output,
                        "duration": s.duration_seconds,
                        "metadata": s.metadata,
                    }
                    for s in trace.steps
                ],
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ── Templates ────────────────────────────────────────────

    @templates_router.get("")
    async def list_templates():
        return {"templates": AgentManager.list_templates()}

    @templates_router.post("/{template_id}/instantiate")
    async def instantiate_template(template_id: str, req: CreateAgentRequest):
        return manager.create_from_template(
            template_id, req.name, overrides=req.config
        )

    # ── Global agent endpoints ───────────────────────────────

    global_router = APIRouter(tags=["agents-global"])

    @global_router.get("/v1/agents/errors")
    def list_error_agents():
        all_agents = manager.list_agents()
        error_agents = [
            a
            for a in all_agents
            if a["status"] in ("error", "needs_attention", "stalled", "budget_exceeded")
        ]
        return {"agents": error_agents}

    @global_router.get("/v1/agents/health")
    def agents_health():
        all_agents = manager.list_agents()
        from collections import Counter

        counts = Counter(a["status"] for a in all_agents)
        return {
            "total": len(all_agents),
            "by_status": dict(counts),
        }

    # ── Tools & credentials ──────────────────────────────────

    tools_router = APIRouter(prefix="/v1/tools", tags=["tools"])

    @tools_router.get("")
    def list_tools():
        return {"tools": build_tools_list()}

    @tools_router.post("/{tool_name}/credentials")
    async def save_tool_credentials(tool_name: str, request: Request):
        from openjarvis.core.credentials import save_credential

        body = await request.json()
        saved = []
        for key, value in body.items():
            save_credential(tool_name, key, value)
            saved.append(key)
        return {"saved": saved}

    @tools_router.get("/{tool_name}/credentials/status")
    def credential_status(tool_name: str):
        from openjarvis.core.credentials import get_credential_status
        return get_credential_status(tool_name)

    return agents_router, templates_router, global_router, tools_router
