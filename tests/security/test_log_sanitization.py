"""Tests for log sanitization (Section 5)."""

from __future__ import annotations

import logging


class TestSanitizingFormatter:
    """SanitizingFormatter should redact secrets in log messages."""

    def test_redacts_openai_key(self) -> None:
        from openjarvis.cli.log_config import SanitizingFormatter

        fmt = SanitizingFormatter("%(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Key is sk-proj-abc123def456ghi789jkl012mno345pqr678stu",
            args=(),
            exc_info=None,
        )
        result = fmt.format(record)
        assert "sk-proj-" not in result
        assert "[REDACTED" in result

    def test_redacts_aws_key(self) -> None:
        from openjarvis.cli.log_config import SanitizingFormatter

        fmt = SanitizingFormatter("%(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="AWS: AKIAIOSFODNN7EXAMPLE",
            args=(),
            exc_info=None,
        )
        result = fmt.format(record)
        assert "AKIAIOSFODNN7EXAMPLE" not in result

    def test_clean_message_unchanged(self) -> None:
        from openjarvis.cli.log_config import SanitizingFormatter

        fmt = SanitizingFormatter("%(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Server started on port 8000",
            args=(),
            exc_info=None,
        )
        result = fmt.format(record)
        assert result == "Server started on port 8000"

    def test_redacts_slack_token(self) -> None:
        from openjarvis.cli.log_config import SanitizingFormatter

        fmt = SanitizingFormatter("%(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Token: xoxb-1234-5678-abcdefghij",
            args=(),
            exc_info=None,
        )
        result = fmt.format(record)
        assert "xoxb-" not in result
