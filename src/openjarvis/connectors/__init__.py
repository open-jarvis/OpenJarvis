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

try:
    import openjarvis.connectors.gmail  # noqa: F401
except ImportError:
    pass  # httpx may not be installed

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
    import openjarvis.connectors.dropbox  # noqa: F401
except ImportError:
    pass  # httpx may not be installed
