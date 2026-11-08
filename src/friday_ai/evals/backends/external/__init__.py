"""External-framework subprocess backends (Hermes Agent, OpenClaw)."""

from friday_ai.evals.backends.external.hermes_agent import HermesBackend
from friday_ai.evals.backends.external.openclaw import OpenClawBackend

__all__ = ["HermesBackend", "OpenClawBackend"]
