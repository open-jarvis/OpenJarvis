"""Verify that optional import failures emit debug logs."""

from __future__ import annotations

import logging
from unittest.mock import patch


def test_tool_import_error_logs_debug(caplog):
    """When a built-in tool fails to import, a debug message is logged."""
    import openjarvis.tools as tools_pkg

    err_msg = "Simulated missing optional library"
    with caplog.at_level(logging.DEBUG, logger="openjarvis.tools"):
        with patch("importlib.import_module", side_effect=ImportError(err_msg)):
            for mod_name in tools_pkg._BUILTIN_TOOL_MODULES:
                try:
                    importlib = __import__("importlib")
                    importlib.import_module(f"openjarvis.tools.{mod_name}")
                except ImportError as exc:
                    tools_pkg.logger.debug(
                        "Optional tool %s not loaded: %s", mod_name, exc
                    )

    assert any(
        f"Optional tool calculator not loaded: {err_msg}" in record.message
        for record in caplog.records
    )


def test_storage_import_error_logs_debug(caplog):
    """When an optional storage backend fails to import, debug message is logged."""
    import openjarvis.tools.storage as storage_pkg

    err_msg = "Simulated missing faiss"
    with caplog.at_level(logging.DEBUG, logger="openjarvis.tools.storage"):
        with patch("importlib.import_module", side_effect=ImportError(err_msg)):
            for backend in storage_pkg._OPTIONAL_STORAGE_BACKENDS:
                try:
                    importlib = __import__("importlib")
                    importlib.import_module(f"openjarvis.tools.storage.{backend}")
                except ImportError as exc:
                    storage_pkg.logger.debug(
                        "Optional storage backend %s not loaded: %s",
                        backend,
                        exc,
                    )

    assert any(
        f"Optional storage backend faiss_backend not loaded: {err_msg}"
        in record.message
        for record in caplog.records
    )


def test_speech_import_error_logs_debug(caplog):
    """When an optional speech backend fails to import, debug message is logged."""
    import openjarvis.speech as speech_pkg

    err_msg = "Simulated missing whisper"
    with caplog.at_level(logging.DEBUG, logger="openjarvis.speech"):
        with patch("importlib.import_module", side_effect=ImportError(err_msg)):
            for mod in ("faster_whisper", "cartesia_tts"):
                try:
                    importlib = __import__("importlib")
                    importlib.import_module(f".{mod}", speech_pkg.__name__)
                except ImportError as exc:
                    speech_pkg.logger.debug(
                        "Optional STT backend %s not loaded: %s", mod, exc
                    )

    assert any(
        f"Optional STT backend faster_whisper not loaded: {err_msg}" in record.message
        for record in caplog.records
    )
