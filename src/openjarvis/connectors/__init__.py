"""Data source connectors for Deep Research."""

from openjarvis.connectors._stubs import (
    Attachment,
    BaseConnector,
    Document,
    SyncStatus,
)
from openjarvis.connectors.store import KnowledgeStore

__all__ = ["Attachment", "BaseConnector", "Document", "KnowledgeStore", "SyncStatus"]

# Auto-register built-in connectors
import openjarvis.connectors.obsidian  # noqa: F401

# gmail (REST API / OAuth) is not registered — use gmail_imap instead.
# The REST API connector requires a full OAuth flow that isn't wired up yet.
try:
    import openjarvis.connectors.gmail_imap  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.connectors.gdrive  # noqa: F401
except ImportError:
    pass  # httpx may not be installed

try:
    import openjarvis.connectors.notion  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.connectors.granola  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.connectors.gcontacts  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.connectors.imessage  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.connectors.apple_notes  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.connectors.apple_music  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.connectors.slack_connector  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.connectors.outlook  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.connectors.gcalendar  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.connectors.dropbox  # noqa: F401
except ImportError:
    pass  # httpx may not be installed

try:
    import openjarvis.connectors.whatsapp  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.connectors.oura  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.connectors.apple_health  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.connectors.strava  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.connectors.spotify  # noqa: F401
except ImportError:
    pass

try:
    import openjarvis.connectors.google_tasks  # noqa: F401
except ImportError:
    pass
