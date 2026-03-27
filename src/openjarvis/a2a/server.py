"""A2A server — exposes agents via /.well-known/agent.json and /a2a/tasks."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from openjarvis.a2a.protocol import (
    A2AResponse,
    A2ATask,
    AgentCard,
    TaskState,
)
from openjarvis.core.events import EventBus, EventType


class A2AServer:
    """A2A server that processes incoming tasks via agent execution.

    Can be mounted as routes in the FastAPI server.
    """

    def __init__(
        self,
        agent_card: AgentCard,
        *,
        handler: Optional[Callable[[str], str]] = None,
        bus: Optional[EventBus] = None,
    ) -> None:
        self._card = agent_card
        self._handler = handler
        self._bus = bus
        self._tasks: Dict[str, A2ATask] = {}

    @property
    def agent_card(self) -> AgentCard:
        return self._card

    def handle_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process a JSON-RPC 2.0 A2A request."""
        method = request_data.get("method", "")
        params = request_data.get("params", {})
        req_id = request_data.get("id", "")

        if method == "tasks/send":
            return self._handle_task_send(params, req_id)
        elif method == "tasks/get":
            return self._handle_task_get(params, req_id)
        elif method == "tasks/cancel":
            return self._handle_task_cancel(params, req_id)
        else:
            return A2AResponse(
                error={"code": -32601, "message": f"Method not found: {method}"},
                request_id=req_id,
            ).to_dict()

    def _handle_task_send(self, params: Dict[str, Any], req_id: str) -> Dict[str, Any]:
        """Handle tasks/send — create and execute a task."""
        input_text = params.get("message", {}).get("parts", [{}])[0].get("text", "")
        if not input_text:
            input_text = params.get("input", "")

        task = A2ATask(input_text=input_text)
        self._tasks[task.task_id] = task

        if self._bus:
            self._bus.publish(
                EventType.A2A_TASK_RECEIVED,
                {"task_id": task.task_id, "input": input_text},
            )

        # Execute
        task.state = TaskState.WORKING
        try:
            if self._handler:
                result = self._handler(input_text)
            else:
                result = f"No handler configured for A2A task: {input_text}"
            task.output_text = result
            task.state = TaskState.COMPLETED
            task.history.append({"role": "agent", "content": result})
        except Exception as exc:
            task.output_text = str(exc)
            task.state = TaskState.FAILED

        if self._bus:
            self._bus.publish(
                EventType.A2A_TASK_COMPLETED,
                {"task_id": task.task_id, "state": task.state.value},
            )

        return A2AResponse(result=task.to_dict(), request_id=req_id).to_dict()

    def _handle_task_get(self, params: Dict[str, Any], req_id: str) -> Dict[str, Any]:
        """Handle tasks/get — retrieve task status."""
        task_id = params.get("id", "")
        task = self._tasks.get(task_id)
        if not task:
            return A2AResponse(
                error={"code": -32602, "message": f"Task not found: {task_id}"},
                request_id=req_id,
            ).to_dict()
        return A2AResponse(result=task.to_dict(), request_id=req_id).to_dict()

    def _handle_task_cancel(
        self,
        params: Dict[str, Any],
        req_id: str,
    ) -> Dict[str, Any]:
        """Handle tasks/cancel — cancel a running task."""
        task_id = params.get("id", "")
        task = self._tasks.get(task_id)
        if not task:
            return A2AResponse(
                error={"code": -32602, "message": f"Task not found: {task_id}"},
                request_id=req_id,
            ).to_dict()
        task.state = TaskState.CANCELED
        return A2AResponse(result=task.to_dict(), request_id=req_id).to_dict()

    def get_routes(self) -> List[Dict[str, Any]]:
        """Return route definitions for mounting in a web framework."""
        return [
            {
                "path": "/.well-known/agent.json",
                "method": "GET",
                "handler": "agent_card",
            },
            {"path": "/a2a/tasks", "method": "POST", "handler": "handle_request"},
        ]


__all__ = ["A2AServer"]
