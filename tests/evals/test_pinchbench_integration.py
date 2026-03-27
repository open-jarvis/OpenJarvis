"""Integration tests for PinchBench eval pipeline.

These tests use synthetic task files to verify the full pipeline
without requiring the actual PinchBench repo or cloud API keys.
"""

import textwrap
from pathlib import Path

from openjarvis.evals.core.event_recorder import EventRecorder, EventType
from openjarvis.evals.datasets.pinchbench import PinchBenchDataset


def _create_test_repo(tmp_path: Path) -> Path:
    """Create a minimal PinchBench repo structure for testing."""
    repo = tmp_path / "skill"
    tasks_dir = repo / "tasks"
    tasks_dir.mkdir(parents=True)
    assets_dir = repo / "assets"
    assets_dir.mkdir()

    # Write a simple automated task
    (tasks_dir / "task_00_sanity.md").write_text(
        textwrap.dedent("""\
    ---
    id: task_00_sanity
    name: Sanity Check
    category: basic
    grading_type: automated
    timeout_seconds: 60
    workspace_files: []
    ---

    ## Prompt

    Write "hello" to a file called output.txt.

    ## Expected Behavior

    A file output.txt exists with the word hello.

    ## Grading Criteria

    - [ ] output.txt exists
    - [ ] Contains hello

    ## Automated Checks

    ```python
    def grade(transcript, workspace_path):
        from pathlib import Path
        f = Path(workspace_path) / "output.txt"
        exists = f.exists()
        has_hello = "hello" in f.read_text().lower() if exists else False
        return {
            "file_exists": 1.0 if exists else 0.0,
            "has_hello": 1.0 if has_hello else 0.0,
        }
    ```
    """)
    )

    return repo


def test_dataset_loads_from_local_path(tmp_path):
    """Dataset loads tasks from a local path."""
    repo = _create_test_repo(tmp_path)
    ds = PinchBenchDataset(path=str(repo))
    ds.load()
    assert ds.size() == 1
    records = list(ds.iter_records())
    assert records[0].record_id == "task_00_sanity"
    assert "hello" in records[0].problem.lower() or "output.txt" in records[0].problem


def test_task_env_creates_workspace(tmp_path):
    """Task env creates and cleans up workspace."""
    repo = _create_test_repo(tmp_path)
    ds = PinchBenchDataset(path=str(repo))
    ds.load()
    record = list(ds.iter_records())[0]

    env = ds.create_task_env(record)
    with env:
        ws = Path(record.metadata["workspace_path"])
        assert ws.exists()
    # After exit, workspace is cleaned up
    assert not ws.exists()


def test_full_grading_pipeline(tmp_path):
    """Full pipeline: workspace setup -> simulate agent -> grade."""
    repo = _create_test_repo(tmp_path)
    ds = PinchBenchDataset(path=str(repo))
    ds.load()
    record = list(ds.iter_records())[0]

    env = ds.create_task_env(record)
    with env:
        ws = Path(record.metadata["workspace_path"])
        # Simulate agent writing the output file
        (ws / "output.txt").write_text("hello world")

        # Simulate EventRecorder with a tool call
        recorder = EventRecorder()
        recorder.record(
            EventType.TOOL_CALL_START,
            tool="file_write",
            arguments={"path": "output.txt", "content": "hello world"},
        )
        recorder.record(
            EventType.TOOL_CALL_END,
            tool="file_write",
            result="ok",
        )
        env.set_event_recorder(recorder)
        env.run_tests()

    assert record.metadata["is_resolved"] is True
    assert record.metadata["pinchbench_score"] == 1.0
    assert record.metadata["pinchbench_breakdown"]["file_exists"] == 1.0
    assert record.metadata["pinchbench_breakdown"]["has_hello"] == 1.0
