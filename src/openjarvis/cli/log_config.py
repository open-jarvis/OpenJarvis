"""Global logging configuration for the OpenJarvis CLI."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, Union

from openjarvis.security.credential_stripper import CredentialStripper

_stripper = CredentialStripper()


class SanitizingFormatter(logging.Formatter):
    """Formatter that redacts credentials from log messages."""

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        return _stripper.strip(msg)


def setup_logging(
    verbose: bool = False,
    quiet: bool = False,
    log_file: Optional[Union[str, Path]] = None,
) -> logging.Logger:
    """Configure the ``openjarvis`` logger.

    Parameters
    ----------
    verbose:
        Set log level to DEBUG.
    quiet:
        Set log level to ERROR (overrides verbose if both set).
    log_file:
        Path for a rotating file handler.  When *verbose* is ``True``
        and no *log_file* is given, defaults to
        ``~/.openjarvis/cli.log``.

    Returns
    -------
    The configured ``openjarvis`` logger.
    """
    logger = logging.getLogger("openjarvis")

    # Clear existing handlers to avoid duplication across calls
    logger.handlers.clear()

    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.WARNING

    logger.setLevel(level)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    fmt = SanitizingFormatter("%(levelname)s %(name)s: %(message)s")
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    # File handler (verbose or explicit path)
    if verbose or log_file is not None:
        if log_file is None:
            from openjarvis.security.file_utils import secure_mkdir

            log_dir = Path.home() / ".openjarvis"
            secure_mkdir(log_dir)
            log_file = log_dir / "cli.log"
        file_handler = RotatingFileHandler(
            str(log_file),
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
        )
        file_handler.setLevel(logging.DEBUG)
        file_fmt = SanitizingFormatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"
        )
        file_handler.setFormatter(file_fmt)
        logger.addHandler(file_handler)

    return logger
