"""User-identity metadata for upstream services.

Some integrations need to know which account a value belongs to (e.g.
which Anthropic account the API key is associated with, used by the
Claude CLI elaboration path and by audit logs that include sender
identity in outbound emails).

This module is the canonical lookup for non-secret identity fields.
Secrets stay in env vars; identity (email addresses, account names) is
read here so call sites have a single import path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True, slots=True)
class IdentityProfile:
    anthropic_email: Optional[str] = None
    smtp_user: Optional[str] = None


def load_profile() -> IdentityProfile:
    """Read the current identity from env (called fresh each request).

    Cheap and pure; no caching so updates to env vars take effect on
    the next call without a restart.
    """
    return IdentityProfile(
        anthropic_email=os.environ.get("ANTHROPIC_EMAIL") or None,
        smtp_user=os.environ.get("SMTP_USER") or None,
    )


def anthropic_email() -> Optional[str]:
    """Convenience accessor for the Anthropic-account email address."""
    return os.environ.get("ANTHROPIC_EMAIL") or None


__all__ = ["IdentityProfile", "anthropic_email", "load_profile"]
