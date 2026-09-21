"""Tests for the Docker-sandboxed code interpreter tool."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch


def _make_docker_mock():
    """Create a mock docker module and return (mock_module, mock_client)."""
    mock_docker = MagicMock()
    mock_client = MagicMock()
    mock_docker.from_env.return_value = mock_client
    return mock_docker, mock_client


class TestDockerCodeInterpreterTool:
    def test_spec(self):
        from openjarvis.tools.code_interpreter_docker import (
            DockerCodeInterpreterTool,
        )

        tool = DockerCodeInterpreterTool()
        spec = tool.spec
        assert spec.name == "code_interpreter_docker"
        assert "code" in spec.parameters["properties"]
        assert spec.category == "code"
        assert spec.metadata["structured_allow_object_text"] is True

    def test_empty_code(self):
        from openjarvis.tools.code_interpreter_docker import (
            DockerCodeInterpreterTool,
        )

        tool = DockerCodeInterpreterTool()
        result = tool.execute(code="")
        assert not result.success
        assert "No code" in result.content

    def test_successful_execution(self):
        from openjarvis.tools.code_interpreter_docker import (
            DockerCodeInterpreterTool,
        )

        mock_docker, mock_client = _make_docker_mock()

        mock_container = MagicMock()
        mock_container.wait.return_value = {"StatusCode": 0}
        mock_container.logs.side_effect = [
            b"Hello World\n",  # stdout
            b"",  # stderr
        ]
        mock_client.containers.run.return_value = mock_container

        with patch.dict(sys.modules, {"docker": mock_docker}):
            tool = DockerCodeInterpreterTool()
            result = tool.execute(code="print('Hello World')")

        assert result.success
        assert "Hello World" in result.content
        mock_container.remove.assert_called_once_with(force=True)

    def test_execution_error(self):
        from openjarvis.tools.code_interpreter_docker import (
            DockerCodeInterpreterTool,
        )

        mock_docker, mock_client = _make_docker_mock()

        mock_container = MagicMock()
        mock_container.wait.return_value = {"StatusCode": 1}
        mock_container.logs.side_effect = [
            b"",
            b"NameError: name 'foo' is not defined\n",
        ]
        mock_client.containers.run.return_value = mock_container

        with patch.dict(sys.modules, {"docker": mock_docker}):
            tool = DockerCodeInterpreterTool()
            result = tool.execute(code="print(foo)")

        assert not result.success
        assert "NameError" in result.content

    def test_container_resource_limits(self):
        from openjarvis.tools.code_interpreter_docker import (
            DockerCodeInterpreterTool,
        )

        mock_docker, mock_client = _make_docker_mock()

        mock_container = MagicMock()
        mock_container.wait.return_value = {"StatusCode": 0}
        mock_container.logs.side_effect = [b"ok\n", b""]
        mock_client.containers.run.return_value = mock_container

        tool = DockerCodeInterpreterTool(
            memory_limit="256m",
            cpu_count=2,
            network_disabled=True,
            pids_limit=50,
        )

        with patch.dict(sys.modules, {"docker": mock_docker}):
            tool.execute(code="print('ok')")

        call_kwargs = mock_client.containers.run.call_args
        assert call_kwargs[1]["mem_limit"] == "256m"
        assert call_kwargs[1]["nano_cpus"] == 2 * 10**9
        assert call_kwargs[1]["network_disabled"] is True
        assert call_kwargs[1]["pids_limit"] == 50
        assert call_kwargs[1]["read_only"] is True

    def test_output_truncation(self):
        from openjarvis.tools.code_interpreter_docker import (
            DockerCodeInterpreterTool,
        )

        mock_docker, mock_client = _make_docker_mock()

        mock_container = MagicMock()
        mock_container.wait.return_value = {"StatusCode": 0}
        mock_container.logs.side_effect = [b"x" * 20000, b""]
        mock_client.containers.run.return_value = mock_container

        with patch.dict(sys.modules, {"docker": mock_docker}):
            tool = DockerCodeInterpreterTool(max_output=100)
            result = tool.execute(code="print('x' * 20000)")

        assert result.success
        assert len(result.content) < 200
        assert "truncated" in result.content

    def test_container_cleanup_on_error(self):
        from openjarvis.tools.code_interpreter_docker import (
            DockerCodeInterpreterTool,
        )

        mock_docker, mock_client = _make_docker_mock()

        mock_container = MagicMock()
        mock_container.wait.side_effect = Exception("timeout")
        mock_client.containers.run.return_value = mock_container

        with patch.dict(sys.modules, {"docker": mock_docker}):
            tool = DockerCodeInterpreterTool()
            result = tool.execute(code="import time; time.sleep(999)")

        assert not result.success
        mock_container.remove.assert_called_once_with(force=True)
