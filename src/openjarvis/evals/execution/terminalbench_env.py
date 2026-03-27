"""TerminalBench task environment — per-task Docker lifecycle + test execution."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from types import TracebackType
from typing import Any, MutableMapping, Optional, Type

LOGGER = logging.getLogger(__name__)


class TerminalBenchTaskEnv:
    """Per-task Docker environment for TerminalBench.

    Context manager that spins up a Docker container, creates a tmux session,
    and runs test scripts after the agent finishes.
    """

    def __init__(self, metadata: MutableMapping[str, Any]) -> None:
        self._metadata = metadata
        self._terminal: Any = None
        self._terminal_cm: Any = None
        self._logs_tmpdir: Any = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> TerminalBenchTaskEnv:
        from terminal_bench.terminal.terminal import spin_up_terminal

        task = self._metadata.get("task")
        task_paths = self._metadata.get("task_paths")
        task_id = self._metadata.get("task_id", "unknown")

        if task is None or task_paths is None:
            raise ValueError(
                "Task metadata missing 'task' or 'task_paths'. "
                "Use the 'terminalbench-native' dataset."
            )

        docker_image_prefix = f"tb__{task_id}".replace(".", "-")
        client_image_name = f"{docker_image_prefix}__client"
        client_container_name = f"oj-{task_id}".replace(".", "-")

        self._logs_tmpdir = tempfile.TemporaryDirectory(prefix="oj_tb_logs_")
        logs_path = Path(self._logs_tmpdir.name)

        self._terminal_cm = spin_up_terminal(
            client_container_name=client_container_name,
            client_image_name=client_image_name,
            docker_compose_path=task_paths.docker_compose_path,
            docker_image_name_prefix=docker_image_prefix,
            sessions_logs_path=logs_path,
            disable_recording=task.disable_asciinema,
        )
        self._terminal = self._terminal_cm.__enter__()

        session = self._terminal.create_session(
            "agent", is_active_stream=False, as_configured_user=True
        )

        self._metadata["terminal"] = self._terminal
        self._metadata["session"] = session
        self._metadata["container"] = client_container_name

        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        self._metadata.pop("terminal", None)
        self._metadata.pop("session", None)
        self._metadata.pop("container", None)

        if self._terminal_cm is not None:
            self._terminal_cm.__exit__(exc_type, exc_val, exc_tb)
            self._terminal_cm = None
            self._terminal = None

        if self._logs_tmpdir is not None:
            self._logs_tmpdir.cleanup()
            self._logs_tmpdir = None

    # ------------------------------------------------------------------
    # Test execution
    # ------------------------------------------------------------------

    def run_tests(self) -> tuple[bool, dict[str, Any]]:
        """Copy test scripts into container, execute, parse results."""
        from terminal_bench.parsers.base_parser import UnitTestStatus
        from terminal_bench.parsers.parser_factory import ParserFactory
        from terminal_bench.terminal.docker_compose_manager import (
            DockerComposeManager,
        )

        task = self._metadata["task"]
        task_paths = self._metadata["task_paths"]
        terminal = self._terminal
        results: dict[str, Any] = {}

        if terminal is None:
            results["error"] = "terminal_not_running"
            self._metadata["is_resolved"] = False
            self._metadata["test_results"] = results
            return False, results

        try:
            paths_to_copy = [task_paths.run_tests_path]
            if task_paths.test_dir.exists():
                paths_to_copy.append(task_paths.test_dir)

            terminal.copy_to_container(
                paths=paths_to_copy,
                container_dir=str(DockerComposeManager.CONTAINER_TEST_DIR),
            )

            if not task.run_tests_in_same_shell:
                test_session = terminal.create_session(
                    "tests", is_active_stream=False, as_configured_user=False
                )
            else:
                test_session = terminal.create_session(
                    "agent-tests",
                    is_active_stream=False,
                    as_configured_user=True,
                )

            test_timeout = task.max_test_timeout_sec
            test_script_path = (
                DockerComposeManager.CONTAINER_TEST_DIR / task_paths.run_tests_path.name
            )

            try:
                test_session.send_keys(
                    ["bash ", str(test_script_path), "Enter"],
                    block=True,
                    max_timeout_sec=test_timeout,
                )
            except TimeoutError:
                LOGGER.warning("Test command timed out after %.0fs", test_timeout)
                results["error"] = "test_timeout"
                self._metadata["is_resolved"] = False
                self._metadata["test_results"] = results
                return False, results

            post_test_pane = test_session.capture_pane(capture_entire=True)
            results["test_output"] = post_test_pane[:10000]

            parser = ParserFactory.get_parser(task.parser_name)
            try:
                parser_results = parser.parse(post_test_pane)
                results["parser_results"] = {
                    name: status.value for name, status in parser_results.items()
                }
                is_resolved = all(
                    status == UnitTestStatus.PASSED
                    for status in parser_results.values()
                )
            except Exception as exc:
                LOGGER.warning("Parser failed: %s", exc)
                results["parse_error"] = str(exc)
                is_resolved = False

            results["is_resolved"] = is_resolved
            self._metadata["is_resolved"] = is_resolved
            self._metadata["test_results"] = results
            return is_resolved, results

        except Exception as exc:
            LOGGER.exception("Test execution failed")
            results["error"] = str(exc)
            self._metadata["is_resolved"] = False
            self._metadata["test_results"] = results
            return False, results


__all__ = ["TerminalBenchTaskEnv"]
