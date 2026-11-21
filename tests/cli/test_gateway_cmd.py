"""The gateway CLI must not pretend to run a daemon that does not exist."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from openjarvis.cli.gateway_cmd import gateway


@pytest.mark.parametrize(
    ("argv", "needs_install"),
    [
        (["status"], False),
        (["stop"], False),
        (["logs"], False),
        (["start", "--install"], True),
    ],
)
def test_service_commands_are_unsupported_on_windows(argv, needs_install):
    with patch(
        "openjarvis.cli.gateway_cmd.platform.system", return_value="Windows"
    ):
        result = CliRunner().invoke(gateway, argv)

    assert result.exit_code == 1
    assert "not available on Windows" in result.output
    assert "Traceback" not in result.output


def test_foreground_start_explains_the_real_entrypoint():
    """`gateway start` used to print "started" and exit without a daemon."""
    result = CliRunner().invoke(gateway, ["start"])

    assert result.exit_code == 1
    assert "not implemented" in result.output
    assert "jarvis serve" in result.output
    assert "Gateway started" not in result.output
