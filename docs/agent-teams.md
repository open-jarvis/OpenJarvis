# Agent teams

Teams organize managed agents by company, client, or project. On the Agents page, choose **New team**, enter a name, then **Save team**. Names can include Arabic and other Unicode text.

Use the **Team** filter to switch between **All teams**, **Unassigned**, or an individual team. Counts reflect active, non-archived agents. Choose a team while creating an agent, or open an existing agent's **Overview** and change its **Team**. Creating an agent while a team is selected defaults its membership to that team.

Select a team to rename or delete it. Deleting a team moves its agents to Unassigned; it preserves the agents, their configurations, messages and tasks. Existing agents remain unassigned after upgrading until you explicitly move them.

Teams organize agents and provide independent company MCP connections, per-team memory and knowledge, and policy-controlled managed-agent messaging. They do not enforce tenant access controls, isolate the filesystem or non-MCP connectors, or automatically run recipients. Team connections are plain MCP servers; nothing is posted to any external service on your behalf.

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

Select a team, then **الإعدادات والاتصالات** (team settings) → **+ إضافة اتصال** (Add connection). Each team owns independent HTTP MCP connections with their own endpoint, provider/service name and bearer credential. For example, Company A and Company B may both use the same Gmail MCP endpoint with different access tokens. Clients and sessions are created independently for each team and turn. The configured provider name must be unique within a team; different teams may use the same provider name.

Only the team's connections are exposed to its agents. Neither a missing credential, discovery failure nor tool error falls back to the globally configured MCP account. Agent **Overview** includes an **Enable this team's connections** switch; an agent's explicit MCP opt-out remains effective. Global MCP behavior remains available to legacy agents that have never been assigned a team. Once an agent has been team-scoped, removing it from the team or deleting the team does not re-enable global accounts: assign it to another team to restore company connections. Existing team members are marked team-scoped during migration.

Credentials are stored in separate files beside the agents database under `team-connection-secrets/`, using the project's atomic owner-only write helper (0700 directory, 0600 files on POSIX). Tokens are not placed in process environment, agent config, API metadata, or prompts. This is local file protection, not encrypted credential storage or an OS-level tenant boundary. Removing a connection or deleting its team removes its credential file and blocks subsequent tool calls. Calls already in progress may finish. Deleting and recreating a connection is the supported credential replacement procedure.

The connection flow supports Streamable HTTP MCP with a bearer token, a custom header whose name you enter (for example `api_token`), or an explicitly unauthenticated server. **Test connection** connects with the team's credential and lists the server's tools; only then is it *Verified*. Each MCP connection can be limited to chosen team members. An agent passes a request file to an MCP tool as `campaign:<relative path>`; the runtime sends the file's bytes (base64) so images never pass through the model, and image URLs in the tool's result are downloaded into the request's `drafts/` and flagged for review. HTTPS is required except for an explicitly local HTTP endpoint. URLs must not contain embedded credentials, query parameters or fragments. A provider's account-specific MCP endpoint/token must be obtained through its own authorization process. Built-in Google OAuth login, token refresh and stdio per-company profiles are not included. **Configured** means settings exist, not that Gmail or another account has been verified. No real company account is connected by installing this feature.

Tools are bound to the connection that discovered them and have stable connection-qualified names, preventing two identically named tools from resolving to another account. Runtime execution checks current agent membership, connection ownership and agent MCP opt-out. Each turn owns and closes its own private MCP clients; it never closes another team's or a global client's session.

## Team memory and knowledge

Each team has its own data folder beside the agents database, `team-data/<team_id>/` (0700 on POSIX), containing:

- `memory.db`: the store behind `memory_store`, `memory_search`, `memory_retrieve`, `memory_index` and `retrieval`, and behind the agent's own cross-tick memory and automatic context retrieval. It uses the configured `[memory] default_backend` when that backend is stored on disk, otherwise SQLite.
- `MEMORY.md`: the persona memory file injected into prompts and written by `memory_manage`. `SOUL.md` and `USER.md` (including a named persona) remain shared, because they describe the operator and persona rather than a client.
- `knowledge.db`: the store behind `knowledge_search`, `knowledge_sql`, `scan_chunks` and Deep Research for the team's agents. Add text with `POST /v1/managed-agents/teams/{team_id}/knowledge`. The global uploads and connector syncs still write to the global `knowledge.db`, which team agents never read.

Team agents never receive the global memory backend, global `MEMORY.md` or global knowledge store. Legacy agents that have never been assigned a team keep the global stores unchanged. A team-scoped agent removed from its team gets a private `team-data/_agents/<agent_id>/` area: it cannot read its former team's data, the global stores or other agents' data. Moving an agent to another team switches it to that team's data from its next turn.

Existing global memory and knowledge are not migrated into teams. Deleting a team keeps its `team-data/<team_id>/` folder on disk so no client data is lost; no agent can reach it afterwards, and you can remove the folder manually. Per-agent conversation history and summary memory were already stored per agent.

## Talking to a team (orchestrator)

Each team has its own pages. Pick a team on **Agents** and open **صفحة الفريق والطلبات** (`/agents/teams/<team>`) for its members and requests, or **الإعدادات والاتصالات** (`/agents/teams/<team>/settings`) for its name, orchestrator, MCP connections, cross-team communication and deletion. Every request has its own page (`/agents/teams/<team>/requests/<request>`), so it can be bookmarked or shared.

Each team can have an **orchestrator**: one of its agents, chosen on the team settings page. Choose **طلب جديد للفريق** (New team request) to send the team a request with a title, the request text, original product photos, an approved logo, approved contact details and a run limit. The request goes to the orchestrator; you never pass results between agents yourself.

- The orchestrator assigns up to four **tasks** per run with `team_assign_tasks` (lead only). Each task **runs the receiving agent automatically**.
- When a member finishes, its reply returns to the orchestrator automatically as a **report**. Reports waiting for the orchestrator in the same request are delivered together in one run.
- `managed_agent_message` stays an informational message: it never runs its recipient.
- Follow-up messages from you on a request also go to the orchestrator.

Every request, task, report, file and status is stored in the agents database and the team's `team-data/<team_id>/campaigns/<request_id>/` folder (`originals/`, `drafts/`, `final/`), so work resumes after a restart. A run interrupted by a restart is requeued within its attempt budget.

Safety limits:

- Policy is checked when a handoff is created and again right before it runs: membership, both teams' communication consent, and the orchestrator role. A change in between blocks the handoff with a visible Arabic reason.
- One atomic claim per handoff; it never runs twice. A request has a run budget (default 16), at most 30 handoffs, depth 12 and four tasks per run. No self-handoffs.
- A **paused** agent is never resumed by the team: its tasks show *الوكيل موقوف* and start only after you resume it. Over-budget, errored or stalled agents block their tasks with an Arabic reason and a **retry** button.
- A run that returns nothing is retried once after a minute, then marked failed.
- Content written by agents is fenced in the recipient's prompt as untrusted data with no authority to change permissions, budgets or connections. Files cannot be shared with another team.

## Final images

A request ends with the exported PNG in the request's `final/` folder. The request page shows every final image at full width, newest first, with a **Download PNG** link; you review and use it yourself. To ask for changes, send the team a follow-up message on the same page.

## Communication permissions

Agents may message other active agents in their own team. Cross-team messaging is denied by default and requires both teams to select each other on their team settings pages. Clear either side's checkbox and save to revoke permission. The receiving team gets a message, not access to the sender's accounts, tools, memory or conversation history.

The runtime binds `managed_agent_peers`, `managed_agent_message`, and `managed_connection_status` to the real source agent. The model cannot supply a different sender identity. Peer discovery exposes only the IDs, names and team IDs of currently reachable agents. Sending queues an attributed `agent_to_agent` message; it does not run the recipient automatically. The recipient consumes queued messages on its next managed tick, with peer content explicitly marked as untrusted rather than operator instructions. Pending messages are blocked if permission is revoked or either agent moves teams before delivery. Already consumed messages cannot be recalled.

This enforces account selection, messaging and handoff policy through managed-agent tool resolution, the managed message queue and the handoff dispatcher. Together with team memory and knowledge, this keeps each team's accounts and stored data apart. It is **not an OS-level sandbox**: file tools, shell/code execution, HTTP tools, global non-MCP connectors and channels retain their existing permissions, and can still reach other companies' files on the same machine (including another team's `team-data/` folder). Do not grant an agent general-purpose tools capable of accessing other companies' data and then treat these team controls as a security sandbox. Tenant authorization, filesystem isolation and separate execution identities remain additional work.

Additional endpoints:

- `PUT /v1/managed-agents/teams/{team_id}/policy` with `{"communicate_with":["other-team-id"]}`.
- `GET /v1/managed-agents/teams/{team_id}/connections`: credential-free metadata.
- `POST /v1/managed-agents/teams/{team_id}/connections` with `name`, `provider`, `url`, optional `auth_type` (`bearer` by default), and optional `token`. An empty bearer token leaves the connection awaiting authentication.
- `DELETE /v1/managed-agents/teams/{team_id}/connections/{connection_id}`: revoke only the connection owned by that team.
- `POST /v1/managed-agents/teams/{team_id}/connections` also accepts non-secret `settings` (`header_name` for `auth_type: "header"`, `agent_ids`). `POST .../connections/{id}/verify` connects with the team's credential and lists the server's tools. `PUT .../connections/{id}/access` with `{"agent_ids": [...]}` limits a connection to chosen members (empty list = all).
- `PUT /v1/managed-agents/teams/{team_id}/lead` with `{"agent_id": ...}`: set or clear the orchestrator.
- `GET|POST /v1/managed-agents/teams/{team_id}/campaigns` (multipart: `title`, `brief`, `contact`, `max_runs`, `photos[]`, `logo`): list or send requests to the team.
- `GET /v1/managed-agents/campaigns/{id}`, `POST .../messages`, `POST .../cancel`, `GET .../file?path=`: request timeline, follow-ups, stop, and previews of files inside that request only.
- `POST /v1/managed-agents/handoffs/{id}/retry`: retry a blocked or failed handoff.
- `GET /v1/managed-agents/teams/{team_id}/knowledge`: number of chunks in the team's knowledge store.
- `POST /v1/managed-agents/teams/{team_id}/knowledge` with `content` and optional `title`: add text to the team's knowledge store only.

Validation errors from the connection endpoint list the failing fields without echoing the submitted body, so a token is never returned in a 422 response.
