# Agent teams

Teams organize managed agents by company, client, or project. On the Agents page, choose **New team**, enter a name, then **Save team**. Names can include Arabic and other Unicode text.

Use the **Team** filter to switch between **All teams**, **Unassigned**, or an individual team. Counts reflect active, non-archived agents. Choose a team while creating an agent, or open an existing agent's **Overview** and change its **Team**. Creating an agent while a team is selected defaults its membership to that team.

Select a team to rename or delete it. Deleting a team moves its agents to Unassigned; it preserves the agents, their configurations, messages and tasks. Existing agents remain unassigned after upgrading until you explicitly move them.

Teams provide organizational grouping. They do not enforce tenant access controls, isolate memory backends or chat data, share prompts, automatically hand work between agents, or configure external publishing providers.

## API

- `GET /v1/managed-agents/teams`: list teams.
- `POST /v1/managed-agents/teams` with `{"name":"Company"}`: create a team.
- `PATCH /v1/managed-agents/teams/{team_id}` with `{"name":"New name"}`: rename.
- `DELETE /v1/managed-agents/teams/{team_id}`: delete the team and clear membership.
- `POST /v1/managed-agents` accepts an optional `team_id`, including with a template.
- `PATCH /v1/managed-agents/{agent_id}` accepts `team_id`; explicit `null` clears it, omission preserves it.
- `GET /v1/managed-agents?team_id=ID`: filter by team. An empty `team_id=` filters unassigned agents. Omit the parameter to list all agents.

A non-null unknown team ID is rejected on assignment. Team names are trimmed, contain 1–120 characters and are unique under SQLite's NOCASE comparison (ASCII case-insensitive). Membership is a nullable foreign key in the existing agents database and survives restarts. No separate service or dependency is required.
