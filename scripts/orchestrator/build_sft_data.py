#!/usr/bin/env python
"""Thin CLI wrapper: build the orchestrator SFT dataset from NeuLab ADP.

Equivalent to::

    python -m openjarvis.learning.intelligence.orchestrator.sft_data.build [...]

Usage:
    python scripts/orchestrator/build_sft_data.py \
        --out data/orchestrator_sft_traces.jsonl \
        --max-tasks 2000 --adp-configs codeactinstruct,code_feedback,openhands
"""

from __future__ import annotations

from openjarvis.learning.intelligence.orchestrator.sft_data.build import _main

if __name__ == "__main__":
    raise SystemExit(_main())
