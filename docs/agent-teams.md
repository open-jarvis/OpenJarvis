# Agent teams

Teams organize managed agents by company, client, or project. On the Agents page, choose **New team**, enter a name, then **Save team**. Names can include Arabic and other Unicode text.

Use the **Team** filter to switch between **All teams**, **Unassigned**, or an individual team. Counts reflect active, non-archived agents. Choose a team while creating an agent, or open an existing agent's **Overview** and change its **Team**. Creating an agent while a team is selected defaults its membership to that team.

Select a team to rename or delete it. Deleting a team moves its agents to Unassigned; it preserves the agents, their configurations, messages and tasks. Existing agents remain unassigned after upgrading until you explicitly move them.

Teams organize agents and provide independent company MCP connections, per-team memory and knowledge, and policy-controlled managed-agent messaging. They do not enforce tenant access controls, isolate the filesystem or non-MCP connectors, automatically run recipients, or configure publishing providers.

## API

- `GET /v1/managed-agents/teams`: list teams.
- `POST /v1/managed-agents/teams` with `{"name":"Company"}`: create a team.
- `PATCH /v1/managed-agents/teams/{team_id}` with `{"name":"New name"}`: rename.
- `DELETE /v1/managed-agents/teams/{team_id}`: delete the team and clear membership.
- `POST /v1/managed-agents` accepts an optional `team_id`, including with a template.
- `PATCH /v1/managed-agents/{agent_id}` accepts `team_id`; explicit `null` clears it, omission preserves it.
- `GET /v1/managed-agents?team_id=ID`: filter by team. An empty `team_id=` filters unassigned agents. Omit the parameter to list all agents.

A non-null unknown team ID is rejected on assignment. Team names are trimmed, contain 1–120 characters and are unique under SQLite's NOCASE comparison (ASCII case-insensitive). Membership is a nullable foreign key in the existing agents database and survives restarts. No separate service or dependency is required.

## Company accounts and connections

Select a team, then **Connections & communication** → **Add company connection**. Each team owns independent HTTP MCP connections with their own endpoint, provider/service name and bearer credential. For example, Company A and Company B may both use the same Gmail MCP endpoint with different access tokens. Clients and sessions are created independently for each team and turn. The configured provider name must be unique within a team; different teams may use the same provider name.

Only the team's connections are exposed to its agents. Neither a missing credential, discovery failure nor tool error falls back to the globally configured MCP account. Agent **Overview** includes an **Enable this team's connections** switch; an agent's explicit MCP opt-out remains effective. Global MCP behavior remains available to legacy agents that have never been assigned a team. Once an agent has been team-scoped, removing it from the team or deleting the team does not re-enable global accounts: assign it to another team to restore company connections. Existing team members are marked team-scoped during migration.

Credentials are stored in separate files beside the agents database under `team-connection-secrets/`, using the project's atomic owner-only write helper (0700 directory, 0600 files on POSIX). Tokens are not placed in process environment, agent config, API metadata, or prompts. This is local file protection, not encrypted credential storage or an OS-level tenant boundary. Removing a connection or deleting its team removes its credential file and blocks subsequent tool calls. Calls already in progress may finish. Deleting and recreating a connection is the supported credential replacement procedure.

The current connection flow supports Streamable HTTP MCP with a bearer token, or an explicitly unauthenticated server. HTTPS is required except for an explicitly local HTTP endpoint. URLs must not contain embedded credentials, query parameters or fragments. A provider's account-specific MCP endpoint/token must be obtained through its own authorization process. Built-in Google OAuth login, token refresh and stdio per-company profiles are not included. **Configured** means settings exist, not that Gmail or another account has been verified. No real company account is connected by installing this feature.

Tools are bound to the connection that discovered them and have stable connection-qualified names, preventing two identically named tools from resolving to another account. Runtime execution checks current agent membership, connection ownership and agent MCP opt-out. Each turn owns and closes its own private MCP clients; it never closes another team's or a global client's session.

## Team memory and knowledge

Each team has its own data folder beside the agents database, `team-data/<team_id>/` (0700 on POSIX), containing:

- `memory.db`: the store behind `memory_store`, `memory_search`, `memory_retrieve`, `memory_index` and `retrieval`, and behind the agent's own cross-tick memory and automatic context retrieval. It uses the configured `[memory] default_backend` when that backend is stored on disk, otherwise SQLite.
- `MEMORY.md`: the persona memory file injected into prompts and written by `memory_manage`. `SOUL.md` and `USER.md` (including a named persona) remain shared, because they describe the operator and persona rather than a client.
- `knowledge.db`: the store behind `knowledge_search`, `knowledge_sql`, `scan_chunks` and Deep Research for the team's agents. Add text with `POST /v1/managed-agents/teams/{team_id}/knowledge`. The global uploads and connector syncs still write to the global `knowledge.db`, which team agents never read.

Team agents never receive the global memory backend, global `MEMORY.md` or global knowledge store. Legacy agents that have never been assigned a team keep the global stores unchanged. A team-scoped agent removed from its team gets a private `team-data/_agents/<agent_id>/` area: it cannot read its former team's data, the global stores or other agents' data. Moving an agent to another team switches it to that team's data from its next turn.

Existing global memory and knowledge are not migrated into teams. Deleting a team keeps its `team-data/<team_id>/` folder on disk so no client data is lost; no agent can reach it afterwards, and you can remove the folder manually. Per-agent conversation history and summary memory were already stored per agent.

## Communication permissions

Agents may message other active agents in their own team. Cross-team messaging is denied by default and requires both teams to select each other under **Connections & communication**. Clear either side's checkbox and save to revoke permission. The receiving team gets a message, not access to the sender's accounts, tools, memory or conversation history.

The runtime binds `managed_agent_peers`, `managed_agent_message`, and `managed_connection_status` to the real source agent. The model cannot supply a different sender identity. Peer discovery exposes only the IDs, names and team IDs of currently reachable agents. Sending queues an attributed `agent_to_agent` message; it does not run the recipient automatically. The recipient consumes queued messages on its next managed tick, with peer content explicitly marked as untrusted rather than operator instructions. Pending messages are blocked if permission is revoked or either agent moves teams before delivery. Already consumed messages cannot be recalled.

This enforces account selection and messaging policy through managed-agent tool resolution and the managed message queue. Together with team memory and knowledge, this keeps each team's accounts and stored data apart. It is **not an OS-level sandbox**: file tools, shell/code execution, HTTP tools, global non-MCP connectors and channels retain their existing permissions, and can still reach other companies' files on the same machine (including another team's `team-data/` folder). Do not grant an agent general-purpose tools capable of accessing other companies' data and then treat these team controls as a security sandbox. Tenant authorization, filesystem isolation and separate execution identities remain additional work.

Additional endpoints:

- `PUT /v1/managed-agents/teams/{team_id}/policy` with `{"communicate_with":["other-team-id"]}`.
- `GET /v1/managed-agents/teams/{team_id}/connections`: credential-free metadata.
- `POST /v1/managed-agents/teams/{team_id}/connections` with `name`, `provider`, `url`, optional `auth_type` (`bearer` by default), and optional `token`. An empty bearer token leaves the connection awaiting authentication.
- `DELETE /v1/managed-agents/teams/{team_id}/connections/{connection_id}`: revoke only the connection owned by that team.
- `GET /v1/managed-agents/teams/{team_id}/knowledge`: number of chunks in the team's knowledge store.
- `POST /v1/managed-agents/teams/{team_id}/knowledge` with `content` and optional `title`: add text to the team's knowledge store only.

Validation errors from the connection endpoint list the failing fields without echoing the submitted body, so a token is never returned in a 422 response.
