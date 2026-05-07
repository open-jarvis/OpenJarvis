"""Railway GraphQL API client.

Talks to https://backboard.railway.app/graphql/v2 with a project- or
team-scoped ``RAILWAY_TOKEN``. Operations exposed match the public
Railway docs schema (subject to evolution). Mutating operations
(set_variable, redeploy, restart) require operator confirmation when
surfaced as model tools.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

GRAPHQL_URL = "https://backboard.railway.app/graphql/v2"


class RailwayUnavailableError(RuntimeError):
    """Raised when RAILWAY_TOKEN is missing or a GraphQL call fails."""


class RailwayClient:
    def __init__(self, token: Optional[str] = None, *, timeout: float = 20.0) -> None:
        self._token = token or os.environ.get("RAILWAY_TOKEN", "")
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self._token)

    def _query(
        self,
        query: str,
        variables: Optional[dict[str, Any]] = None,
    ) -> Any:
        if not self.configured:
            raise RailwayUnavailableError(
                "Railway not configured — set RAILWAY_TOKEN"
            )
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        payload = {"query": query, "variables": variables or {}}
        try:
            with httpx.Client(timeout=self._timeout) as c:
                resp = c.post(GRAPHQL_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise RailwayUnavailableError(f"Railway GraphQL failed: {exc}") from exc

        if data.get("errors"):
            raise RailwayUnavailableError(
                f"Railway GraphQL errors: {data['errors']}"
            )
        return data.get("data", {})

    # -- Read operations -----------------------------------------------

    def me(self) -> Any:
        return self._query("query { me { id name email } }")

    def list_projects(self) -> Any:
        q = """
        query {
          projects(first: 50) {
            edges { node { id name description createdAt } }
          }
        }
        """
        return self._query(q)

    def list_services(self, project_id: str) -> Any:
        q = """
        query($projectId: String!) {
          project(id: $projectId) {
            services {
              edges { node { id name } }
            }
          }
        }
        """
        return self._query(q, {"projectId": project_id})

    def get_service_variables(
        self,
        project_id: str,
        environment_id: str,
        service_id: str,
    ) -> Any:
        q = """
        query($projectId: String!, $environmentId: String!, $serviceId: String!) {
          variables(projectId: $projectId, environmentId: $environmentId, serviceId: $serviceId)
        }
        """
        return self._query(
            q,
            {
                "projectId": project_id,
                "environmentId": environment_id,
                "serviceId": service_id,
            },
        )

    # -- Mutating operations -------------------------------------------

    def upsert_variable(
        self,
        project_id: str,
        environment_id: str,
        service_id: str,
        name: str,
        value: str,
    ) -> Any:
        q = """
        mutation($input: VariableUpsertInput!) {
          variableUpsert(input: $input)
        }
        """
        return self._query(
            q,
            {
                "input": {
                    "projectId": project_id,
                    "environmentId": environment_id,
                    "serviceId": service_id,
                    "name": name,
                    "value": value,
                }
            },
        )

    def redeploy_service(
        self,
        service_id: str,
        environment_id: str,
    ) -> Any:
        q = """
        mutation($serviceId: String!, $environmentId: String!) {
          serviceInstanceRedeploy(serviceId: $serviceId, environmentId: $environmentId)
        }
        """
        return self._query(
            q,
            {"serviceId": service_id, "environmentId": environment_id},
        )

    def deployment_logs(
        self,
        deployment_id: str,
        *,
        limit: int = 200,
    ) -> Any:
        q = """
        query($deploymentId: String!, $limit: Int!) {
          deploymentLogs(deploymentId: $deploymentId, limit: $limit) {
            timestamp
            message
          }
        }
        """
        return self._query(q, {"deploymentId": deployment_id, "limit": limit})


_default: Optional[RailwayClient] = None


def get_default_client() -> RailwayClient:
    global _default
    if _default is None:
        _default = RailwayClient()
    return _default


__all__ = ["RailwayClient", "RailwayUnavailableError", "get_default_client"]
