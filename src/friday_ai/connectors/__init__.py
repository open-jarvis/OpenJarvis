"""Data source connectors for Deep Research."""

from friday_ai.connectors._stubs import (
    Attachment,
    BaseConnector,
    Document,
    SyncStatus,
)
from friday_ai.connectors.store import KnowledgeStore

__all__ = ["Attachment", "BaseConnector", "Document", "KnowledgeStore", "SyncStatus"]

# Auto-register built-in connectors
import friday_ai.connectors.obsidian  # noqa: F401

try:
    import friday_ai.connectors.gmail  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.connectors.gmail_imap  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.connectors.gdrive  # noqa: F401
except ImportError:
    pass  # httpx may not be installed

try:
    import friday_ai.connectors.notion  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.connectors.granola  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.connectors.gcontacts  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.connectors.imessage  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.connectors.apple_notes  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.connectors.apple_music  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.connectors.apple_contacts  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.connectors.apple_calendar  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.connectors.slack_connector  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.connectors.outlook  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.connectors.imap  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.connectors.gcalendar  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.connectors.dropbox  # noqa: F401
except ImportError:
    pass  # httpx may not be installed

try:
    import friday_ai.connectors.whatsapp  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.connectors.oura  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.connectors.apple_health  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.connectors.strava  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.connectors.spotify  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.connectors.google_tasks  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.connectors.weather  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.connectors.github_notifications  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.connectors.hackernews  # noqa: F401
except ImportError:
    pass

try:
    import friday_ai.connectors.news_rss  # noqa: F401
except ImportError:
    pass
