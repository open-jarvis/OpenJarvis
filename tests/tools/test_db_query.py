"""Tests for the db_query tool."""

from __future__ import annotations

import sqlite3

from friday_ai.tools.db_query import DatabaseQueryTool


class TestDatabaseQueryTool:
    """Tests for DatabaseQueryTool."""

    def test_spec(self):
        tool = DatabaseQueryTool()
        assert tool.spec.name == "db_query"
        assert tool.spec.category == "database"
        assert tool.spec.timeout_seconds == 30.0
        assert "code:execute" in tool.spec.required_capabilities
        assert "query" in tool.spec.parameters["required"]

    def test_no_query(self):
        tool = DatabaseQueryTool()
        result = tool.execute(query="")
        assert result.success is False
        assert "No query" in result.content

    def test_simple_select_in_memory(self):
        """SELECT on in-memory database using a literal values query."""
        tool = DatabaseQueryTool()
        result = tool.execute(query="SELECT 1 AS value, 'hello' AS greeting")
        assert result.success is True
        assert "value" in result.content
        assert "greeting" in result.content
        assert "1" in result.content
        assert "hello" in result.content
        assert result.metadata["db_type"] == "sqlite"
        assert result.metadata["row_count"] == 1
        assert result.metadata["column_names"] == ["value", "greeting"]

    def test_read_only_blocks_insert(self):
        tool = DatabaseQueryTool()
        result = tool.execute(
            query="INSERT INTO users VALUES (1, 'Alice')",
        )
        assert result.success is False
        lower = result.content.lower()
        assert "blocked" in lower or "read-only" in lower

    def test_read_only_blocks_delete(self):
        tool = DatabaseQueryTool()
        result = tool.execute(query="DELETE FROM users WHERE id=1")
        assert result.success is False
        lower = result.content.lower()
        assert "blocked" in lower or "read-only" in lower

    def test_read_only_blocks_drop(self):
        tool = DatabaseQueryTool()
        result = tool.execute(query="DROP TABLE users")
        assert result.success is False
        lower = result.content.lower()
        assert "blocked" in lower or "read-only" in lower

    def test_read_only_blocks_update(self):
        tool = DatabaseQueryTool()
        result = tool.execute(query="UPDATE users SET name='Bob' WHERE id=1")
        assert result.success is False

    def test_read_only_blocks_alter(self):
        tool = DatabaseQueryTool()
        result = tool.execute(query="ALTER TABLE users ADD COLUMN age INTEGER")
        assert result.success is False

    def test_read_only_blocks_create(self):
        tool = DatabaseQueryTool()
        result = tool.execute(query="CREATE TABLE evil (id INTEGER)")
        assert result.success is False

    def test_read_only_blocks_truncate(self):
        tool = DatabaseQueryTool()
        result = tool.execute(query="TRUNCATE TABLE users")
        assert result.success is False

    def test_pragma_allowed(self):
        tool = DatabaseQueryTool()
        result = tool.execute(query="PRAGMA table_info('sqlite_master')")
        assert result.success is True

    def test_explain_allowed(self):
        tool = DatabaseQueryTool()
        result = tool.execute(query="EXPLAIN SELECT 1")
        assert result.success is True

    def test_max_rows_limit(self, tmp_path):
        """Create a table with many rows and verify max_rows is honored."""
        db_file = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE numbers (n INTEGER)")
        for i in range(50):
            conn.execute("INSERT INTO numbers VALUES (?)", (i,))
        conn.commit()
        conn.close()

        tool = DatabaseQueryTool()
        result = tool.execute(
            query="SELECT n FROM numbers",
            db_path=str(db_file),
            max_rows=10,
            read_only=True,
        )
        assert result.success is True
        assert result.metadata["row_count"] == 10

    def test_db_path_to_file(self, tmp_path):
        """Test querying a real SQLite file."""
        db_file = tmp_path / "mydata.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO items VALUES (1, 'apple')")
        conn.execute("INSERT INTO items VALUES (2, 'banana')")
        conn.commit()
        conn.close()

        tool = DatabaseQueryTool()
        result = tool.execute(
            query="SELECT * FROM items ORDER BY id",
            db_path=str(db_file),
        )
        assert result.success is True
        assert "apple" in result.content
        assert "banana" in result.content
        assert result.metadata["row_count"] == 2
        assert result.metadata["column_names"] == ["id", "name"]
        assert result.metadata["db_type"] == "sqlite"

    def test_blocks_sensitive_db_paths(self, tmp_path):
        """Sensitive file patterns (e.g. .env) should be blocked."""
        f = tmp_path / ".env"
        f.write_text("SECRET=foo", encoding="utf-8")

        tool = DatabaseQueryTool()
        result = tool.execute(
            query="SELECT 1",
            db_path=str(f),
        )
        assert result.success is False
        assert "sensitive" in result.content.lower()

    def test_blocks_pem_db_path(self, tmp_path):
        """Sensitive file patterns (.pem) should be blocked."""
        f = tmp_path / "server.pem"
        f.write_text("data", encoding="utf-8")

        tool = DatabaseQueryTool()
        result = tool.execute(
            query="SELECT 1",
            db_path=str(f),
        )
        assert result.success is False
        assert "sensitive" in result.content.lower()

    def test_with_select_allowed(self):
        """WITH ... SELECT (CTE) should be allowed in read-only mode."""
        tool = DatabaseQueryTool()
        result = tool.execute(
            query="WITH cte AS (SELECT 1 AS x) SELECT x FROM cte",
        )
        assert result.success is True
        assert "x" in result.content
        assert "1" in result.content

    def test_with_insert_blocked(self):
        """WITH ... INSERT should be blocked in read-only mode."""
        tool = DatabaseQueryTool()
        result = tool.execute(
            query="WITH cte AS (SELECT 1) INSERT INTO t SELECT * FROM cte",
        )
        assert result.success is False

    def test_format_output_has_column_headers(self):
        """Verify pipe-delimited table format with column headers."""
        tool = DatabaseQueryTool()
        result = tool.execute(
            query="SELECT 42 AS answer, 'test' AS label",
        )
        assert result.success is True
        lines = result.content.strip().split("\n")
        # First line: column headers
        assert "answer" in lines[0]
        assert "label" in lines[0]
        # Second line: separator
        assert "-" in lines[1]
        # Third line: data row
        assert "42" in lines[2]
        assert "test" in lines[2]

    def test_postgresql_url_without_psycopg2_gives_helpful_error(self):
        """When db_url is provided but psycopg2 is not installed,
        the tool should return a helpful error message."""
        tool = DatabaseQueryTool()
        result = tool.execute(
            query="SELECT 1",
            db_url="postgresql://user:pass@localhost/testdb",
        )
        # psycopg2 is not installed in the test environment
        # so we expect a helpful error
        assert result.success is False
        assert "psycopg2" in result.content
        assert "pip install" in result.content

    def test_read_only_false_allows_write(self, tmp_path):
        """When read_only=False, write queries should be allowed."""
        db_file = tmp_path / "writable.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE data (id INTEGER)")
        conn.commit()
        conn.close()

        tool = DatabaseQueryTool()
        result = tool.execute(
            query="INSERT INTO data VALUES (42)",
            db_path=str(db_file),
            read_only=False,
        )
        assert result.success is True

        # Verify the insert actually worked
        result2 = tool.execute(
            query="SELECT id FROM data",
            db_path=str(db_file),
        )
        assert result2.success is True
        assert "42" in result2.content

    def test_sql_error_returns_failure(self):
        """Invalid SQL should return a failure result, not raise."""
        tool = DatabaseQueryTool()
        result = tool.execute(query="SELECT * FROM nonexistent_table_xyz")
        assert result.success is False
        assert "error" in result.content.lower()

    def test_nonexistent_db_file(self):
        """Opening a non-existent file in read-only mode should fail."""
        tool = DatabaseQueryTool()
        result = tool.execute(
            query="SELECT 1",
            db_path="/tmp/this_does_not_exist_12345.db",
            read_only=True,
        )
        assert result.success is False

    def test_tool_id(self):
        tool = DatabaseQueryTool()
        assert tool.tool_id == "db_query"

    def test_openai_function_format(self):
        tool = DatabaseQueryTool()
        fn = tool.to_openai_function()
        assert fn["function"]["name"] == "db_query"
        assert "query" in fn["function"]["parameters"]["properties"]
        assert "db_path" in fn["function"]["parameters"]["properties"]
        assert "db_url" in fn["function"]["parameters"]["properties"]
        assert "read_only" in fn["function"]["parameters"]["properties"]
        assert "max_rows" in fn["function"]["parameters"]["properties"]

    def test_multiple_columns_alignment(self, tmp_path):
        """Verify the pipe-delimited format aligns columns properly."""
        db_file = tmp_path / "align.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE t (short TEXT, longer_column TEXT)")
        conn.execute("INSERT INTO t VALUES ('a', 'xyz')")
        conn.commit()
        conn.close()

        tool = DatabaseQueryTool()
        result = tool.execute(
            query="SELECT * FROM t",
            db_path=str(db_file),
        )
        assert result.success is True
        # Check pipe delimiters are present
        assert "|" in result.content
        assert "short" in result.content
        assert "longer_column" in result.content
