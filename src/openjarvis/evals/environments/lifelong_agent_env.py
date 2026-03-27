"""Multi-turn task environments for LifelongAgentBench.

Implements faithful reproductions of the original's interaction protocols:
  - DB: MySQL Docker container (SQLite fallback with degraded-mode warning)
  - KG: Variable-store API simulation (SPARQL endpoint if configured)
  - OS: Docker container with correct image

Reference: https://github.com/caixd-220529/LifelongAgentBench
"""

from __future__ import annotations

import logging
import re
import shutil
import sqlite3
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.evals.core.types import EvalRecord
from openjarvis.evals.environments.base import TaskEnvironment
from openjarvis.evals.scorers.lifelong_agent_scorer import (
    _TYPE_MAP,
    _normalize_entity,
    compare_tuple_lists,
    extract_sql,
    values_match,
)

logger = logging.getLogger(__name__)

# Per-subset max turns matching the original's default configs
MAX_TURNS_DB = 3
MAX_TURNS_KG = 15
MAX_TURNS_OS = 5


def _infer_oracle_result(
    func_name: str,
    current_action: str,
    next_action: str,
) -> str:
    """Infer a plausible oracle result from the gold action sequence.

    The HF dataset stores action_list as plain strings like
    ``"get_relations(m.03fwl)"`` — these are the *calls* the gold
    solution makes, not their results.  We reconstruct plausible
    results by inspecting what the *next* gold call expects:

    - If current is ``get_relations(X)`` and next is
      ``get_neighbors(X, rel)``, then ``rel`` was among the results.
    - If current is ``get_neighbors(X, rel)`` and next uses the
      result variable, we return the entity from the next call.
    """
    import re as _re

    # get_relations → the next call's relation argument is a result
    if func_name == "get_relations":
        m = _re.search(r"\w+\([^,]+,\s*([^)]+)\)", next_action)
        if m:
            relation = m.group(1).strip()
            return f"['{relation}']"

    # get_neighbors / get_attributes → extract entity from next call
    if func_name in ("get_neighbors", "get_attributes"):
        m = _re.search(r"\w+\(([^,)]+)", next_action)
        if m:
            arg = m.group(1).strip()
            if arg.startswith("m.") or arg.startswith("g."):
                return arg

    # intersection, argmax, argmin, count → generic acknowledgement
    return f"(oracle: {current_action} executed)"


# ====================================================================
# DB Environment
# ====================================================================


def _mysql_available() -> bool:
    """Check if Docker + MySQL image is available."""
    if not shutil.which("docker"):
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


class DBEnvironment(TaskEnvironment):
    """Multi-turn DB environment matching the original's interaction protocol.

    The original uses MySQL Docker containers.  We try MySQL first and fall
    back to SQLite with a clear degraded-mode warning.
    """

    @property
    def max_turns(self) -> int:
        return MAX_TURNS_DB

    def __init__(self, use_mysql: bool = True) -> None:
        self._use_mysql = use_mysql and _mysql_available()
        self._conn: Optional[sqlite3.Connection] = None
        self._mysql_conn: Any = None  # mysql.connector connection
        self._mysql_port: Optional[int] = None
        self._mysql_container: Optional[str] = None
        self._record: Optional[EvalRecord] = None
        self._table_info: Dict[str, Any] = {}
        self._answer_info: Dict[str, Any] = {}
        self._answer_type: str = "direct"
        self._agent_final_answer: Optional[str] = None
        self._agent_sql_history: List[str] = []
        self._is_done = False
        self._degraded = False

    def reset(self, record: EvalRecord) -> str:
        self._record = record
        self._table_info = record.metadata.get("table_info", {})
        self._answer_info = record.metadata.get("answer_info", {})
        self._answer_type = record.metadata.get("answer_type", "direct")
        self._agent_final_answer = None
        self._agent_sql_history = []
        self._is_done = False

        if self._use_mysql:
            try:
                self._setup_mysql()
                self._init_mysql_tables()
            except Exception as exc:
                logger.warning(
                    "MySQL setup failed for %s, falling back to SQLite: %s",
                    record.record_id,
                    exc,
                )
                self._use_mysql = False
                self._mysql_conn = None

        if not self._use_mysql:
            self._degraded = True
            logger.warning(
                "DB task %s using SQLite fallback (DEGRADED MODE). "
                "MySQL-specific SQL features will not work correctly. "
                "Install Docker and pull mysql:8.0 for faithful evaluation.",
                record.record_id,
            )
            self._conn = _build_sqlite_db(self._table_info)

        return self._format_schema_observation()

    def step(self, agent_response: str) -> Tuple[str, bool]:
        # Check for "Action: Answer" / "Final Answer:"
        answer_match = re.search(
            r"(?:Action:\s*Answer\s*\n\s*)?Final\s+Answer:\s*(.+)",
            agent_response,
            re.DOTALL | re.IGNORECASE,
        )
        if answer_match:
            self._agent_final_answer = answer_match.group(1).strip()
            self._is_done = True
            return "Answer received.", True

        # Check for "Action: Operation" with SQL
        sql = extract_sql(agent_response)
        if not sql:
            return (
                "Error: Could not parse a valid SQL statement. "
                "Use: Action: Operation\n```sql\n<SQL>\n```\n"
                "Or: Action: Answer\nFinal Answer: <answer>"
            ), False

        self._agent_sql_history.append(sql)

        # Execute SQL — use MySQL if available, otherwise SQLite
        try:
            if self._mysql_conn is not None:
                return self._execute_mysql(sql), False
            elif self._conn is not None:
                cursor = self._conn.execute(sql)
                if sql.strip().upper().startswith("SELECT"):
                    rows = cursor.fetchall()
                    self._conn.commit()
                    if not rows:
                        return "Result: Empty result set", False
                    desc = cursor.description
                    col_names = [d[0] for d in desc] if desc else []
                    result_lines = []
                    if col_names:
                        result_lines.append(str(col_names))
                    for row in rows[:50]:
                        result_lines.append(str(list(row)))
                    if len(rows) > 50:
                        extra = len(rows) - 50
                        result_lines.append(f"... ({extra} more)")
                    header = f"Result: {len(rows)} row(s)\n"
                    return header + "\n".join(result_lines), False
                else:
                    self._conn.commit()
                    n = self._conn.total_changes
                    return f"Result: OK. Rows affected: {n}", False
            else:
                return "Error: No database connection available", False
        except (sqlite3.Error, Exception) as exc:
            return f"Error: SQL execution failed: {exc}", False

    def evaluate(self) -> Tuple[Optional[bool], Dict[str, Any]]:
        meta: Dict[str, Any] = {
            "match_type": f"interactive_db_{self._answer_type}",
            "agent_sql_history": self._agent_sql_history,
            "degraded_mode": self._degraded,
            "scorable": True,
        }

        if self._answer_type == "md5":
            return self._evaluate_md5(meta)
        else:
            return self._evaluate_direct(meta)

    def _evaluate_md5(
        self,
        meta: Dict[str, Any],
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        """Evaluate DML tasks by comparing table state after agent's SQL."""
        table_name = self._table_info.get("name", "data")
        expected_sql = self._answer_info.get("sql", "")
        meta["expected_sql"] = expected_sql

        if not self._agent_sql_history:
            meta["reason"] = "no_sql_executed"
            return False, meta

        if not expected_sql:
            meta["reason"] = "no_ground_truth_sql"
            return None, meta

        # Get actual table state (agent's SQL already executed)
        try:
            if self._mysql_conn is not None:
                actual_rows = self._get_mysql_table_rows(table_name)
            else:
                actual_rows = _get_table_rows(self._conn, table_name)
        except Exception as exc:
            meta["reason"] = f"read_state_failed: {exc}"
            return None, meta

        # Execute ground-truth SQL on fresh DB and compare.
        # When using SQLite fallback, MySQL-specific syntax in the
        # ground-truth SQL will fail.  Fall back to normalized SQL
        # comparison rather than returning unscorable.
        try:
            ref_conn = _build_sqlite_db(self._table_info)
            ref_conn.execute(expected_sql)
            ref_conn.commit()
            expected_rows = _get_table_rows(ref_conn, table_name)
            ref_conn.close()
        except Exception as exc:
            logger.warning(
                "MD5 task %s: ground-truth SQL failed on SQLite (%s). "
                "Falling back to normalized SQL comparison.",
                table_name,
                exc,
            )
            meta["ref_sql_sqlite_error"] = str(exc)
            meta["fallback"] = "normalized_sql_comparison"
            from openjarvis.evals.scorers.lifelong_agent_scorer import (
                _normalize_sql,
            )

            # Compare the last DML statement the agent executed against
            # the ground-truth DML statement.
            agent_dml = ""
            for sql in reversed(self._agent_sql_history):
                upper = sql.strip().upper()
                if upper.startswith(("INSERT", "UPDATE", "DELETE")):
                    agent_dml = sql
                    break
            if not agent_dml:
                agent_dml = (
                    self._agent_sql_history[-1] if self._agent_sql_history else ""
                )
            norm_agent = _normalize_sql(agent_dml)
            norm_expected = _normalize_sql(expected_sql)
            is_correct = norm_agent == norm_expected
            meta["comparison_detail"] = (
                "normalized_sql_match"
                if is_correct
                else f"normalized_sql_mismatch: "
                f"expected={norm_expected!r}, got={norm_agent!r}"
            )
            meta["actual_row_count"] = len(actual_rows)
            return is_correct, meta

        is_correct, detail = _compare_table_states(expected_rows, actual_rows)
        meta["comparison_detail"] = detail
        meta["actual_row_count"] = len(actual_rows)
        meta["expected_row_count"] = len(expected_rows)
        return is_correct, meta

    def _evaluate_direct(
        self,
        meta: Dict[str, Any],
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        """Evaluate SELECT tasks by comparing result tuples."""
        expected_direct = self._answer_info.get("direct")
        meta["expected_sql"] = self._answer_info.get("sql", "")

        if expected_direct is None:
            meta["reason"] = "no_ground_truth_direct"
            return None, meta

        expected_tuples = [r if isinstance(r, list) else [r] for r in expected_direct]
        meta["expected_tuples"] = expected_tuples

        # Strategy 1: Try each SELECT from agent's SQL history (newest first).
        for sql in reversed(self._agent_sql_history):
            if sql.strip().upper().startswith("SELECT"):
                try:
                    if self._mysql_conn is not None:
                        actual_rows = self._execute_mysql_select(sql)
                    else:
                        ref_conn = _build_sqlite_db(self._table_info)
                        cursor = ref_conn.execute(sql)
                        actual_rows = [list(row) for row in cursor.fetchall()]
                        ref_conn.close()
                    is_correct, detail = compare_tuple_lists(
                        expected_tuples,
                        actual_rows,
                    )
                    if is_correct:
                        meta["actual_tuples"] = actual_rows
                        meta["strategy"] = "sql_execution"
                        meta["comparison_detail"] = detail
                        return True, meta
                except Exception as exc:
                    meta["sql_error"] = str(exc)

        # Strategy 2: Parse text from final answer
        if self._agent_final_answer:
            from openjarvis.evals.scorers.lifelong_agent_scorer import (
                _parse_text_answer,
            )

            answer_text = self._agent_final_answer
            if not answer_text.lower().startswith("final answer"):
                answer_text = f"Final Answer: {answer_text}"
            parsed = _parse_text_answer(answer_text)
            if parsed is not None:
                meta["actual_tuples"] = parsed
                meta["strategy"] = "text_answer_parsing"
                is_correct, detail = compare_tuple_lists(expected_tuples, parsed)
                meta["comparison_detail"] = detail
                return is_correct, meta

        meta["reason"] = "no_answer_extracted"
        meta["strategy"] = "none"
        return False, meta

    def _init_mysql_tables(self) -> None:
        """Create and populate tables on the MySQL container.

        Matches the original's protocol: each task gets a fresh database
        with the schema and data from table_info.
        """
        import mysql.connector

        table_name = self._table_info.get("name", "data")
        columns = self._table_info.get("column_info_list", [])
        rows = self._table_info.get("row_list", [])
        db_name = "lifelong_bench"

        conn = mysql.connector.connect(
            host="127.0.0.1",
            user="root",
            password="password",
            port=self._mysql_port,
        )
        cursor = conn.cursor()
        cursor.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
        cursor.execute(f"CREATE DATABASE `{db_name}`")
        cursor.execute(f"USE `{db_name}`")

        col_defs = []
        for col in columns:
            cname = col.get("name", "col")
            ctype = col.get("type", "TEXT")
            col_defs.append(f"`{cname}` {ctype}")
        if not col_defs:
            col_defs = ["`value` TEXT"]

        cursor.execute(f"CREATE TABLE `{table_name}` ({', '.join(col_defs)})")

        if rows and columns:
            ncols = len(columns)
            ph = ", ".join(["%s"] * ncols)
            for row in rows:
                padded = list(row[:ncols])
                while len(padded) < ncols:
                    padded.append(None)
                try:
                    cursor.execute(
                        f"INSERT INTO `{table_name}` VALUES ({ph})",
                        padded,
                    )
                except Exception as exc:
                    logger.debug("Skipping row in MySQL table %s: %s", table_name, exc)

        conn.commit()
        cursor.close()
        conn.close()

        # Store a persistent connection for agent interactions
        self._mysql_conn = mysql.connector.connect(
            host="127.0.0.1",
            user="root",
            password="password",
            port=self._mysql_port,
            database=db_name,
        )

    def _execute_mysql(self, sql: str) -> str:
        """Execute SQL on the MySQL connection, return formatted result."""
        cursor = self._mysql_conn.cursor()
        try:
            cursor.execute(sql)
            if sql.strip().upper().startswith("SELECT"):
                rows = cursor.fetchall()
                if not rows:
                    return "Result: Empty result set"
                desc = cursor.description
                col_names = [d[0] for d in desc] if desc else []
                result_lines = []
                if col_names:
                    result_lines.append(str(col_names))
                for row in rows[:50]:
                    result_lines.append(str(list(row)))
                if len(rows) > 50:
                    result_lines.append(f"... ({len(rows) - 50} more)")
                return f"Result: {len(rows)} row(s)\n" + "\n".join(result_lines)
            else:
                self._mysql_conn.commit()
                return f"Result: OK. Rows affected: {cursor.rowcount}"
        finally:
            cursor.close()

    def _execute_mysql_select(self, sql: str) -> List[List[Any]]:
        """Execute a SELECT on MySQL and return rows as list of lists."""
        cursor = self._mysql_conn.cursor()
        try:
            cursor.execute(sql)
            return [list(row) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def _get_mysql_table_rows(self, table_name: str) -> List[List[Any]]:
        """Read all rows from a MySQL table."""
        cursor = self._mysql_conn.cursor()
        try:
            cursor.execute(f"SELECT * FROM `{table_name}`")
            return [list(row) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def _format_schema_observation(self) -> str:
        table_name = self._table_info.get("name", "data")
        columns = self._table_info.get("column_info_list", [])
        sample_rows = self._table_info.get("row_list", [])

        lines = [f"Table: {table_name}", "Columns:"]
        for col in columns:
            lines.append(f"  - {col.get('name', '?')} ({col.get('type', '?')})")
        if sample_rows:
            col_names = [c.get("name", "?") for c in columns]
            lines.append(f"\nSample data ({len(sample_rows)} rows):")
            lines.append(f"  {col_names}")
            for r in sample_rows[:5]:
                lines.append(f"  {r}")
            if len(sample_rows) > 5:
                lines.append(f"  ... ({len(sample_rows) - 5} more rows)")

        return "\n".join(lines)

    def _setup_mysql(self) -> None:
        """Start a MySQL Docker container and initialize the DB."""
        import socket

        # Find free port
        with socket.socket() as s:
            s.bind(("", 0))
            self._mysql_port = s.getsockname()[1]

        self._mysql_container = f"lifelong-db-{self._mysql_port}"
        subprocess.run(
            ["docker", "rm", "-f", self._mysql_container],
            capture_output=True,
            timeout=30,
        )
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                self._mysql_container,
                "-e",
                "MYSQL_ROOT_PASSWORD=password",
                "-p",
                f"{self._mysql_port}:3306",
                "mysql:8.0",
            ],
            capture_output=True,
            check=True,
            timeout=60,
        )
        # Wait for MySQL to be ready (up to 30s)
        for _ in range(30):
            time.sleep(1)
            try:
                import mysql.connector

                conn = mysql.connector.connect(
                    host="127.0.0.1",
                    user="root",
                    password="password",
                    port=self._mysql_port,
                )
                conn.close()
                break
            except Exception:
                continue
        else:
            raise RuntimeError("MySQL container did not become ready in 30s")

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        if self._mysql_conn is not None:
            try:
                self._mysql_conn.close()
            except Exception:
                pass
            self._mysql_conn = None
        if self._mysql_container:
            try:
                subprocess.run(
                    ["docker", "rm", "-f", self._mysql_container],
                    capture_output=True,
                    timeout=30,
                )
            except Exception:
                pass
            self._mysql_container = None


# ====================================================================
# KG Environment
# ====================================================================


class _Variable:
    """Variable in the KG variable store, matching the original's Variable class."""

    def __init__(
        self,
        idx: int,
        program: str,
        vtype: str = "entity",
        callable: bool = True,
    ):
        self.idx = idx
        self.program = program
        self.type = vtype
        self.callable = callable

    def __repr__(self) -> str:
        return f"#_{self.idx}"


class KGEnvironment(TaskEnvironment):
    """KG API simulation environment.

    The original uses a Freebase SPARQL endpoint.  When no endpoint is
    configured, we simulate API calls using the gold ``action_list`` from
    the dataset as oracle responses and clearly warn about degraded mode.

    Metrics match the original: exact-set match + F1 on answer entities.
    """

    @property
    def max_turns(self) -> int:
        return MAX_TURNS_KG

    def __init__(self, sparql_endpoint: Optional[str] = None) -> None:
        self._sparql_endpoint = sparql_endpoint
        self._record: Optional[EvalRecord] = None
        self._variables: List[_Variable] = []
        self._entity_dict: Dict[str, str] = {}
        self._answer_list: List[str] = []
        self._action_list: List[Dict[str, Any]] = []
        self._action_idx: int = 0
        self._agent_final_answer: Optional[str] = None
        self._is_done = False
        self._degraded = False

    def reset(self, record: EvalRecord) -> str:
        self._record = record
        self._entity_dict = record.metadata.get("entity_dict", {})
        self._answer_list = record.metadata.get("answer_list", [])
        self._action_list = record.metadata.get("action_list", [])
        self._variables = []
        self._action_idx = 0
        self._agent_final_answer = None
        self._final_answer_variable: Optional[_Variable] = None
        self._is_done = False

        if not self._sparql_endpoint:
            self._degraded = True
            if not self._action_list:
                logger.warning(
                    "KG task %s: no SPARQL endpoint and no action_list for "
                    "oracle simulation. API calls will return empty results.",
                    record.record_id,
                )

        # Initialize variables for known entities
        for name, mid in self._entity_dict.items():
            var = _Variable(len(self._variables), mid, "entity")
            self._variables.append(var)

        entity_lines = []
        for name, mid in self._entity_dict.items():
            entity_lines.append(f"  - {name}: {mid}")

        obs = ""
        if entity_lines:
            obs += "Known Entities:\n" + "\n".join(entity_lines) + "\n\n"
        obs += f"Question: {record.metadata.get('question', record.problem)}"
        return obs

    def step(self, agent_response: str) -> Tuple[str, bool]:
        # Check for Final Answer with variable reference (#N) — original format
        var_ref_match = re.search(
            r"Final\s+[Aa]nswer:\s*(?:[Vv]ar(?:iable)?\s*)?#(\d+)",
            agent_response,
        )
        if var_ref_match:
            var_idx = int(var_ref_match.group(1))
            if 0 <= var_idx < len(self._variables):
                var = self._variables[var_idx]
                # Resolve the variable to its program/entity for scoring
                self._agent_final_answer = var.program
                self._final_answer_variable = var
            else:
                self._agent_final_answer = f"#_{var_idx}"
                self._final_answer_variable = None
            self._is_done = True
            return "Answer received.", True

        # Check for Final Answer with raw entities — fallback format
        fa_match = re.search(
            r"(?i)final\s+answer:\s*(.+)",
            agent_response,
            re.DOTALL,
        )
        if fa_match:
            self._agent_final_answer = fa_match.group(1).strip()
            # Truncate at next section
            for stop in ("\n\n", "\nAction:", "\nThought:"):
                pos = self._agent_final_answer.find(stop)
                if pos > 0:
                    self._agent_final_answer = self._agent_final_answer[:pos].strip()
            self._final_answer_variable = None
            self._is_done = True
            return "Answer received.", True

        # Parse API call: Action: func_name(args)
        action_match = re.search(
            r"Action:\s*(\w+)\((.+?)\)",
            agent_response,
            re.DOTALL,
        )
        if not action_match:
            return (
                "Error: Could not parse an API call from your response. "
                "Use format: Action: func_name(arg1, arg2)\n"
                "Or provide: Final Answer: <entity1>, <entity2>"
            ), False

        func_name = action_match.group(1).strip()
        args_str = action_match.group(2).strip()

        return self._execute_api(func_name, args_str), False

    def _execute_api(self, func_name: str, args_str: str) -> str:
        """Execute a KG API call, matching the original's API interface."""
        valid_funcs = {
            "get_relations",
            "get_neighbors",
            "intersection",
            "get_attributes",
            "argmax",
            "argmin",
            "count",
        }
        if func_name not in valid_funcs:
            return (
                f"Error: Unknown API function '{func_name}'. "
                f"Valid: {sorted(valid_funcs)}"
            )

        # If we have oracle action_list, use it for responses.
        # HF dataset stores action_list as strings (e.g. "get_relations(m.03fwl)")
        # not as dicts.  We pair them with the next action in the list as a
        # breadcrumb — the actual result is unknown without a SPARQL endpoint,
        # so we provide the next expected call as a hint, or signal completion.
        if self._action_list and self._action_idx < len(self._action_list):
            oracle = self._action_list[self._action_idx]
            self._action_idx += 1
            # Create a new variable for the result
            new_var = _Variable(
                len(self._variables),
                f"{func_name}({args_str})",
                "entity",
            )
            self._variables.append(new_var)
            # Handle both dict format ({"result": ...}) and string format
            # ("get_relations(m.03fwl)") from the HF dataset
            if isinstance(oracle, dict):
                oracle_result = oracle.get("result", oracle.get("output", ""))
            else:
                # String format: the entry is the expected action call itself,
                # not its result.  Peek at the *next* entry to provide a
                # plausible response, or return a generic acknowledgement.
                if self._action_idx < len(self._action_list):
                    next_action = self._action_list[self._action_idx]
                    if isinstance(next_action, str):
                        # Extract relation/entity hints from the next call
                        oracle_result = _infer_oracle_result(
                            func_name,
                            str(oracle),
                            str(next_action),
                        )
                    else:
                        oracle_result = next_action.get(
                            "result",
                            next_action.get("output", ""),
                        )
                else:
                    oracle_result = f"(oracle: action '{oracle}' executed)"
            return f"Result stored as #{new_var.idx}.\nOutput: {oracle_result}"

        # No oracle — simulate with empty results + warning
        new_var = _Variable(
            len(self._variables),
            f"{func_name}({args_str})",
            "entity",
        )
        self._variables.append(new_var)

        if func_name == "count":
            new_var.callable = False
            return "Result: 0 (no SPARQL endpoint — simulated empty result)"

        return (
            f"Result stored as #{new_var.idx}. "
            f"Output: [] (no SPARQL endpoint — simulated empty result)"
        )

    def evaluate(self) -> Tuple[Optional[bool], Dict[str, Any]]:
        expected = self._answer_list
        expected_set = set(_normalize_entity(a) for a in expected)

        # Extract agent answers — handle both variable references and raw entities
        agent_answers: List[str] = []
        if self._agent_final_answer:
            # If answer came from a variable reference (#N), the program
            # may contain entity IDs or a LISP expression.  Extract entities.
            answer_text = self._agent_final_answer
            # Extract Freebase entity IDs (m.xxx or g.xxx)
            entities = re.findall(r"[mg]\.\w+", answer_text)
            if entities:
                agent_answers = entities
            else:
                parts = re.split(r"[,\n;]", answer_text)
                agent_answers = [a.strip() for a in parts if a.strip()]

        agent_set = set(_normalize_entity(a) for a in agent_answers)
        executable = len(agent_set) > 0
        exact_match = expected_set == agent_set

        # F1 matching the original's calculate_metric()
        tp = len(expected_set & agent_set)
        fp = len(agent_set - expected_set)
        fn = len(expected_set - agent_set)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            (2 * precision * recall / (precision + recall))
            if (precision + recall) > 0
            else 0.0
        )

        meta: Dict[str, Any] = {
            "match_type": "interactive_kg",
            "expected_answers": sorted(expected_set),
            "agent_answers": sorted(agent_set),
            "exact_match": exact_match,
            "f1": f1,
            "precision": precision,
            "recall": recall,
            "executable": executable,
            "degraded_mode": self._degraded,
            "scorable": True,
            "skills": self._record.metadata.get("skills", []) if self._record else [],
        }

        return exact_match, meta

    def close(self) -> None:
        pass


# ====================================================================
# OS Environment
# ====================================================================

# The original uses "local-os/default", a custom image.  We try that first
# then fall back to ubuntu:22.04 with a warning.
_OS_IMAGES = ["local-os/default", "ubuntu:22.04"]


class OSEnvironment(TaskEnvironment):
    """Docker-based OS interaction environment.

    Matches the original's three-phase protocol:
    1. Start container, run initialization_command_item
    2. Agent sends bash commands, gets output
    3. Run evaluation_command_item — pass iff exit_code == 0
    """

    @property
    def max_turns(self) -> int:
        return MAX_TURNS_OS

    def __init__(self, image: Optional[str] = None, timeout: int = 120) -> None:
        self._image = image
        self._timeout = timeout
        self._container_name: Optional[str] = None
        self._record: Optional[EvalRecord] = None
        self._agent_commands: List[str] = []
        self._is_done = False

    def reset(self, record: EvalRecord) -> str:
        self._record = record
        self._agent_commands = []
        self._is_done = False

        if not shutil.which("docker"):
            raise RuntimeError(
                "OS interaction tasks REQUIRE Docker. "
                "Install Docker and ensure the daemon is running."
            )

        # Pick image
        image = self._image
        if not image:
            for candidate in _OS_IMAGES:
                try:
                    result = subprocess.run(
                        ["docker", "image", "inspect", candidate],
                        capture_output=True,
                        timeout=10,
                    )
                    if result.returncode == 0:
                        image = candidate
                        break
                except Exception:
                    continue
            if not image:
                image = "ubuntu:22.04"
                logger.warning(
                    "OS task: 'local-os/default' image not found. "
                    "Falling back to 'ubuntu:22.04'. The original benchmark "
                    "uses a custom image — some tasks may fail."
                )

        # Start container
        self._container_name = f"lifelong-os-{record.record_id.replace('/', '-')}"
        subprocess.run(
            ["docker", "rm", "-f", self._container_name],
            capture_output=True,
            timeout=30,
        )
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                self._container_name,
                image,
                "sleep",
                "600",
            ],
            capture_output=True,
            check=True,
            timeout=60,
        )

        # Run initialization command
        init_cmd = record.metadata.get("init_command", {})
        init_cmd_str = ""
        if isinstance(init_cmd, dict):
            init_cmd_str = init_cmd.get("script", init_cmd.get("command", ""))
        elif isinstance(init_cmd, str):
            init_cmd_str = init_cmd

        if init_cmd_str:
            result = subprocess.run(
                ["docker", "exec", self._container_name, "bash", "-c", init_cmd_str],
                capture_output=True,
                timeout=self._timeout,
            )
            if result.returncode != 0:
                logger.warning(
                    "Init command failed (exit %d): %s",
                    result.returncode,
                    result.stderr.decode(errors="replace")[:200],
                )

        return record.metadata.get("instruction", record.problem)

    def step(self, agent_response: str) -> Tuple[str, bool]:
        # Check for "Act: finish"
        finish_match = re.search(r"Act:\s*finish", agent_response, re.IGNORECASE)
        if finish_match:
            self._is_done = True
            return "Task marked as finished.", True

        # Extract bash commands
        commands = _extract_bash_commands_from_response(agent_response)
        if not commands:
            return (
                "Error: Could not parse a bash command from your response. "
                "Use format:\nAct: bash\n```bash\n<command>\n```\n"
                "Or to finish: Act: finish"
            ), False

        # Execute commands
        outputs: List[str] = []
        for cmd in commands:
            self._agent_commands.append(cmd)
            try:
                result = subprocess.run(
                    ["docker", "exec", self._container_name, "bash", "-c", cmd],
                    capture_output=True,
                    timeout=self._timeout,
                )
                stdout = result.stdout.decode(errors="replace")[:2000]
                stderr = result.stderr.decode(errors="replace")[:500]
                out = f"[exit code: {result.returncode}]"
                if stdout.strip():
                    out += f"\n{stdout}"
                if stderr.strip():
                    out += f"\n[stderr] {stderr}"
                outputs.append(out)
            except subprocess.TimeoutExpired:
                outputs.append(f"[timeout after {self._timeout}s]")
            except Exception as exc:
                outputs.append(f"[error: {exc}]")

        return "\n---\n".join(outputs), False

    def evaluate(self) -> Tuple[Optional[bool], Dict[str, Any]]:
        meta: Dict[str, Any] = {
            "match_type": "interactive_os",
            "agent_commands": self._agent_commands,
            "scorable": True,
        }

        if not self._container_name:
            meta["reason"] = "no_container"
            meta["scorable"] = False
            return None, meta

        rec_meta = self._record.metadata if self._record else {}
        eval_info = rec_meta.get("evaluation_info", {})
        eval_cmd = rec_meta.get("evaluation_command", {})

        # Extract evaluation command string
        eval_cmd_str = ""
        if isinstance(eval_cmd, dict):
            eval_cmd_str = eval_cmd.get("script", eval_cmd.get("command", ""))
        if not eval_cmd_str and isinstance(eval_info, dict):
            # Try nested structure
            nested = eval_info.get("evaluation_command_item", eval_info)
            if isinstance(nested, dict):
                eval_cmd_str = nested.get("script", nested.get("command", ""))
            elif isinstance(nested, str):
                eval_cmd_str = nested

        if not eval_cmd_str:
            meta["reason"] = (
                "no_evaluation_command — cannot determine correctness. "
                "The original benchmark requires evaluation_command_item "
                "with exit_code==0 meaning correct."
            )
            meta["scorable"] = False
            return None, meta

        try:
            result = subprocess.run(
                ["docker", "exec", self._container_name, "bash", "-c", eval_cmd_str],
                capture_output=True,
                timeout=self._timeout,
            )
            meta["eval_exit_code"] = result.returncode
            meta["eval_stdout"] = result.stdout.decode(errors="replace")[:500]
            return result.returncode == 0, meta
        except subprocess.TimeoutExpired:
            meta["reason"] = "eval_command_timeout"
            return False, meta
        except Exception as exc:
            meta["reason"] = f"eval_command_error: {exc}"
            return None, meta

    def close(self) -> None:
        if self._container_name:
            try:
                subprocess.run(
                    ["docker", "rm", "-f", self._container_name],
                    capture_output=True,
                    timeout=30,
                )
            except Exception:
                pass
            self._container_name = None


# ====================================================================
# Helpers (shared with scorer — avoid duplication)
# ====================================================================


def _build_sqlite_db(table_info: Dict[str, Any]) -> sqlite3.Connection:
    """Build an in-memory SQLite DB from table_info."""
    conn = sqlite3.connect(":memory:")
    table_name = table_info.get("name", "data")
    columns = table_info.get("column_info_list", [])
    rows = table_info.get("row_list", [])

    col_defs = []
    for col in columns:
        raw_type = col.get("type", "TEXT")
        base = raw_type.split("(")[0].strip().upper()
        stype = _TYPE_MAP.get(base, "TEXT")
        col_defs.append(f'"{col.get("name", "col")}" {stype}')

    if not col_defs:
        col_defs = ['"value" TEXT']

    conn.execute(f'CREATE TABLE "{table_name}" ({", ".join(col_defs)})')

    if rows and columns:
        ncols = len(columns)
        ph = ", ".join(["?"] * ncols)
        for row in rows:
            padded = list(row[:ncols])
            while len(padded) < ncols:
                padded.append(None)
            try:
                conn.execute(f'INSERT INTO "{table_name}" VALUES ({ph})', padded)
            except sqlite3.Error:
                pass
    conn.commit()
    return conn


def _get_table_rows(
    conn: Optional[sqlite3.Connection],
    table_name: str,
) -> List[List[Any]]:
    if conn is None:
        return []
    cursor = conn.execute(f'SELECT * FROM "{table_name}" ORDER BY rowid')
    return [list(row) for row in cursor.fetchall()]


def _compare_table_states(
    expected: List[List[Any]],
    actual: List[List[Any]],
) -> Tuple[bool, str]:
    if len(expected) != len(actual):
        return False, f"row_count_mismatch: expected {len(expected)}, got {len(actual)}"
    for i, (exp_row, act_row) in enumerate(zip(expected, actual)):
        if len(exp_row) != len(act_row):
            return False, f"col_count_mismatch at row {i}"
        for j, (ev, av) in enumerate(zip(exp_row, act_row)):
            if not values_match(ev, av):
                return False, f"value_mismatch at row {i} col {j}: {ev!r} vs {av!r}"
    return True, "all_match"


def _extract_bash_commands_from_response(text: str) -> List[str]:
    """Extract bash commands from agent response.

    Supports multiple formats matching the original:
    1. Act: bash\\n```bash\\n<cmd>\\n```   (original format)
    2. Act: ```bash\\n<cmd>\\n```          (shorthand)
    3. ```bash\\n<cmd>\\n```               (bare code block)
    """
    commands: List[str] = []

    # Original format: Act: bash\n```bash\n...\n```
    for m in re.finditer(
        r"Act:\s*bash\s*\n\s*```(?:bash)?\s*\n(.*?)\n\s*```",
        text,
        re.DOTALL | re.IGNORECASE,
    ):
        cmd = m.group(1).strip()
        if cmd:
            commands.append(cmd)
    if commands:
        return commands

    # Act: ```bash\n...\n```
    for m in re.finditer(
        r"Act:\s*```(?:bash)?\s*\n(.*?)\n\s*```",
        text,
        re.DOTALL | re.IGNORECASE,
    ):
        cmd = m.group(1).strip()
        if cmd:
            commands.append(cmd)
    if commands:
        return commands

    # ```bash\n...\n```
    for m in re.finditer(
        r"```(?:bash|sh)\s*\n(.*?)\n\s*```",
        text,
        re.DOTALL | re.IGNORECASE,
    ):
        cmd = m.group(1).strip()
        if cmd:
            commands.append(cmd)

    return commands


def create_task_environment(
    record: EvalRecord,
    *,
    sparql_endpoint: Optional[str] = None,
    os_image: Optional[str] = None,
    os_timeout: int = 120,
) -> TaskEnvironment:
    """Factory: create the right environment for a LifelongAgentBench record."""
    subset = record.metadata.get("subset", "db_bench")
    if subset == "db_bench":
        return DBEnvironment()
    elif subset == "knowledge_graph":
        return KGEnvironment(sparql_endpoint=sparql_endpoint)
    elif subset == "os_interaction":
        return OSEnvironment(image=os_image, timeout=os_timeout)
    else:
        raise ValueError(f"Unknown LifelongAgentBench subset: {subset}")


__all__ = [
    "TaskEnvironment",
    "DBEnvironment",
    "KGEnvironment",
    "OSEnvironment",
    "create_task_environment",
]
