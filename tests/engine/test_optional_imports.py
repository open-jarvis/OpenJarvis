"""Diagnostics for optional inference-engine imports."""

from __future__ import annotations

import logging
from unittest import mock


def test_optional_engine_import_errors_are_logged(caplog) -> None:
    import openjarvis.engine as engine_module

    caplog.set_level(logging.DEBUG, logger="openjarvis.engine")
    with mock.patch.object(
        engine_module.importlib,
        "import_module",
        side_effect=ImportError("renamed SDK symbol"),
    ):
        engine_module._register_optional_engines()

    assert "Optional engine 'cloud' unavailable: renamed SDK symbol" in caplog.text
    assert "Optional engine 'litellm' unavailable: renamed SDK symbol" in caplog.text
    assert "Optional engine 'gemma_cpp' unavailable: renamed SDK symbol" in caplog.text
