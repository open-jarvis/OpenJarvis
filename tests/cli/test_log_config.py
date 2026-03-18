"""Tests for CLI log configuration."""

from __future__ import annotations

import logging

from openjarvis.cli.log_config import setup_logging


class TestSetupLogging:
    def test_default_level_is_warning(self):
        logger = setup_logging(verbose=False, quiet=False)
        assert logger.level == logging.WARNING

    def test_verbose_sets_debug(self):
        logger = setup_logging(verbose=True, quiet=False)
        assert logger.level == logging.DEBUG

    def test_quiet_sets_error(self):
        logger = setup_logging(verbose=False, quiet=True)
        assert logger.level == logging.ERROR

    def test_returns_logger(self):
        logger = setup_logging(verbose=False, quiet=False)
        assert isinstance(logger, logging.Logger)
        assert logger.name == "openjarvis"

    def test_log_file_handler_on_verbose(self, tmp_path):
        log_file = tmp_path / "cli.log"
        logger = setup_logging(verbose=True, quiet=False, log_file=log_file)
        # Should have at least one file handler
        file_handlers = [h for h in logger.handlers if hasattr(h, "baseFilename")]
        assert len(file_handlers) >= 1
        # Clean up
        for h in logger.handlers[:]:
            logger.removeHandler(h)
            h.close()
