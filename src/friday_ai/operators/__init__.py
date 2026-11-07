"""Operators — persistent, scheduled autonomous agents."""

from friday_ai.operators.loader import load_operator
from friday_ai.operators.manager import OperatorManager
from friday_ai.operators.types import OperatorManifest

__all__ = ["OperatorManifest", "OperatorManager", "load_operator"]
