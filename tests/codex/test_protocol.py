from __future__ import annotations

from openjarvis.codex import BackendCapabilities


def test_capability_matrix_is_complete_and_serializable() -> None:
    matrix = BackendCapabilities(
        persistent_threads=True,
        resume=True,
        fork=True,
        streaming=True,
        steer=True,
        interrupt=True,
        command_approvals=False,
        file_approvals=False,
        full_item_events=True,
        usage_events=True,
        read_only=True,
        workspace_write=True,
    )

    assert matrix.as_dict() == {
        "persistent_threads": True,
        "resume": True,
        "fork": True,
        "streaming": True,
        "steer": True,
        "interrupt": True,
        "command_approvals": False,
        "file_approvals": False,
        "full_item_events": True,
        "usage_events": True,
        "read_only": True,
        "workspace_write": True,
    }
