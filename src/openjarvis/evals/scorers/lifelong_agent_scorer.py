"""Scorer for LifelongAgentBench.

Reproduces the original evaluation methodology from:
  https://github.com/caixd-220529/LifelongAgentBench

When used with interactive environments (episode_mode=True), the
TaskEnvironment handles scoring directly.  This scorer serves as:

1. **Fallback** for non-interactive (single-shot) evaluation — with loud
   warnings that results are degraded and not faithful to the original.
2. **Helper library** for shared scoring functions used by both the
   environments and this scorer.

Three subset scoring strategies matching the original:

1. **db_bench** — Two modes matching the original ``Task._complete()``:
   - *direct* (SELECT): Execute agent SQL, compare tuples with numeric
     tolerance (``rel_tol=1e-6``).
   - *md5* (INSERT/UPDATE/DELETE): Execute SQL, compare full table state.

2. **knowledge_graph** — Exact-set match + F1 score on answer entities,
   matching the original's ``calculate_metric()``.

3. **os_interaction** — Docker evaluation with exit_code == 0.

IMPORTANT: Single-shot scoring is DEGRADED and will always emit warnings.
The original benchmark is multi-turn interactive.  Use ``episode_mode=True``
with the ``jarvis-agent`` backend for faithful evaluation.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import shutil
import sqlite3
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.evals.core.scorer import Scorer
from openjarvis.evals.core.types import EvalRecord

logger = logging.getLogger(__name__)

_REL_TOLERANCE = 1e-6
_ABS_TOLERANCE = 1e-6

_SINGLE_SHOT_WARNING = (
    "DEGRADED: Single-shot scoring for LifelongAgentBench is NOT faithful "
    "to the original benchmark. The original uses multi-turn interactive "
    "evaluation. Use episode_mode=True for faithful evaluation."
)

_TYPE_MAP: Dict[str, str] = {
    "INT": "INTEGER",
    "INTEGER": "INTEGER",
    "BIGINT": "INTEGER",
    "SMALLINT": "INTEGER",
    "TINYINT": "INTEGER",
    "FLOAT": "REAL",
    "DOUBLE": "REAL",
    "DECIMAL": "REAL",
    "NUMERIC": "REAL",
    "REAL": "REAL",
    "TEXT": "TEXT",
    "VARCHAR": "TEXT",
    "CHAR": "TEXT",
    "BLOB": "BLOB",
    "DATE": "TEXT",
    "DATETIME": "TEXT",
    "TIMESTAMP": "TEXT",
    "BOOLEAN": "INTEGER",
    "BOOL": "INTEGER",
}


class LifelongAgentScorer(Scorer):
    """Scorer for LifelongAgentBench.

    When used with interactive environments (episode_mode), the environment
    handles scoring and this scorer is bypassed.  For single-shot mode,
    this scorer provides degraded fallback scoring with clear warnings.

    Constructor accepts ``(judge_backend, judge_model)`` for CLI
    compatibility but does not use them — all scoring is deterministic.
    """

    scorer_id = "lifelong-agent"

    _warned_single_shot = False

    def __init__(self, judge_backend: Any = None, judge_model: str = "") -> None:
        pass

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        # If this result came from interactive evaluation, the metadata
        # already contains the score — pass it through.
        # (The EvalRunner handles this case directly; this is just safety.)

        if not model_answer or not model_answer.strip():
            return False, {"reason": "empty_response", "match_type": "empty"}

        # Warn loudly about single-shot degradation (once per process)
        if not LifelongAgentScorer._warned_single_shot:
            logger.warning(_SINGLE_SHOT_WARNING)
            LifelongAgentScorer._warned_single_shot = True

        subset = record.metadata.get("subset", "db_bench")

        if subset == "db_bench":
            ok, meta = self._score_db(record, model_answer)
        elif subset == "knowledge_graph":
            ok, meta = self._score_kg(record, model_answer)
        elif subset == "os_interaction":
            ok, meta = self._score_os(record, model_answer)
        else:
            return None, {"reason": f"unknown_subset: {subset}"}

        meta["degraded_single_shot"] = True
        meta["warning"] = _SINGLE_SHOT_WARNING
        return ok, meta

    # ================================================================
    # DB scoring (matches original's Task._complete + DirectTypeAnswerValidator)
    # ================================================================

    def _score_db(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        table_info = record.metadata.get("table_info", {})
        answer_info = record.metadata.get("answer_info", {})
        skills = record.metadata.get("skills", [])
        answer_type = record.metadata.get("answer_type", "direct")

        if not table_info:
            return None, {"reason": "no_table_info", "match_type": "error"}

        try:
            conn = build_db(table_info)
        except Exception as exc:
            logger.warning("DB build failed for %s: %s", record.record_id, exc)
            return None, {"reason": f"db_build_failed: {exc}", "match_type": "error"}

        try:
            if answer_type == "md5":
                return self._score_db_md5(
                    conn,
                    model_answer,
                    table_info,
                    answer_info,
                    skills,
                )
            else:
                return self._score_db_direct(
                    conn,
                    model_answer,
                    answer_info,
                    skills,
                )
        finally:
            conn.close()

    def _score_db_md5(
        self,
        conn: sqlite3.Connection,
        model_answer: str,
        table_info: Dict,
        answer_info: Dict,
        skills: List[str],
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        expected_sql = answer_info.get("sql", "")
        table_name = table_info.get("name", "data")
        agent_sql = extract_sql(model_answer)

        meta: Dict[str, Any] = {
            "match_type": "md5_table_state",
            "expected_sql": expected_sql,
            "agent_sql": agent_sql,
            "skills": skills,
            "scorable": True,
        }

        if not agent_sql:
            meta["reason"] = "no_sql_extracted"
            return False, meta

        try:
            conn.execute(agent_sql)
            conn.commit()
        except sqlite3.Error as exc:
            meta["reason"] = f"agent_sql_error: {exc}"
            meta["sql_error"] = str(exc)
            return False, meta

        try:
            actual_rows = _get_table_rows(conn, table_name)
        except sqlite3.Error as exc:
            meta["reason"] = f"read_state_failed: {exc}"
            return None, meta

        if not expected_sql:
            meta["reason"] = "no_ground_truth_sql"
            return None, meta

        # Try executing ground-truth SQL on a fresh SQLite DB.  The original
        # uses MySQL, so MySQL-specific syntax (backticks, MD5(), CONCAT_WS,
        # GROUP_CONCAT) will fail on SQLite.  When that happens, fall back to
        # comparing the agent's SQL text against the ground-truth SQL text
        # (normalized), rather than silently returning None/unscorable.
        try:
            ref_conn = build_db(table_info)
            ref_conn.execute(expected_sql)
            ref_conn.commit()
            expected_rows = _get_table_rows(ref_conn, table_name)
            ref_conn.close()
        except Exception as exc:
            # Ground-truth SQL failed on SQLite (likely MySQL-specific syntax).
            # Fall back: compare normalized SQL strings and table state hashes.
            logger.warning(
                "MD5 task %s: ground-truth SQL failed on SQLite (%s). "
                "Falling back to normalized SQL comparison. Use MySQL/Docker "
                "for faithful evaluation of DML tasks.",
                table_name,
                exc,
            )
            meta["ref_sql_sqlite_error"] = str(exc)
            # Compare: did the agent execute the same DML statement?
            norm_agent = _normalize_sql(agent_sql)
            norm_expected = _normalize_sql(expected_sql)
            is_correct = norm_agent == norm_expected
            meta["comparison_detail"] = (
                "normalized_sql_match"
                if is_correct
                else f"normalized_sql_mismatch: expected={norm_expected!r}, got={norm_agent!r}"
            )
            meta["fallback"] = "normalized_sql_comparison"
            meta["actual_hash"] = _hash_table_state(actual_rows)
            meta["actual_row_count"] = len(actual_rows)
            return is_correct, meta

        is_correct, detail = _compare_table_states(expected_rows, actual_rows)
        meta["actual_hash"] = _hash_table_state(actual_rows)
        meta["expected_hash"] = _hash_table_state(expected_rows)
        meta["actual_row_count"] = len(actual_rows)
        meta["expected_row_count"] = len(expected_rows)
        meta["comparison_detail"] = detail
        return is_correct, meta

    def _score_db_direct(
        self,
        conn: sqlite3.Connection,
        model_answer: str,
        answer_info: Dict,
        skills: List[str],
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        expected_direct = answer_info.get("direct")
        expected_sql = answer_info.get("sql", "")

        meta: Dict[str, Any] = {
            "match_type": "direct_tuple_comparison",
            "expected_sql": expected_sql,
            "skills": skills,
            "scorable": True,
        }

        if expected_direct is None:
            meta["reason"] = "no_ground_truth_direct"
            return None, meta

        expected_tuples = [r if isinstance(r, list) else [r] for r in expected_direct]
        meta["expected_tuples"] = expected_tuples

        agent_sql = extract_sql(model_answer)
        meta["agent_sql"] = agent_sql

        if agent_sql:
            try:
                cursor = conn.execute(agent_sql)
                actual_rows = [list(row) for row in cursor.fetchall()]
                meta["actual_tuples"] = actual_rows
                is_correct, detail = compare_tuple_lists(
                    expected_tuples,
                    actual_rows,
                )
                meta["comparison_detail"] = detail
                meta["strategy"] = "sql_execution"
                return is_correct, meta
            except sqlite3.Error as exc:
                meta["sql_error"] = str(exc)
                logger.debug(
                    "SQL execution failed, trying text parsing: %s",
                    exc,
                )

        parsed = _parse_text_answer(model_answer)
        if parsed is not None:
            meta["actual_tuples"] = parsed
            meta["strategy"] = "text_answer_parsing"
            is_correct, detail = compare_tuple_lists(expected_tuples, parsed)
            meta["comparison_detail"] = detail
            return is_correct, meta

        meta["reason"] = "no_answer_extracted"
        meta["strategy"] = "none"
        return False, meta

    # ================================================================
    # KG scoring (matches original's exact match + F1)
    # ================================================================

    def _score_kg(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        expected = record.metadata.get("answer_list", [])
        skills = record.metadata.get("skills", [])

        # The original KG benchmark requires multi-turn interaction with a
        # SPARQL endpoint.  The agent builds up variables via API calls and
        # provides "Final Answer: #N" referencing a variable.  The system
        # then executes the composed query to get the actual entity set.
        #
        # In single-shot mode we cannot resolve variable references — any
        # attempt to heuristically extract entity IDs from the response text
        # produces unreliable results (IDs from intermediate reasoning, not
        # the final answer).  Return unscorable rather than misleading scores.
        logger.error(
            "KG task %s: single-shot scoring is NOT possible for knowledge "
            "graph tasks. The original benchmark requires multi-turn "
            "interaction with a SPARQL endpoint to resolve variable "
            "references. Use episode_mode=True for faithful evaluation.",
            record.record_id,
        )
        return None, {
            "match_type": "kg_unscorable_single_shot",
            "expected_answers": [str(a) for a in expected],
            "skills": skills,
            "scorable": False,
            "reason": (
                "KG tasks require multi-turn interactive evaluation with a "
                "SPARQL endpoint. Single-shot scoring cannot resolve variable "
                "references (Final Answer: #N). Use episode_mode=True."
            ),
        }

    # ================================================================
    # OS scoring (matches original's Docker-based evaluation)
    # ================================================================

    def _score_os(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        skills = record.metadata.get("skills", [])
        init_command = record.metadata.get("init_command", {})
        eval_info = record.metadata.get("evaluation_info", {})
        eval_command = record.metadata.get("evaluation_command", {})

        meta: Dict[str, Any] = {
            "match_type": "os_docker_eval",
            "skills": skills,
        }

        if not _docker_available():
            meta["scorable"] = False
            meta["reason"] = (
                "OS interaction tasks REQUIRE Docker for evaluation. "
                "The original runs: (1) initialization commands, "
                "(2) agent's bash commands, (3) evaluation commands "
                "where exit_code==0 means correct. "
                "Install Docker and ensure the daemon is running."
            )
            logger.error(
                "OS task %s: Docker not available — task NOT scorable. "
                "Install Docker for faithful evaluation.",
                record.record_id,
            )
            return None, meta

        meta["scorable"] = True

        agent_commands = _extract_bash_commands(model_answer)
        meta["agent_commands"] = agent_commands

        if not agent_commands:
            meta["reason"] = "no_bash_commands_extracted"
            return False, meta

        try:
            is_correct = _evaluate_os_in_docker(
                init_command,
                agent_commands,
                eval_command,
                eval_info,
            )
            meta["docker_eval_completed"] = True
            return is_correct, meta
        except Exception as exc:
            logger.warning("Docker OS eval failed: %s", exc)
            meta["reason"] = f"docker_eval_error: {exc}"
            meta["docker_eval_completed"] = False
            return None, meta


# ====================================================================
# DB helpers
# ====================================================================


def build_db(table_info: Dict[str, Any]) -> sqlite3.Connection:
    """Build an in-memory SQLite DB from table_info.

    Note: The original uses MySQL Docker containers.  SQLite is used
    as a portable fallback.  MySQL-specific features (e.g. backtick
    quoting, GROUP_CONCAT, MD5()) will not be available.
    """
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
        for row_idx, row in enumerate(rows):
            padded = list(row[:ncols])
            while len(padded) < ncols:
                padded.append(None)
            try:
                conn.execute(
                    f'INSERT INTO "{table_name}" VALUES ({ph})',
                    padded,
                )
            except sqlite3.Error as exc:
                logger.debug(
                    "Skipping row %d in table %s: %s",
                    row_idx,
                    table_name,
                    exc,
                )

    conn.commit()
    return conn


def _get_table_rows(
    conn: sqlite3.Connection,
    table_name: str,
) -> List[List[Any]]:
    cursor = conn.execute(
        f'SELECT * FROM "{table_name}" ORDER BY rowid',
    )
    return [list(row) for row in cursor.fetchall()]


def _hash_table_state(rows: List[List[Any]]) -> str:
    row_hashes = []
    for row in rows:
        concat = ",".join(str(v) if v is not None else "NULL" for v in row)
        row_hashes.append(hashlib.md5(concat.encode()).hexdigest())
    row_hashes.sort()
    return hashlib.md5("".join(row_hashes).encode()).hexdigest()


def _compare_table_states(
    expected: List[List[Any]],
    actual: List[List[Any]],
) -> Tuple[bool, str]:
    if len(expected) != len(actual):
        return False, (
            f"row_count_mismatch: expected {len(expected)}, got {len(actual)}"
        )
    for i, (exp_row, act_row) in enumerate(zip(expected, actual)):
        if len(exp_row) != len(act_row):
            return False, (
                f"col_count_mismatch at row {i}: expected "
                f"{len(exp_row)}, got {len(act_row)}"
            )
        for j, (exp_val, act_val) in enumerate(zip(exp_row, act_row)):
            if not values_match(exp_val, act_val):
                return False, (
                    f"value_mismatch at row {i} col {j}: "
                    f"expected {exp_val!r}, got {act_val!r}"
                )
    return True, "all_match"


# ====================================================================
# SQL extraction (matches original's Action: Operation format)
# ====================================================================


def extract_sql(text: str) -> str:
    text = text.strip()

    # Action: Operation\n```sql\n...\n```
    m = re.search(
        r"Action:\s*Operation\s*\n\s*```(?:sql)?\s*\n?(.*?)\n?\s*```",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    # ```sql ... ```
    m = re.search(
        r"```sql\s*\n?(.*?)\n?```",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    # ``` ... ``` with SQL inside
    m = re.search(r"```\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        candidate = m.group(1).strip()
        if _looks_like_sql(candidate):
            return candidate

    # "Operation: <SQL>" (shorthand)
    m = re.search(r"(?i)operation:\s*(.+)", text, re.DOTALL)
    if m:
        candidate = m.group(1).strip()
        answer_pos = re.search(r"(?i)action:\s*answer", candidate)
        if answer_pos:
            candidate = candidate[: answer_pos.start()].strip()
        if _looks_like_sql(candidate):
            return candidate

    # Bare SQL
    for line in text.split("\n"):
        stripped = line.strip()
        if _looks_like_sql(stripped):
            sql_lines = [stripped]
            start_idx = text.split("\n").index(line)
            for cont_line in text.split("\n")[start_idx + 1 :]:
                cont = cont_line.strip()
                if not cont or cont.startswith("Action:") or cont.startswith("Act:"):
                    break
                sql_lines.append(cont)
            return " ".join(sql_lines)

    return ""


def _looks_like_sql(text: str) -> bool:
    kws = ("SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP")
    upper = text.strip().upper()
    return any(upper.startswith(kw) for kw in kws)


def _normalize_sql(sql: str) -> str:
    """Normalize SQL for comparison when execution-based comparison fails.

    Strips whitespace, lowercases, removes backticks and trailing semicolons
    so that ``INSERT INTO `t` VALUES (1)`` matches ``INSERT INTO t VALUES (1)``.
    """
    s = sql.strip().lower()
    s = s.replace("`", "")
    s = re.sub(r"\s+", " ", s)
    s = s.rstrip(";").strip()
    return s


# ====================================================================
# Text answer parsing (matches DirectTypeAnswerValidator)
# ====================================================================


def _parse_text_answer(text: str) -> Optional[List[List[Any]]]:
    m = re.search(
        r"(?:Action:\s*Answer\s*\n\s*)?Final\s+Answer:\s*(.+)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return None

    answer_text = m.group(1).strip()

    try:
        parsed = _safe_literal_eval(answer_text)
        if isinstance(parsed, list):
            if parsed and isinstance(parsed[0], (list, tuple)):
                return [list(row) for row in parsed]
            return [list(parsed)]
        return [[parsed]]
    except (ValueError, SyntaxError):
        pass

    if "," in answer_text:
        parts = [p.strip().strip("'\"") for p in answer_text.split(",")]
        typed = [_try_numeric(p) for p in parts if p]
        return [typed] if typed else None

    val = _try_numeric(answer_text.strip().strip("'\""))
    if val is not None or answer_text.strip():
        return [[val if val is not None else answer_text.strip()]]

    return None


def _safe_literal_eval(s: str) -> Any:
    s = re.sub(r"Decimal\('([^']*)'\)", r"\1", s)
    import ast

    return ast.literal_eval(s)


def _try_numeric(s: str) -> Any:
    try:
        return int(s)
    except (ValueError, TypeError):
        pass
    try:
        return float(s)
    except (ValueError, TypeError):
        pass
    return s if s else None


# ====================================================================
# KG helpers (matches original's answer extraction + F1)
# ====================================================================


def extract_kg_answers(text: str) -> List[str]:
    text = text.strip()

    # Original format: Final Answer: #N (variable reference).
    # In single-shot mode we can't resolve variables, so extract any
    # entity IDs from the surrounding text as a best-effort fallback.
    var_ref = re.search(
        r"Final\s+[Aa]nswer:\s*(?:[Vv]ar(?:iable)?\s*)?#(\d+)",
        text,
    )
    if var_ref:
        # Can't resolve variable in single-shot mode — look for entity IDs
        # in the full response as a heuristic.
        entities = re.findall(r"[mg]\.\w+", text)
        if entities:
            return entities
        return [f"#_{var_ref.group(1)}"]

    m = re.search(r"(?i)final\s+answer:\s*(.+)", text, re.DOTALL)
    if m:
        answer_text = m.group(1).strip()
        for stop in ("\n\n", "\nAction:", "\nThought:"):
            pos = answer_text.find(stop)
            if pos > 0:
                answer_text = answer_text[:pos].strip()

        entities = re.findall(r"[mg]\.\w+", answer_text)
        if entities:
            return entities

        parts = re.split(r"[,\n;]", answer_text)
        return [a.strip() for a in parts if a.strip()]

    entities = re.findall(r"[mg]\.\w+", text)
    if entities:
        return entities

    return [text.strip()] if text.strip() else []


def _normalize_entity(entity: Any) -> str:
    s = str(entity).strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        s = s[1:-1]
    return s


# ====================================================================
# OS helpers (matches original's Docker evaluation)
# ====================================================================


def _docker_available() -> bool:
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


def _extract_bash_commands(text: str) -> List[str]:
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

    for m in re.finditer(
        r"```(?:bash|sh)\s*\n(.*?)\n\s*```",
        text,
        re.DOTALL | re.IGNORECASE,
    ):
        cmd = m.group(1).strip()
        if cmd:
            commands.append(cmd)
    if commands:
        return commands

    for m in re.finditer(r"```\s*\n(.*?)\n\s*```", text, re.DOTALL):
        cmd = m.group(1).strip()
        if cmd and not _looks_like_sql(cmd):
            commands.append(cmd)

    return commands


def _evaluate_os_in_docker(
    init_command: Dict[str, Any],
    agent_commands: List[str],
    eval_command: Dict[str, Any],
    eval_info: Dict[str, Any],
) -> bool:
    """Run OS evaluation in Docker matching the original's protocol."""
    container_name = "lifelong-agent-os-eval"
    # Try the original's custom image first, fall back to ubuntu:22.04
    image = "ubuntu:22.04"
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", "local-os/default"],
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            image = "local-os/default"
        else:
            logger.warning(
                "OS eval: 'local-os/default' image not found, using '%s'. "
                "Build the original's Docker image for faithful evaluation.",
                image,
            )
    except Exception:
        pass

    try:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            timeout=30,
        )
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                container_name,
                image,
                "sleep",
                "300",
            ],
            capture_output=True,
            check=True,
            timeout=60,
        )

        init_cmd_str = init_command.get("script", init_command.get("command", ""))
        if init_cmd_str:
            result = subprocess.run(
                ["docker", "exec", container_name, "bash", "-c", init_cmd_str],
                capture_output=True,
                timeout=120,
            )
            if result.returncode != 0:
                logger.warning(
                    "Init command failed (exit %d): %s",
                    result.returncode,
                    result.stderr.decode(errors="replace")[:200],
                )

        for cmd in agent_commands:
            subprocess.run(
                ["docker", "exec", container_name, "bash", "-c", cmd],
                capture_output=True,
                timeout=120,
            )

        eval_cmd_str = eval_command.get("script", eval_command.get("command", ""))
        if not eval_cmd_str:
            eval_cmd_str = eval_info.get("script", eval_info.get("command", ""))
        if not eval_cmd_str:
            # Try nested evaluation_command_item
            nested = eval_info.get("evaluation_command_item", {})
            if isinstance(nested, dict):
                eval_cmd_str = nested.get("script", nested.get("command", ""))

        if not eval_cmd_str:
            logger.error(
                "No evaluation command found — cannot determine correctness. "
                "The original benchmark requires evaluation_command_item."
            )
            return False

        result = subprocess.run(
            ["docker", "exec", container_name, "bash", "-c", eval_cmd_str],
            capture_output=True,
            timeout=120,
        )
        return result.returncode == 0

    except subprocess.TimeoutExpired:
        logger.warning("Docker command timed out")
        return False
    except subprocess.CalledProcessError as exc:
        logger.warning("Docker command failed: %s", exc)
        return False
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True,
            timeout=30,
        )


# ====================================================================
# Value comparison (matches original's DirectTypeAnswerValidator)
# ====================================================================


def compare_tuple_lists(
    expected: List[List[Any]],
    actual: List[List[Any]],
) -> Tuple[bool, str]:
    if len(expected) != len(actual):
        return False, (
            f"row_count_mismatch: expected {len(expected)}, got {len(actual)}"
        )
    for i, (exp_row, act_row) in enumerate(zip(expected, actual)):
        if len(exp_row) != len(act_row):
            return False, (
                f"col_count_mismatch at row {i}: expected "
                f"{len(exp_row)}, got {len(act_row)}"
            )
        for j, (exp_val, act_val) in enumerate(zip(exp_row, act_row)):
            if not values_match(exp_val, act_val):
                return False, (
                    f"value_mismatch at row {i} col {j}: "
                    f"expected {exp_val!r}, got {act_val!r}"
                )
    return True, "all_match"


def values_match(expected: Any, actual: Any) -> bool:
    if expected is None and actual is None:
        return True
    if expected is None or actual is None:
        return False

    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if expected == 0 and actual == 0:
            return True
        return math.isclose(
            float(expected),
            float(actual),
            rel_tol=_REL_TOLERANCE,
            abs_tol=_ABS_TOLERANCE,
        )

    try:
        exp_f = float(expected)
        act_f = float(actual)
        if exp_f == 0 and act_f == 0:
            return True
        return math.isclose(
            exp_f,
            act_f,
            rel_tol=_REL_TOLERANCE,
            abs_tol=_ABS_TOLERANCE,
        )
    except (ValueError, TypeError):
        pass

    return str(expected).strip() == str(actual).strip()


__all__ = ["LifelongAgentScorer"]
