#!/usr/bin/env python3
"""Compatibility wrapper for Pearl model conversion tooling.

The implementation lives in ``scripts/pearl/model_converter.py``.
"""

from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(
        str(Path(__file__).parents[1] / "pearl" / "model_converter.py"),
        run_name="__main__",
    )
