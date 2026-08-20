"""Shared fixtures for server route tests.

Server tests build apps via ``create_app``, which (with traces enabled by
default) wires a ``TraceStore`` at the real ``~/.openjarvis/traces.db``. Now
that the chat endpoints actually *write* traces, an unguarded run would
pollute the developer's real trace DB and make tests non-hermetic. This
autouse fixture redirects the traces DB to a per-test temp path.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_traces_db(tmp_path, monkeypatch):
    """Point ``config.traces.db_path`` at a temp file for every server test.

    ``load_config`` returns a fresh ``JarvisConfig`` per call (no caching), so
    wrapping it to rewrite ``traces.db_path`` only affects calls made during
    the test — there is no global leak.
    """
    from openjarvis.core import config as _config

    real_load_config = _config.load_config
    db_path = str(tmp_path / "traces.db")

    def _patched_load_config(*args, **kwargs):
        cfg = real_load_config(*args, **kwargs)
        cfg.traces.db_path = db_path
        return cfg

    monkeypatch.setattr(_config, "load_config", _patched_load_config)
    return db_path
