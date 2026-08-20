"""TerminalBench task environment — per-task Docker lifecycle + test execution."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from types import TracebackType
from typing import Any, MutableMapping, Optional, Type

from openjarvis.evals.core.environment import TaskEnvironmentError

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
        task = self._metadata.get("task")
        task_paths = self._metadata.get("task_paths")
        task_id = self._metadata.get("task_id", "unknown")

        if task is None or task_paths is None:
            raise ValueError(
                "Task metadata missing 'task' or 'task_paths'. "
                "Use the 'terminalbench-native' dataset."
            )

        from terminal_bench.terminal.terminal import spin_up_terminal

        docker_image_prefix = f"tb__{task_id}".replace(".", "-")
        client_image_name = f"{docker_image_prefix}__client"
        client_container_name = f"oj-{task_id}".replace(".", "-")

        self._logs_tmpdir = tempfile.TemporaryDirectory(prefix="oj_tb_logs_")
        logs_path = Path(self._logs_tmpdir.name)

        # Everything below is exception-safe: a failure mid-startup (docker
        # compose, tmux, asciinema) tears the spun-up terminal back down
        # immediately instead of leaking the docker compose project until GC
        # (or forever, when the env object is retained), and re-raises as a
        # loud TaskEnvironmentError naming the task image so the runner can
        # record a harness error for THIS task and continue with the rest.
        try:
            self._terminal_cm = spin_up_terminal(
                client_container_name=client_container_name,
                client_image_name=client_image_name,
                docker_compose_path=task_paths.docker_compose_path,
                docker_image_name_prefix=docker_image_prefix,
                sessions_logs_path=logs_path,
                disable_recording=task.disable_asciinema,
            )
            self._terminal = self._terminal_cm.__enter__()

            # Preflight BEFORE the agent loop: terminal-bench drives the
            # agent through tmux (and records via asciinema unless the task
            # disables it). A missing binary otherwise surfaces mid-run as
            # an opaque RuntimeError or a fake TimeoutError.
            self._preflight_container_binaries(
                task, task_id, client_image_name, client_container_name
            )

            session = self._terminal.create_session(
                "agent", is_active_stream=False, as_configured_user=True
            )
        except BaseException as exc:
            self._teardown(type(exc), exc, exc.__traceback__)
            if not isinstance(exc, Exception):
                # KeyboardInterrupt / SystemExit: clean up but never mask.
                raise
            if isinstance(exc, TaskEnvironmentError):
                self._metadata["harness_error"] = str(exc)
                raise
            message = (
                f"Task '{task_id}': failed to start the task environment "
                f"(image '{client_image_name}', container "
                f"'{client_container_name}'): {exc}. This is a harness/"
                "environment failure, not a model failure. Check that the "
                "Docker daemon is healthy and that tmux is installed in the "
                "task image."
            )
            # docker compose stderr is only logged at DEBUG by
            # terminal-bench; surface it here so the failure is actionable.
            stderr = getattr(exc, "stderr", None)
            if stderr:
                if isinstance(stderr, bytes):
                    stderr = stderr.decode("utf-8", errors="replace")
                message += f"\ndocker compose stderr (tail):\n{stderr[-2000:]}"
            self._metadata["harness_error"] = message
            raise TaskEnvironmentError(message) from exc

        self._metadata["terminal"] = self._terminal
        self._metadata["session"] = session
        self._metadata["container"] = client_container_name

        return self

    def _preflight_container_binaries(
        self,
        task: Any,
        task_id: str,
        client_image_name: str,
        client_container_name: str,
    ) -> None:
        """Verify tmux (and asciinema if recording) exist in the container.

        Raises:
            TaskEnvironmentError: naming the task image and the missing
                binary, with the remedy, before any agent work starts.
        """
        container = getattr(self._terminal, "container", None)
        if container is None:
            # Terminal implementation without a container handle (e.g. a
            # future terminal-bench version); fall through to terminal-bench's
            # own checks rather than guessing.
            return

        checks: list[tuple[str, list[str], str]] = [
            (
                "tmux",
                ["tmux", "-V"],
                f"install tmux in the task image '{client_image_name}'",
            ),
        ]
        if not getattr(task, "disable_asciinema", False):
            checks.append(
                (
                    "asciinema",
                    ["asciinema", "--version"],
                    f"install asciinema in the task image '{client_image_name}' "
                    "or set disable_asciinema in task.yaml",
                )
            )

        for binary, cmd, remedy in checks:
            result = container.exec_run(cmd)
            exit_code = getattr(result, "exit_code", 0)
            if exit_code == 0:
                continue
            output = getattr(result, "output", b"")
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="replace")
            raise TaskEnvironmentError(
                f"Task '{task_id}': required binary '{binary}' is not usable "
                f"in task image '{client_image_name}' (container "
                f"'{client_container_name}'): exec exit code {exit_code}, "
                f"output {str(output).strip()!r}. Remedy: {remedy}. This is "
                "a harness/environment failure, not a model failure."
            )

    def _teardown(
        self,
        exc_type: Optional[Type[BaseException]] = None,
        exc_val: Optional[BaseException] = None,
        exc_tb: Optional[TracebackType] = None,
    ) -> None:
        """Idempotent cleanup shared by ``__exit__`` and failed ``__enter__``.

        Secondary cleanup errors are logged, never raised, so they cannot
        mask the original failure.
        """
        self._metadata.pop("terminal", None)
        self._metadata.pop("session", None)
        self._metadata.pop("container", None)

        terminal_cm, self._terminal_cm, self._terminal = self._terminal_cm, None, None
        if terminal_cm is not None:
            try:
                terminal_cm.__exit__(exc_type, exc_val, exc_tb)
            except Exception:
                LOGGER.exception(
                    "Secondary error while tearing down the terminal for "
                    "task %s (original error, if any, is re-raised)",
                    self._metadata.get("task_id", "unknown"),
                )

        logs_tmpdir, self._logs_tmpdir = self._logs_tmpdir, None
        if logs_tmpdir is not None:
            try:
                logs_tmpdir.cleanup()
            except Exception:
                LOGGER.exception("Failed to clean up session logs tmpdir")

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        self._teardown(exc_type, exc_val, exc_tb)

    # ------------------------------------------------------------------
    # Test execution
    # ------------------------------------------------------------------

    def run_tests(self) -> tuple[bool, dict[str, Any]]:
        """Copy test scripts into container, execute, parse results."""
        task = self._metadata["task"]
        task_paths = self._metadata["task_paths"]
        terminal = self._terminal
        results: dict[str, Any] = {}

        if terminal is None:
            results["error"] = "terminal_not_running"
            self._metadata["is_resolved"] = False
            self._metadata["test_results"] = results
            return False, results

        from terminal_bench.parsers.base_parser import UnitTestStatus
        from terminal_bench.parsers.parser_factory import ParserFactory
        from terminal_bench.terminal.docker_compose_manager import (
            DockerComposeManager,
        )

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
