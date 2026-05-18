"""External-framework subprocess backends (Hermes Agent, OpenClaw)."""

from openjarvis.evals.backends.external.hermes_agent import HermesBackend
from openjarvis.evals.backends.external.openclaw import OpenClawBackend

__all__ = ["HermesBackend", "OpenClawBackend"]
