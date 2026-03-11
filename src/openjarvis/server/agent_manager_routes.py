"""FastAPI routes for the Agent Manager."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from openjarvis.agents.manager import AgentManager

try:
    from fastapi import APIRouter, HTTPException
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


def create_agent_manager_router(
    manager: AgentManager,
) -> Tuple[APIRouter, APIRouter, APIRouter]:
    """Create FastAPI routers with agent management endpoints.

    Returns a 3-tuple: (agents_router, templates_router, global_router).
    """
    agents_router = APIRouter(prefix="/v1/managed-agents", tags=["managed-agents"])
    templates_router = APIRouter(prefix="/v1/templates", tags=["templates"])

    # ── Agent lifecycle ──────────────────────────────────────

    @agents_router.get("")
    async def list_agents():
        return {"agents": manager.list_agents()}

    @agents_router.post("")
    async def create_agent(req: CreateAgentRequest):
        if req.template_id:
            return manager.create_from_template(
                req.template_id, req.name, overrides=req.config
            )
        return manager.create_agent(
            name=req.name, agent_type=req.agent_type, config=req.config
        )

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
        agent = manager.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        try:
            manager.start_tick(agent_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return {"status": "running", "agent_id": agent_id}

    # ── Recover ──────────────────────────────────────────────

    @agents_router.post("/{agent_id}/recover")
    def recover_agent(agent_id: str):
        checkpoint = manager.recover_agent(agent_id)
        if checkpoint is None:
            raise HTTPException(status_code=404, detail="No checkpoint found")
        return checkpoint

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
        return {
            "total": len(all_agents),
            "running": sum(1 for a in all_agents if a["status"] == "running"),
            "error": sum(
                1 for a in all_agents if a["status"] in ("error", "needs_attention")
            ),
            "idle": sum(1 for a in all_agents if a["status"] == "idle"),
        }

    return agents_router, templates_router, global_router
