"""Windows must get a clear answer, not a missing-systemctl traceback."""

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
