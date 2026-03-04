"""External experiment trackers for the eval framework.

Trackers are lazily imported to avoid mandatory dependencies on wandb/gspread.
"""

from __future__ import annotations


def WandbTracker(*args, **kwargs):  # noqa: N802
    """Lazy constructor — imports the real class on first use."""
    from openjarvis.evals.trackers.wandb_tracker import WandbTracker as _Cls

    return _Cls(*args, **kwargs)


def SheetsTracker(*args, **kwargs):  # noqa: N802
    """Lazy constructor — imports the real class on first use."""
    from openjarvis.evals.trackers.sheets_tracker import SheetsTracker as _Cls

    return _Cls(*args, **kwargs)


__all__ = ["WandbTracker", "SheetsTracker"]
