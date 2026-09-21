"""Security invariants for atomic private-file persistence."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from openjarvis.security.file_utils import secure_write_json


def test_secure_write_json_is_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "credentials.json"

    secure_write_json(path, {"access_token": "secret"})

    assert json.loads(path.read_text(encoding="utf-8")) == {"access_token": "secret"}
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_secure_write_json_preserves_old_file_when_replace_fails(
    tmp_path: Path,
) -> None:
    path = tmp_path / "credentials.json"
    secure_write_json(path, {"access_token": "old"})

    with (
        patch(
            "openjarvis.security.file_utils.os.replace",
            side_effect=OSError("simulated replace failure"),
        ),
        pytest.raises(OSError, match="simulated replace failure"),
    ):
        secure_write_json(path, {"access_token": "new"})

    assert json.loads(path.read_text(encoding="utf-8")) == {"access_token": "old"}
    assert list(tmp_path.glob(".credentials.json.*.tmp")) == []
