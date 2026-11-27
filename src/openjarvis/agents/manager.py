"""Persistent agent lifecycle manager.

Composition layer — stores agent state in SQLite, delegates all computation
to the five existing primitives (Intelligence, Agent, Tools, Engine, Learning).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
import uuid
from functools import wraps
from typing import Any, Dict, List, Optional
from uuid import uuid4

from openjarvis.core.paths import get_config_dir

logger = logging.getLogger(__name__)

_CREATE_AGENTS = """\
CREATE TABLE IF NOT EXISTS managed_agents (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    agent_type      TEXT NOT NULL DEFAULT 'monitor_operative',
    config_json     TEXT NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'idle',
    summary_memory  TEXT NOT NULL DEFAULT '',
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
"""

_CREATE_TEAMS = """\
CREATE TABLE IF NOT EXISTS agent_teams (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    created_at REAL NOT NULL
);
"""

_CREATE_TASKS = """\
CREATE TABLE IF NOT EXISTS agent_tasks (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL REFERENCES managed_agents(id),
    description     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    progress_json   TEXT NOT NULL DEFAULT '{}',
    findings_json   TEXT NOT NULL DEFAULT '[]',
    created_at      REAL NOT NULL
);
"""

_CREATE_BINDINGS = """\
CREATE TABLE IF NOT EXISTS channel_bindings (
    id              TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL REFERENCES managed_agents(id),
    channel_type    TEXT NOT NULL,
    config_json     TEXT NOT NULL DEFAULT '{}',
    session_id      TEXT,
    routing_mode    TEXT NOT NULL DEFAULT 'dedicated'
);
"""

_CREATE_CHECKPOINTS = """\
CREATE TABLE IF NOT EXISTS agent_checkpoints (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES managed_agents(id),
    tick_id TEXT NOT NULL,
    conversation_state TEXT NOT NULL DEFAULT '{}',
    tool_state TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL
);
"""

_CREATE_MESSAGES = """\
CREATE TABLE IF NOT EXISTS agent_messages (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES managed_agents(id),
    direction TEXT NOT NULL,
    content TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'queued',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL
);
"""

_CREATE_LEARNING_LOG = """\
CREATE TABLE IF NOT EXISTS agent_learning_log (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    description TEXT,
    data TEXT,
    created_at REAL NOT NULL
);
"""

# Rolling summary fed back into the next tick's prompt, so it stays bounded —
# but 2000 chars clipped real research reports mid-sentence (the findings the
# UI/CLI show come from here). 16k (~4k tokens) holds a full report while
# keeping per-tick prompt growth in check.
_SUMMARY_MAX = 16000


def _db_locked(func):
    """Serialize access to the connection shared by manager worker threads."""

    @wraps(func)
    def wrapped(self, *args, **kwargs):
        with self._db_lock:
            return func(self, *args, **kwargs)

    return wrapped


class AgentManager:
    """Persistent agent lifecycle manager with SQLite backing."""

    # A tick that hasn't touched its DB row in this many seconds is treated
    # as a zombie (its worker died without running end_tick). start_tick()
    # will overtake such a lock instead of refusing forever. The executor
    # bumps updated_at at start and on every tool/inference event, so a live
    # tick stays well under this window.
    _STALE_TICK_SECONDS = 600

    def __init__(self, db_path: str, *, clear_stale_running: bool = False) -> None:
        self._db_path = str(db_path)
        self._db_lock = threading.RLock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute(_CREATE_TEAMS)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS team_mcp_connections (
                id TEXT PRIMARY KEY,
                team_id TEXT NOT NULL REFERENCES agent_teams(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                provider TEXT NOT NULL COLLATE NOCASE,
                url TEXT NOT NULL,
                auth_type TEXT NOT NULL,
                created_at REAL NOT NULL,
                UNIQUE(team_id, name),
                UNIQUE(team_id, provider)
            )
        """)
        self._conn.execute(_CREATE_AGENTS)
        self._conn.execute(_CREATE_TASKS)
        self._conn.execute(_CREATE_BINDINGS)
        self._conn.executescript(_CREATE_CHECKPOINTS)
        self._conn.executescript(_CREATE_MESSAGES)
        self._conn.executescript(_CREATE_LEARNING_LOG)
        self._conn.commit()
        # Schema migrations for runtime columns
        _MIGRATIONS = [
            "ALTER TABLE managed_agents ADD COLUMN total_tokens INTEGER DEFAULT 0",
            "ALTER TABLE managed_agents ADD COLUMN total_cost REAL DEFAULT 0",
            "ALTER TABLE managed_agents ADD COLUMN total_runs INTEGER DEFAULT 0",
            "ALTER TABLE managed_agents ADD COLUMN last_run_at REAL",
            "ALTER TABLE managed_agents ADD COLUMN last_activity_at REAL",
            "ALTER TABLE managed_agents ADD COLUMN stall_retries INTEGER DEFAULT 0",
            "ALTER TABLE managed_agents ADD COLUMN current_activity TEXT DEFAULT ''",
            "ALTER TABLE managed_agents ADD COLUMN input_tokens INTEGER DEFAULT 0",
            "ALTER TABLE managed_agents ADD COLUMN output_tokens INTEGER DEFAULT 0",
            # JSON-encoded array of {tool, arguments, result, success, latency}
            "ALTER TABLE agent_messages ADD COLUMN tool_calls TEXT",
        ]
        _MIGRATIONS.append(
            "ALTER TABLE managed_agents ADD COLUMN team_scoped "
            "INTEGER NOT NULL DEFAULT 0"
        )
        _MIGRATIONS.append(
            "ALTER TABLE managed_agents ADD COLUMN team_id TEXT "
            "REFERENCES agent_teams(id) ON DELETE SET NULL"
        )
        for migration in _MIGRATIONS:
            try:
                self._conn.execute(migration)
            except sqlite3.OperationalError:
                pass  # Column already exists
        self._conn.execute(
            "UPDATE managed_agents SET team_scoped = 1 WHERE team_id IS NOT NULL"
        )
        try:
            self._conn.execute(
                "ALTER TABLE team_mcp_connections ADD COLUMN settings_json "
                "TEXT NOT NULL DEFAULT '{}'"
            )
        except sqlite3.OperationalError:
            pass  # Existing database already has this column.
        for column in ("communication_json",):
            try:
                self._conn.execute(
                    f"ALTER TABLE agent_teams ADD COLUMN {column} "
                    "TEXT NOT NULL DEFAULT '[]'"
                )
            except sqlite3.OperationalError:
                pass  # Existing database already has this policy column.
        self._conn.commit()
        # Only the authoritative long-running process (the API server, which
        # owns the scheduler) may sweep running→idle on boot. Short-lived CLI
        # commands (`jarvis agents list/info/...`) and the SystemBuilder path
        # used by `run`/`ask` MUST NOT: they share this DB with a server that
        # may be mid-tick, and an unconditional sweep here flips an actively
        # running agent back to "idle" — which is exactly why `list` reported
        # "idle" while a tick was running elsewhere. Zombies left by a crashed
        # worker are recovered lazily by start_tick()'s stale-lock overtake.
        if clear_stale_running:
            self._clear_stale_running_state()

    @property
    def campaigns(self):
        """Team requests and task handoffs (created on first use)."""
        store = getattr(self, "_campaigns", None)
        if store is None:
            from openjarvis.agents.campaigns import CampaignStore

            store = self._campaigns = CampaignStore(self)
        return store

    @_db_locked
    def _clear_stale_running_state(self) -> None:
        """Reset any agent stuck in ``status='running'`` on startup.

        Tick worker threads are ``daemon=True`` — when the server process
        exits (SIGTERM, crash, restart), they die without running the
        ``finally`` clause that calls :meth:`end_tick`, leaving the DB row
        in ``running`` forever. The :meth:`start_tick` guard then rejects
        every subsequent run with "Agent is already running".

        The server boot holds zero tick locks by definition, so any persisted
        ``running`` is a zombie. Sweep it back to ``idle`` and clear the
        activity string so the UI doesn't show a stale "Preparing tick..."
        indicator. Call this only from a process that owns tick execution.
        """
        cur = self._conn.execute(
            "UPDATE managed_agents SET status = 'idle', current_activity = '',"
            " updated_at = ? WHERE status = 'running'",
            (time.time(),),
        )
        self._conn.commit()
        if cur.rowcount:
            logger.info(
                "AgentManager: cleared stale 'running' status on %d agent(s)",
                cur.rowcount,
            )

    @_db_locked
    def close(self) -> None:
        self._conn.close()

    # ── Agent CRUD ────────────────────────────────────────────────

    @_db_locked
    def create_agent(
        self,
        name: str,
        agent_type: str = "monitor_operative",
        config: Optional[Dict[str, Any]] = None,
        team_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._validate_team_id(team_id)
        agent_id = uuid.uuid4().hex[:12]
        now = time.time()
        config = dict(config or {})
        config_json = json.dumps(config)
        self._conn.execute(
            "INSERT INTO managed_agents"
            " (id, name, agent_type, config_json,"
            " status, summary_memory, created_at, updated_at, team_id, team_scoped)"
            " VALUES (?, ?, ?, ?, 'idle', '', ?, ?, ?, ?)",
            (agent_id, name, agent_type, config_json, now, now, team_id, bool(team_id)),
        )
        self._conn.commit()
        return self.get_agent(agent_id)  # type: ignore[return-value]

    @_db_locked
    def list_agents(
        self, include_archived: bool = False, team_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM managed_agents WHERE 1=1"
        params: list[Any] = []
        if not include_archived:
            query += " AND status != 'archived'"
        if team_id is not None:
            if team_id == "":
                query += " AND team_id IS NULL"
            else:
                query += " AND team_id = ?"
                params.append(team_id)
        query += " ORDER BY updated_at DESC"
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_agent(r) for r in rows]

    @_db_locked
    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM managed_agents WHERE id = ?", (agent_id,)
        ).fetchone()
        return self._row_to_agent(row) if row else None

    @_db_locked
    def update_agent(self, agent_id: str, **kwargs: Any) -> Dict[str, Any]:
        sets: List[str] = []
        vals: List[Any] = []
        if "team_id" in kwargs:
            self._validate_team_id(kwargs["team_id"])
            sets.append("team_id = ?")
            vals.append(kwargs["team_id"])
            if kwargs["team_id"] is not None:
                sets.append("team_scoped = 1")
        for key in ("name", "agent_type", "status", "current_activity"):
            if key in kwargs:
                sets.append(f"{key} = ?")
                vals.append(kwargs[key])
        if "config" in kwargs:
            sets.append("config_json = ?")
            vals.append(json.dumps(kwargs["config"]))
        total_runs_increment = kwargs.get("total_runs_increment", 0)
        if total_runs_increment:
            sets.append("total_runs = total_runs + ?")
            vals.append(total_runs_increment)
            sets.append("last_run_at = ?")
            vals.append(time.time())
        total_cost_increment = kwargs.get("total_cost_increment", 0)
        if total_cost_increment:
            sets.append("total_cost = total_cost + ?")
            vals.append(total_cost_increment)
        total_tokens_increment = kwargs.get("total_tokens_increment", 0)
        if total_tokens_increment:
            sets.append("total_tokens = total_tokens + ?")
            vals.append(total_tokens_increment)
        input_tokens_increment = kwargs.get("input_tokens_increment", 0)
        if input_tokens_increment:
            sets.append("input_tokens = input_tokens + ?")
            vals.append(input_tokens_increment)
        output_tokens_increment = kwargs.get("output_tokens_increment", 0)
        if output_tokens_increment:
            sets.append("output_tokens = output_tokens + ?")
            vals.append(output_tokens_increment)
        if "last_activity_at" in kwargs:
            sets.append("last_activity_at = ?")
            vals.append(kwargs["last_activity_at"])
        if "stall_retries" in kwargs:
            sets.append("stall_retries = ?")
            vals.append(kwargs["stall_retries"])
        sets.append("updated_at = ?")
        vals.append(time.time())
        vals.append(agent_id)
        self._conn.execute(
            f"UPDATE managed_agents SET {', '.join(sets)} WHERE id = ?", vals
        )
        self._conn.commit()
        return self.get_agent(agent_id)  # type: ignore[return-value]

    @_db_locked
    def delete_agent(self, agent_id: str) -> None:
        self._set_status(agent_id, "archived")

    @_db_locked
    def pause_agent(self, agent_id: str) -> None:
        self._set_status(agent_id, "paused")

    @_db_locked
    def resume_agent(self, agent_id: str) -> None:
        self._set_status(agent_id, "idle")

    @_db_locked
    def _set_status(self, agent_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE managed_agents SET status = ?, updated_at = ? WHERE id = ?",
            (status, time.time(), agent_id),
        )
        self._conn.commit()

    # ── Tick concurrency guard ────────────────────────────────────

    @_db_locked
    def start_tick(self, agent_id: str) -> None:
        """Mark agent as running. Raises ValueError if already running.

        A row that has been ``running`` longer than ``_STALE_TICK_SECONDS``
        without any update is treated as a zombie left by a dead worker and
        overtaken rather than refused — otherwise a crash with no server
        around to sweep it would wedge the agent forever.

        The state transition is a single conditional SQLite update.  The
        read-before-write approach is racy when two workers start together:
        both can observe ``idle`` and then mark the row ``running``.  The
        conditional update lets SQLite choose exactly one winner, including
        when workers use separate connections or processes.
        """
        while True:
            now = time.time()
            stale_before = now - self._STALE_TICK_SECONDS
            agent = self.get_agent(agent_id)
            if agent is None:
                return

            was_stale = (
                agent["status"] == "running"
                and (agent.get("updated_at") or 0) <= stale_before
            )
            cursor = self._conn.execute(
                "UPDATE managed_agents SET status = 'running', "
                "updated_at = ? WHERE id = ? AND "
                "(status != 'running' OR updated_at <= ?)",
                (now, agent_id, stale_before),
            )
            self._conn.commit()
            if cursor.rowcount:
                if was_stale:
                    age = time.time() - (agent.get("updated_at") or 0)
                    logger.warning(
                        "Agent %s: overtaking stale tick lock "
                        "(running, idle for %.0fs)",
                        agent_id,
                        age,
                    )
                return

            # Another connection acquired the lock after our read.  If that
            # lock is still fresh, this caller loses; if it ended between the
            # failed update and this read, retry so the caller never proceeds
            # without owning the tick lock.
            current = self.get_agent(agent_id)
            if current is None:
                return
            if current["status"] == "running":
                age = time.time() - (current.get("updated_at") or 0)
                if age < self._STALE_TICK_SECONDS:
                    raise ValueError(f"Agent {agent_id} is already executing a tick")

    @_db_locked
    def end_tick(self, agent_id: str) -> None:
        self._conn.execute(
            "UPDATE managed_agents SET status = 'idle', "
            "current_activity = '', updated_at = ? "
            "WHERE id = ? AND status = 'running'",
            (time.time(), agent_id),
        )
        self._conn.commit()

    # ── Checkpoints ───────────────────────────────────────────────

    _CHECKPOINT_RETENTION = 5

    @_db_locked
    def save_checkpoint(
        self,
        agent_id: str,
        tick_id: str,
        conversation_state: dict,
        tool_state: dict,
    ) -> dict:
        cp_id = uuid4().hex[:16]
        now = time.time()
        self._conn.execute(
            "INSERT INTO agent_checkpoints"
            " (id, agent_id, tick_id, conversation_state, tool_state, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                cp_id,
                agent_id,
                tick_id,
                json.dumps(conversation_state),
                json.dumps(tool_state),
                now,
            ),
        )
        # Prune old checkpoints beyond retention limit
        self._conn.execute(
            "DELETE FROM agent_checkpoints WHERE agent_id = ? AND id NOT IN "
            "(SELECT id FROM agent_checkpoints WHERE agent_id = ?"
            " ORDER BY created_at DESC LIMIT ?)",
            (agent_id, agent_id, self._CHECKPOINT_RETENTION),
        )
        self._conn.commit()
        return {
            "id": cp_id,
            "agent_id": agent_id,
            "tick_id": tick_id,
            "created_at": now,
        }

    @_db_locked
    def list_checkpoints(self, agent_id: str) -> list:
        rows = self._conn.execute(
            "SELECT * FROM agent_checkpoints"
            " WHERE agent_id = ? ORDER BY created_at DESC",
            (agent_id,),
        ).fetchall()
        return [self._row_to_checkpoint(r) for r in rows]

    @_db_locked
    def get_latest_checkpoint(self, agent_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM agent_checkpoints"
            " WHERE agent_id = ? ORDER BY created_at DESC LIMIT 1",
            (agent_id,),
        ).fetchone()
        return self._row_to_checkpoint(row) if row else None

    @_db_locked
    def recover_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        checkpoint = self.get_latest_checkpoint(agent_id)
        # Always reset to idle — clearing the error state is the primary purpose
        self.update_agent(agent_id, status="idle")
        return checkpoint

    @staticmethod
    def _row_to_checkpoint(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "tick_id": row["tick_id"],
            "conversation_state": json.loads(row["conversation_state"]),
            "tool_state": json.loads(row["tool_state"]),
            "created_at": row["created_at"],
        }

    # ── Summary memory ────────────────────────────────────────────

    @_db_locked
    def update_summary_memory(self, agent_id: str, summary: str) -> None:
        truncated = summary[:_SUMMARY_MAX]
        self._conn.execute(
            "UPDATE managed_agents SET summary_memory = ?, updated_at = ? WHERE id = ?",
            (truncated, time.time(), agent_id),
        )
        self._conn.commit()

    # ── Task CRUD ─────────────────────────────────────────────────

    @_db_locked
    def create_task(
        self, agent_id: str, description: str, status: str = "pending"
    ) -> Dict[str, Any]:
        task_id = uuid.uuid4().hex[:12]
        now = time.time()
        self._conn.execute(
            "INSERT INTO agent_tasks (id, agent_id, description, status, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (task_id, agent_id, description, status, now),
        )
        self._conn.commit()
        return self._get_task(task_id)  # type: ignore[return-value]

    @_db_locked
    def list_tasks(
        self, agent_id: str, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM agent_tasks WHERE agent_id = ?"
        params: List[Any] = [agent_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC"
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_task(r) for r in rows]

    @_db_locked
    def update_task(self, task_id: str, **kwargs: Any) -> Dict[str, Any]:
        sets: List[str] = []
        vals: List[Any] = []
        for key in ("description", "status"):
            if key in kwargs:
                sets.append(f"{key} = ?")
                vals.append(kwargs[key])
        if "progress" in kwargs:
            sets.append("progress_json = ?")
            vals.append(json.dumps(kwargs["progress"]))
        if "findings" in kwargs:
            sets.append("findings_json = ?")
            vals.append(json.dumps(kwargs["findings"]))
        if not sets:
            return self._get_task(task_id)  # type: ignore[return-value]
        vals.append(task_id)
        self._conn.execute(
            f"UPDATE agent_tasks SET {', '.join(sets)} WHERE id = ?", vals
        )
        self._conn.commit()
        return self._get_task(task_id)  # type: ignore[return-value]

    @_db_locked
    def delete_task(self, task_id: str) -> None:
        self._conn.execute("DELETE FROM agent_tasks WHERE id = ?", (task_id,))
        self._conn.commit()

    @_db_locked
    def _get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM agent_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return self._row_to_task(row) if row else None

    # ── Channel bindings ──────────────────────────────────────────

    @_db_locked
    def bind_channel(
        self,
        agent_id: str,
        channel_type: str,
        config: Optional[Dict[str, Any]] = None,
        routing_mode: str = "dedicated",
    ) -> Dict[str, Any]:
        binding_id = uuid.uuid4().hex[:12]
        session_id = uuid.uuid4().hex[:16]
        config_json = json.dumps(config or {})
        self._conn.execute(
            "INSERT INTO channel_bindings "
            "(id, agent_id, channel_type, config_json, session_id, routing_mode) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (binding_id, agent_id, channel_type, config_json, session_id, routing_mode),
        )
        self._conn.commit()
        return self._get_binding(binding_id)  # type: ignore[return-value]

    @_db_locked
    def list_channel_bindings(self, agent_id: str) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM channel_bindings WHERE agent_id = ?", (agent_id,)
        ).fetchall()
        return [self._row_to_binding(r) for r in rows]

    @_db_locked
    def unbind_channel(self, binding_id: str) -> None:
        self._conn.execute("DELETE FROM channel_bindings WHERE id = ?", (binding_id,))
        self._conn.commit()

    @_db_locked
    def _get_binding(self, binding_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM channel_bindings WHERE id = ?", (binding_id,)
        ).fetchone()
        return self._row_to_binding(row) if row else None

    @_db_locked
    def find_binding_for_channel(
        self, channel_type: str, channel_id: str
    ) -> Optional[Dict[str, Any]]:
        """Find a dedicated binding for a specific channel."""
        rows = self._conn.execute(
            "SELECT * FROM channel_bindings WHERE channel_type = ?",
            (channel_type,),
        ).fetchall()
        for row in rows:
            binding = self._row_to_binding(row)
            config = binding.get("config", {})
            if config.get("channel") == channel_id:
                return binding
        return None

    # ── Templates ─────────────────────────────────────────────────

    @staticmethod
    def list_templates() -> List[Dict[str, Any]]:
        """Discover built-in and user templates."""
        import importlib.resources

        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib  # type: ignore[no-redef]

        templates: List[Dict[str, Any]] = []

        # Built-in templates
        try:
            tpl_dir = importlib.resources.files("openjarvis.agents") / "templates"
            for item in tpl_dir.iterdir():
                if str(item).endswith(".toml"):
                    data = tomllib.loads(item.read_text(encoding="utf-8"))
                    tpl = data.get("template", {})
                    tpl["source"] = "built-in"
                    templates.append(tpl)
        except Exception:
            pass

        # User templates
        user_dir = get_config_dir() / "templates"
        if user_dir.is_dir():
            for f in user_dir.glob("*.toml"):
                try:
                    data = tomllib.loads(f.read_text(encoding="utf-8"))
                    tpl = data.get("template", {})
                    tpl["source"] = "user"
                    templates.append(tpl)
                except Exception:
                    pass

        return templates

    def create_from_template(
        self,
        template_id: str,
        name: str,
        overrides: Optional[Dict[str, Any]] = None,
        *,
        team_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create an agent from a template with optional overrides."""
        templates = self.list_templates()
        tpl = next((t for t in templates if t.get("id") == template_id), None)
        if not tpl:
            raise ValueError(f"Template not found: {template_id}")
        skip = {"id", "name", "description", "source"}
        config = {k: v for k, v in tpl.items() if k not in skip}
        if overrides:
            config.update(overrides)
        agent_type = config.pop("agent_type", "monitor_operative")

        # Expand system_prompt_template with instruction
        prompt_tpl = config.pop("system_prompt_template", "")
        if prompt_tpl:
            instruction = config.get("instruction", "")
            config["system_prompt"] = prompt_tpl.format(
                instruction=instruction or "(No specific instruction provided)",
            )

        return self.create_agent(
            name=name, agent_type=agent_type, config=config, team_id=team_id
        )

    def _validate_team_id(self, team_id: Optional[str]) -> None:
        if (
            team_id is not None
            and not self._conn.execute(
                "SELECT 1 FROM agent_teams WHERE id = ?", (team_id,)
            ).fetchone()
        ):
            raise ValueError("Team not found")

    @staticmethod
    def _team_name(name: str) -> str:
        name = name.strip()
        if not name or len(name) > 120:
            raise ValueError("Team name must contain 1 to 120 characters")
        return name

    @_db_locked
    def list_teams(self) -> List[Dict[str, Any]]:
        """List organizational teams, including teams with no agents."""
        return [
            self._row_to_team(row)
            for row in self._conn.execute(
                "SELECT * FROM agent_teams ORDER BY name COLLATE NOCASE, id"
            ).fetchall()
        ]

    @_db_locked
    def create_team(self, name: str) -> Dict[str, Any]:
        """Create a named team; names are unique without ASCII case differences."""
        team = {
            "id": uuid.uuid4().hex[:12],
            "name": self._team_name(name),
            "created_at": time.time(),
        }
        try:
            with self._conn:
                self._conn.execute(
                    "INSERT INTO agent_teams (id, name, created_at) VALUES (?, ?, ?)",
                    (team["id"], team["name"], team["created_at"]),
                )
        except sqlite3.IntegrityError:
            raise ValueError("A team with this name already exists") from None
        return self.get_team(team["id"])

    @_db_locked
    def rename_team(self, team_id: str, name: str) -> Dict[str, Any]:
        """Rename a team without changing agent membership."""
        name = self._team_name(name)
        try:
            with self._conn:
                cursor = self._conn.execute(
                    "UPDATE agent_teams SET name = ? WHERE id = ?", (name, team_id)
                )
                if not cursor.rowcount:
                    raise KeyError("Team not found")
        except sqlite3.IntegrityError:
            raise ValueError("A team with this name already exists") from None
        return self.get_team(team_id)

    @_db_locked
    def delete_team(self, team_id: str) -> None:
        """Delete a team, preserving its agents and all their related records."""
        connections = self.list_team_connections(team_id)
        with self._conn:
            self._conn.execute(
                "UPDATE managed_agents SET team_id = NULL, updated_at = ? "
                "WHERE team_id = ?",
                (time.time(), team_id),
            )
            for peer in self.list_teams():
                if team_id in peer["communicate_with"]:
                    remaining = [x for x in peer["communicate_with"] if x != team_id]
                    self._conn.execute(
                        "UPDATE agent_teams SET communication_json = ? WHERE id = ?",
                        (json.dumps(remaining), peer["id"]),
                    )
            cursor = self._conn.execute(
                "DELETE FROM agent_teams WHERE id = ?", (team_id,)
            )
            if not cursor.rowcount:
                raise KeyError("Team not found")
        for connection in connections:
            self._connection_secret_path(connection["id"]).unlink(missing_ok=True)

    @staticmethod
    def _row_to_team(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "created_at": row["created_at"],
            "communicate_with": json.loads(row["communication_json"]),
            "lead_agent_id": (
                row["lead_agent_id"] if "lead_agent_id" in row.keys() else None
            ),
        }

    @_db_locked
    def get_team(self, team_id: str) -> Optional[Dict[str, Any]]:
        """Read team settings without exposing server credentials."""
        row = self._conn.execute(
            "SELECT * FROM agent_teams WHERE id = ?", (team_id,)
        ).fetchone()
        return self._row_to_team(row) if row else None

    @_db_locked
    def update_team_policy(
        self, team_id: str, *, communicate_with: list[str]
    ) -> Dict[str, Any]:
        """Replace bilateral communication preferences; accounts remain team-owned."""
        if self.get_team(team_id) is None:
            raise KeyError("Team not found")
        for values in (communicate_with,):
            if not isinstance(values, list) or any(
                not isinstance(value, str) or not value.strip() for value in values
            ):
                raise ValueError("Policy entries must be non-empty strings")
        for peer in communicate_with:
            if peer == team_id or self.get_team(peer) is None:
                raise ValueError("Choose other existing teams for communication")
        with self._conn:
            self._conn.execute(
                "UPDATE agent_teams SET communication_json = ? WHERE id = ?",
                (json.dumps(sorted(set(communicate_with))), team_id),
            )
        return self.get_team(team_id)

    @_db_locked
    def agents_can_communicate(self, source_id: str, target_id: str) -> bool:
        """Allow same-team messages or explicit consent from both current teams."""
        source, target = self.get_agent(source_id), self.get_agent(target_id)
        if not source or not target:
            return False
        if source["status"] == "archived" or target["status"] == "archived":
            return False
        source_team, target_team = source["team_id"], target["team_id"]
        if not source_team or not target_team:
            return False
        if source_team == target_team:
            return True
        a, b = self.get_team(source_team), self.get_team(target_team)
        return bool(
            a
            and b
            and target_team in a["communicate_with"]
            and source_team in b["communicate_with"]
        )

    @_db_locked
    def list_agent_peers(self, source_id: str) -> List[Dict[str, Any]]:
        """Expose only reachable agents, without their config, history or memory."""
        return [
            {key: agent[key] for key in ("id", "name", "team_id")}
            for agent in self.list_agents()
            if agent["id"] != source_id
            and self.agents_can_communicate(source_id, agent["id"])
        ]

    @_db_locked
    def send_agent_message(self, source_id: str, target_id: str, content: str) -> dict:
        """Queue an attributed message after an atomic live policy check.

        Delivery is queued, never an automatic model run. Source identity is supplied
        by the runtime-bound tool, not a model-controlled tool parameter.
        """
        if not self.agents_can_communicate(source_id, target_id):
            raise PermissionError("Team communication is not permitted")
        if not isinstance(content, str) or not content.strip() or len(content) > 20000:
            raise ValueError("Message must contain 1 to 20000 characters")
        msg_id = uuid4().hex[:16]
        now = time.time()
        source = self.get_agent(source_id)
        envelope = json.dumps(
            {
                "source_agent_id": source_id,
                "source_team_id": source["team_id"],
                "target_team_id": self.get_agent(target_id)["team_id"],
                "message": content,
            },
            ensure_ascii=False,
        )
        self._conn.execute(
            "INSERT INTO agent_messages "
            "(id,agent_id,direction,content,mode,status,created_at) "
            "VALUES (?,?,'agent_to_agent',?,'queued','pending',?)",
            (msg_id, target_id, envelope, now),
        )
        self._conn.commit()
        return {"message_id": msg_id, "status": "queued", "target_agent_id": target_id}

    def _connection_secret_path(self, connection_id: str):
        from pathlib import Path

        if not connection_id or any(c not in "0123456789abcdef" for c in connection_id):
            raise ValueError("Invalid connection ID")
        return Path(self._db_path).parent / "team-connection-secrets" / connection_id

    @_db_locked
    def list_team_connections(self, team_id: str) -> List[Dict[str, Any]]:
        """List this team's independent connections, never credential values."""
        rows = self._conn.execute(
            "SELECT * FROM team_mcp_connections WHERE team_id = ? ORDER BY name",
            (team_id,),
        ).fetchall()
        result = []
        for row in rows:
            connection = dict(row)
            # Older local databases may hold non-MCP rows from an earlier draft.
            if connection.pop("kind", "mcp") != "mcp":
                continue
            connection["settings"] = json.loads(connection.pop("settings_json") or "{}")
            configured = (
                row["auth_type"] == "none"
                or self._connection_secret_path(row["id"]).is_file()
            )
            # Saved settings are "configured"; only a successful live check by
            # the provider client (verify) records "verified".
            if not configured:
                status = "needs_authentication"
            elif connection["settings"].get("last_error"):
                status = "error"
            elif connection["settings"].get("verified_at"):
                status = "verified"
            else:
                status = "configured"
            connection["status"] = status
            result.append(connection)
        return result

    @_db_locked
    def get_team_connection(
        self, team_id: str, connection_id: str
    ) -> Optional[Dict[str, Any]]:
        return next(
            (
                c
                for c in self.list_team_connections(team_id)
                if c["id"] == connection_id
            ),
            None,
        )

    @_db_locked
    def update_team_connection_settings(
        self, team_id: str, connection_id: str, **changes: Any
    ) -> Dict[str, Any]:
        """Merge non-secret settings (verification state, allowed agents...)."""
        connection = self.get_team_connection(team_id, connection_id)
        if connection is None:
            raise KeyError("Connection not found")
        settings = dict(connection["settings"])
        for key, value in changes.items():
            if value is None:
                settings.pop(key, None)
            else:
                settings[key] = value
        self._conn.execute(
            "UPDATE team_mcp_connections SET settings_json = ? "
            "WHERE id = ? AND team_id = ?",
            (json.dumps(settings, ensure_ascii=False), connection_id, team_id),
        )
        self._conn.commit()
        return self.get_team_connection(team_id, connection_id)  # type: ignore[return-value]

    @_db_locked
    def create_team_connection(
        self,
        team_id: str,
        *,
        name: str,
        provider: str,
        url: str,
        auth_type: str = "bearer",
        token: str = "",
        settings: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Save a team-owned HTTP connection and private per-connection credential.

        The token is stored in a mode-0600 file, never in process environment,
        returned metadata, agent configuration or the global MCP credential.
        """
        from urllib.parse import urlsplit

        from openjarvis.security.file_utils import secure_write_text

        if not self.get_team(team_id):
            raise KeyError("Team not found")
        name, provider = self._team_name(name), self._team_name(provider)
        settings = self._mcp_settings(team_id, settings or {}, auth_type)
        parsed = urlsplit(url)
        if not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Use an MCP endpoint without credentials in its URL")
        if parsed.query or parsed.fragment:
            raise ValueError("Put authentication in the credential field, not the URL")
        if parsed.scheme != "https" and not (
            parsed.scheme == "http"
            and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError("Use HTTPS, or HTTP for an explicitly local MCP server")
        if auth_type not in {"bearer", "none", "header"}:
            raise ValueError("Choose bearer, header or none authentication")
        if auth_type == "none" and token:
            raise ValueError("Choose bearer authentication when supplying a credential")
        connection_id = uuid.uuid4().hex
        secret_path = self._connection_secret_path(connection_id)
        try:
            if token.strip():
                secret_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                secure_write_text(secret_path, token.strip(), mode=0o600)
            with self._conn:
                self._conn.execute(
                    "INSERT INTO team_mcp_connections "
                    "(id,team_id,name,provider,url,auth_type,created_at,"
                    "settings_json) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        connection_id,
                        team_id,
                        name,
                        provider,
                        url,
                        auth_type,
                        time.time(),
                        json.dumps(settings, ensure_ascii=False),
                    ),
                )
        except Exception:
            secret_path.unlink(missing_ok=True)
            raise
        return next(
            c for c in self.list_team_connections(team_id) if c["id"] == connection_id
        )

    _FORBIDDEN_HEADERS = {
        "host",
        "content-type",
        "content-length",
        "accept",
        "mcp-session-id",
        "connection",
        "transfer-encoding",
    }

    def _mcp_settings(
        self, team_id: str, settings: Dict[str, Any], auth_type: str
    ) -> Dict[str, Any]:
        """Validate MCP settings: auth header name and allowed agents."""
        clean: Dict[str, Any] = {}
        if auth_type == "header":
            header = str(settings.get("header_name") or "").strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", header) or (
                header.lower() in self._FORBIDDEN_HEADERS
            ):
                raise ValueError("Choose a valid authentication header name")
            clean["header_name"] = header
        clean["agent_ids"] = self._member_ids(team_id, settings.get("agent_ids") or [])
        return clean

    def _member_ids(self, team_id: str, agent_ids: Any) -> List[str]:
        if not isinstance(agent_ids, list):
            raise ValueError("agent_ids must be a list")
        members = {a["id"] for a in self.list_agents() if a["team_id"] == team_id}
        unknown = [a for a in agent_ids if a not in members]
        if unknown:
            raise ValueError("Allowed agents must be active members of this team")
        return sorted(set(agent_ids))

    @_db_locked
    def set_team_connection_access(
        self,
        team_id: str,
        connection_id: str,
        *,
        agent_ids: List[str],
    ) -> Dict[str, Any]:
        """Limit an MCP connection to chosen members (empty: the whole team)."""
        connection = self.get_team_connection(team_id, connection_id)
        if connection is None:
            raise KeyError("Connection not found")
        return self.update_team_connection_settings(
            team_id,
            connection_id,
            agent_ids=self._member_ids(team_id, agent_ids),
        )

    @staticmethod
    def connection_open_to(connection: Dict[str, Any], agent_id: str) -> bool:
        allowed = (connection.get("settings") or {}).get("agent_ids") or []
        return not allowed or agent_id in allowed

    @_db_locked
    def delete_team_connection(self, team_id: str, connection_id: str) -> None:
        """Revoke a connection and remove only its own credential."""
        cursor = self._conn.execute(
            "DELETE FROM team_mcp_connections WHERE id = ? AND team_id = ?",
            (connection_id, team_id),
        )
        self._conn.commit()
        if not cursor.rowcount:
            raise KeyError("Connection not found")
        self._connection_secret_path(connection_id).unlink(missing_ok=True)

    @_db_locked
    def team_connection_allowed(self, agent_id: str, connection_id: str) -> bool:
        """Check current membership and connection ownership immediately before use."""
        agent = self.get_agent(agent_id)
        if not agent or agent["status"] == "archived":
            return False
        if agent["config"].get("mcp_tools", True) is False:
            return False
        connection = self.get_team_connection(agent["team_id"], connection_id)
        return bool(connection and self.connection_open_to(connection, agent_id))

    @_db_locked
    def _team_connection_token(self, connection_id: str) -> str:
        """Read only the selected connection's credential for transport construction."""
        return self._connection_secret_path(connection_id).read_text().strip()

    # ── Message queue ─────────────────────────────────────────────

    @_db_locked
    def send_message(self, agent_id: str, content: str, mode: str = "queued") -> dict:
        msg_id = uuid4().hex[:16]
        now = time.time()
        _sql = (
            "INSERT INTO agent_messages"
            " (id, agent_id, direction, content, mode, status, created_at)"
            " VALUES (?, ?, 'user_to_agent', ?, ?, 'pending', ?)"
        )
        self._conn.execute(_sql, (msg_id, agent_id, content, mode, now))
        self._conn.commit()
        return {
            "id": msg_id,
            "agent_id": agent_id,
            "direction": "user_to_agent",
            "content": content,
            "mode": mode,
            "status": "pending",
            "created_at": now,
        }

    @_db_locked
    def store_agent_response(
        self,
        agent_id: str,
        content: str,
        tool_calls: Optional[list] = None,
    ) -> dict:
        """Store an agent-to-user response message.

        ``tool_calls`` is an optional list of ``{tool, arguments, result,
        success, latency}`` dicts captured during the turn. They are stored
        as JSON alongside the message so the UI can replay them after a
        page reload.
        """
        msg_id = uuid4().hex[:16]
        now = time.time()
        tool_calls_json = json.dumps(tool_calls) if tool_calls else None
        self._conn.execute(
            "INSERT INTO agent_messages"
            " (id, agent_id, direction, content, mode, status, created_at,"
            " tool_calls)"
            " VALUES (?, ?, 'agent_to_user', ?, 'immediate', 'delivered', ?, ?)",
            (msg_id, agent_id, content, now, tool_calls_json),
        )
        self._conn.commit()
        return {
            "id": msg_id,
            "agent_id": agent_id,
            "direction": "agent_to_user",
            "content": content,
            "mode": "immediate",
            "status": "delivered",
            "created_at": now,
            "tool_calls": tool_calls or None,
        }

    @_db_locked
    def list_messages(self, agent_id: str, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM agent_messages"
            " WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?",
            (agent_id, limit),
        ).fetchall()
        return [self._row_to_message(r) for r in rows]

    @_db_locked
    def get_pending_messages(self, agent_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM agent_messages"
            " WHERE agent_id = ? AND direction IN ('user_to_agent', 'agent_to_agent')"
            " AND status = 'pending' ORDER BY created_at ASC",
            (agent_id,),
        ).fetchall()
        result = []
        for row in rows:
            message = self._row_to_message(row)
            if message["direction"] == "agent_to_agent":
                try:
                    envelope = json.loads(message["content"])
                    source_id = envelope["source_agent_id"]
                except (ValueError, KeyError, TypeError):
                    continue
                source, target = self.get_agent(source_id), self.get_agent(agent_id)
                unchanged = (
                    source
                    and target
                    and source["team_id"] == envelope.get("source_team_id")
                    and target["team_id"] == envelope.get("target_team_id")
                )
                if not unchanged or not self.agents_can_communicate(
                    source_id, agent_id
                ):
                    self._conn.execute(
                        "UPDATE agent_messages SET status = 'blocked' WHERE id = ?",
                        (message["id"],),
                    )
                    self._conn.commit()
                    continue
            result.append(message)
        return result

    @_db_locked
    def mark_message_delivered(self, message_id: str) -> None:
        self._conn.execute(
            "UPDATE agent_messages SET status = 'delivered' WHERE id = ?",
            (message_id,),
        )
        self._conn.commit()

    @_db_locked
    def add_agent_response(self, agent_id: str, content: str) -> dict:
        msg_id = uuid4().hex[:16]
        now = time.time()
        _sql = (
            "INSERT INTO agent_messages"
            " (id, agent_id, direction, content, mode, status, created_at)"
            " VALUES (?, ?, 'agent_to_user', ?, 'immediate', 'responded', ?)"
        )
        self._conn.execute(_sql, (msg_id, agent_id, content, now))
        self._conn.commit()
        return {
            "id": msg_id,
            "agent_id": agent_id,
            "direction": "agent_to_user",
            "content": content,
            "mode": "immediate",
            "status": "responded",
            "created_at": now,
        }

    @staticmethod
    def _row_to_message(row: sqlite3.Row) -> dict:
        tool_calls = None
        try:
            raw = row["tool_calls"]
        except (IndexError, KeyError):
            raw = None
        if raw:
            try:
                tool_calls = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                tool_calls = None
        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "direction": row["direction"],
            "content": row["content"],
            "mode": row["mode"],
            "status": row["status"],
            "created_at": row["created_at"],
            "tool_calls": tool_calls,
        }

    # ── Learning log ──────────────────────────────────────────

    @_db_locked
    def add_learning_log(
        self,
        agent_id: str,
        event_type: str,
        description: str = "",
        data: dict | None = None,
    ) -> dict:
        log_id = uuid4().hex[:16]
        now = time.time()
        self._conn.execute(
            "INSERT INTO agent_learning_log"
            " (id, agent_id, event_type, description, data, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (log_id, agent_id, event_type, description, json.dumps(data or {}), now),
        )
        self._conn.commit()
        return {
            "id": log_id,
            "agent_id": agent_id,
            "event_type": event_type,
            "description": description,
            "data": data or {},
            "created_at": now,
        }

    @_db_locked
    def list_learning_log(self, agent_id: str, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM agent_learning_log"
            " WHERE agent_id = ? ORDER BY created_at DESC LIMIT ?",
            (agent_id, limit),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "agent_id": r["agent_id"],
                "event_type": r["event_type"],
                "description": r["description"],
                "data": json.loads(r["data"] or "{}"),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    # ── Row converters ────────────────────────────────────────────

    @staticmethod
    def _row_to_agent(row: sqlite3.Row) -> Dict[str, Any]:
        config_raw = row["config_json"]
        return {
            "id": row["id"],
            "name": row["name"],
            "agent_type": row["agent_type"],
            "team_id": row["team_id"],
            "team_scoped": bool(row["team_scoped"]),
            "config": json.loads(config_raw) if config_raw else {},
            "status": row["status"],
            "summary_memory": row["summary_memory"] or "",
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "total_tokens": row["total_tokens"] or 0,
            "total_cost": row["total_cost"] or 0.0,
            "total_runs": row["total_runs"] or 0,
            "last_run_at": row["last_run_at"],
            "last_activity_at": row["last_activity_at"],
            "stall_retries": row["stall_retries"] or 0,
            "current_activity": row["current_activity"] or "",
            "input_tokens": row["input_tokens"] or 0,
            "output_tokens": row["output_tokens"] or 0,
        }

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> Dict[str, Any]:
        progress_raw = row["progress_json"]
        findings_raw = row["findings_json"]
        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "description": row["description"],
            "status": row["status"],
            "progress": json.loads(progress_raw) if progress_raw else {},
            "findings": json.loads(findings_raw) if findings_raw else [],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _row_to_binding(row: sqlite3.Row) -> Dict[str, Any]:
        config_raw = row["config_json"]
        return {
            "id": row["id"],
            "agent_id": row["agent_id"],
            "channel_type": row["channel_type"],
            "config": json.loads(config_raw) if config_raw else {},
            "session_id": row["session_id"] or "",
            "routing_mode": row["routing_mode"] or "auto",
        }
