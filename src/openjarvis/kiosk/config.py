"""Kiosk configuration — pure data, no logic."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class KioskConfig:
    """Debounce, timing, and threshold parameters for the kiosk FSM.

    All time values are in seconds. All distance values are in meters.
    """

    approach_threshold_m: float = 1.0
    approach_entry_debounce: float = 0.4      # 2 ticks at 5 Hz
    approach_sustain_seconds: float = 2.0
    leave_sustain_seconds_prompting: float = 5.0
    leave_sustain_seconds_active: float = 10.0
    session_max_seconds: float = 600.0        # 10 minutes
    session_warning_seconds: float = 540.0    # 9 minutes
    popup_timeout: float = 30.0               # auto-dismiss consent popup
    decline_cooldown_seconds: float = 10.0    # ignore person after decline
