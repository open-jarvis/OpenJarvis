"""Backward-compat shim -- canonical location is agents.native_react."""

from openjarvis.agents.native_react import NativeReActAgent as ReActAgent  # noqa: F401
from openjarvis.agents.native_react import REACT_SYSTEM_PROMPT  # noqa: F401

__all__ = ["ReActAgent", "REACT_SYSTEM_PROMPT"]
