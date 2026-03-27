"""Database query tool — execute SQL queries against SQLite and PostgreSQL."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, List, Optional, Tuple

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

# ---------------------------------------------------------------------------
# SQL validation helpers
# ---------------------------------------------------------------------------

# Statements allowed when read_only=True (case-insensitive prefix match)
_READ_ONLY_PREFIXES = ("SELECT", "EXPLAIN", "PRAGMA", "DESCRIBE", "SHOW")

# Dangerous keywords blocked when read_only=True
_WRITE_KEYWORDS = re.compile(
    r"\b(DROP|DELETE|INSERT|UPDATE|ALTER|CREATE|TRUNCATE)\b",
    re.IGNORECASE,
)


def _is_read_only_query(query: str) -> bool:
    """Return True if *query* is safe for read-only mode.

    Allows SELECT, EXPLAIN, PRAGMA, DESCRIBE, SHOW, and WITH ... SELECT
    (common table expressions that end with a SELECT).
    """
    stripped = query.strip().rstrip(";").strip()
    if not stripped:
        return False

    upper = stripped.upper()

    # Direct prefix match for simple statements
    for prefix in _READ_ONLY_PREFIXES:
        if upper.startswith(prefix):
            return True

    # WITH ... SELECT (common table expressions)
    if upper.startswith("WITH"):
        # Check that the body after WITH eventually contains SELECT
        # and does not contain write keywords
        if _WRITE_KEYWORDS.search(stripped):
            return False
        # Must contain a SELECT somewhere after WITH
        if re.search(r"\bSELECT\b", upper):
            return True
        return False

    return False


def _format_table(columns: List[str], rows: List[Tuple[Any, ...]]) -> str:
    """Format query results as a pipe-delimited table."""
    if not columns:
        return "(no columns)"

    # Convert all values to strings
    str_rows = [[str(v) for v in row] for row in rows]

    # Compute column widths
    widths = [len(c) for c in columns]
    for row in str_rows:
        for i, val in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(val))

    # Build header
    header = " | ".join(c.ljust(widths[i]) for i, c in enumerate(columns))
    separator = "-+-".join("-" * w for w in widths)

    # Build rows
    lines = [header, separator]
    for row in str_rows:
        line = " | ".join(
            (row[i] if i < len(row) else "").ljust(widths[i])
            for i in range(len(columns))
        )
        lines.append(line)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# DatabaseQueryTool
# ---------------------------------------------------------------------------


@ToolRegistry.register("db_query")
class DatabaseQueryTool(BaseTool):
    """Execute SQL queries against SQLite or PostgreSQL databases."""

    tool_id = "db_query"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="db_query",
            description=(
                "Execute a SQL query against a SQLite or PostgreSQL database."
                " Returns results as a formatted table."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "SQL query to execute.",
                    },
                    "db_path": {
                        "type": "string",
                        "description": (
                            "Path to a SQLite database file."
                            " Defaults to an in-memory database."
                        ),
                    },
                    "db_url": {
                        "type": "string",
                        "description": (
                            "PostgreSQL connection URL"
                            " (e.g. postgresql://user:pass@host/db)."
                        ),
                    },
                    "read_only": {
                        "type": "boolean",
                        "description": (
                            "Restrict to read-only queries"
                            " (SELECT, EXPLAIN, PRAGMA). Default: true."
                        ),
                    },
                    "max_rows": {
                        "type": "integer",
                        "description": (
                            "Maximum number of result rows to return. Default: 100."
                        ),
                    },
                },
                "required": ["query"],
            },
            category="database",
            timeout_seconds=30.0,
            required_capabilities=["code:execute"],
        )

    def execute(self, **params: Any) -> ToolResult:
        query: str = params.get("query", "")
        db_path: Optional[str] = params.get("db_path")
        db_url: Optional[str] = params.get("db_url")
        read_only: bool = params.get("read_only", True)
        max_rows: int = params.get("max_rows", 100)

        if not query:
            return ToolResult(
                tool_name="db_query",
                content="No query provided.",
                success=False,
            )

        # Enforce read-only restrictions
        if read_only and not _is_read_only_query(query):
            return ToolResult(
                tool_name="db_query",
                content=(
                    "Query blocked: only SELECT, EXPLAIN, PRAGMA,"
                    " DESCRIBE, SHOW, and WITH...SELECT are allowed"
                    " in read-only mode."
                ),
                success=False,
            )

        # Route to the appropriate backend
        if db_url:
            return self._execute_postgresql(
                query,
                db_url,
                read_only,
                max_rows,
            )
        return self._execute_sqlite(query, db_path, read_only, max_rows)

    # -----------------------------------------------------------------------
    # SQLite backend
    # -----------------------------------------------------------------------

    def _execute_sqlite(
        self,
        query: str,
        db_path: Optional[str],
        read_only: bool,
        max_rows: int,
    ) -> ToolResult:
        # Validate db_path against sensitive file policy
        if db_path:
            from openjarvis.security.file_policy import is_sensitive_file

            p = Path(db_path)
            if is_sensitive_file(p):
                return ToolResult(
                    tool_name="db_query",
                    content=f"Access denied: {db_path} is a sensitive file.",
                    success=False,
                )

        # Build connection string
        if read_only and db_path:
            # Use URI mode for read-only access to file databases
            uri_path = Path(db_path).resolve().as_uri() + "?mode=ro"
            conn_str = uri_path
            use_uri = True
        elif db_path:
            conn_str = db_path
            use_uri = False
        else:
            conn_str = ":memory:"
            use_uri = False

        try:
            conn = sqlite3.connect(conn_str, uri=use_uri)
        except sqlite3.OperationalError as exc:
            return ToolResult(
                tool_name="db_query",
                content=f"Database connection error: {exc}",
                success=False,
            )

        try:
            cursor = conn.cursor()
            cursor.execute(query)

            # Fetch column names
            column_names: List[str] = []
            if cursor.description:
                column_names = [desc[0] for desc in cursor.description]

            # Fetch rows (up to max_rows)
            rows = cursor.fetchmany(max_rows)
            row_count = len(rows)

            # Commit write operations so changes persist
            if not read_only:
                conn.commit()

            # Format output
            if column_names:
                content = _format_table(column_names, rows)
            else:
                content = (
                    f"Query executed successfully. Rows affected: {cursor.rowcount}"
                )

            return ToolResult(
                tool_name="db_query",
                content=content,
                success=True,
                metadata={
                    "row_count": row_count,
                    "column_names": column_names,
                    "db_type": "sqlite",
                },
            )
        except sqlite3.OperationalError as exc:
            return ToolResult(
                tool_name="db_query",
                content=f"SQL error: {exc}",
                success=False,
            )
        except sqlite3.Error as exc:
            return ToolResult(
                tool_name="db_query",
                content=f"Database error: {exc}",
                success=False,
            )
        finally:
            conn.close()

    # -----------------------------------------------------------------------
    # PostgreSQL backend
    # -----------------------------------------------------------------------

    def _execute_postgresql(
        self,
        query: str,
        db_url: str,
        read_only: bool,
        max_rows: int,
    ) -> ToolResult:
        try:
            import psycopg2  # noqa: F401
        except ImportError:
            return ToolResult(
                tool_name="db_query",
                content=(
                    "PostgreSQL support requires the psycopg2 package."
                    " Install it with: pip install psycopg2-binary"
                ),
                success=False,
            )

        try:
            conn = psycopg2.connect(db_url)
            if read_only:
                conn.set_session(readonly=True, autocommit=True)
        except Exception as exc:
            return ToolResult(
                tool_name="db_query",
                content=f"PostgreSQL connection error: {exc}",
                success=False,
            )

        try:
            cursor = conn.cursor()
            cursor.execute(query)

            # Fetch column names
            column_names: List[str] = []
            if cursor.description:
                column_names = [desc[0] for desc in cursor.description]

            # Fetch rows (up to max_rows)
            rows = cursor.fetchmany(max_rows) if cursor.description else []
            row_count = len(rows)

            # Format output
            if column_names:
                content = _format_table(column_names, rows)
            else:
                content = (
                    f"Query executed successfully. Rows affected: {cursor.rowcount}"
                )

            return ToolResult(
                tool_name="db_query",
                content=content,
                success=True,
                metadata={
                    "row_count": row_count,
                    "column_names": column_names,
                    "db_type": "postgresql",
                },
            )
        except Exception as exc:
            return ToolResult(
                tool_name="db_query",
                content=f"PostgreSQL error: {exc}",
                success=False,
            )
        finally:
            conn.close()


__all__ = ["DatabaseQueryTool"]
