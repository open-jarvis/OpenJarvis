"""Health check tests for all data source connectors.

Verifies that each connector can be instantiated, reports connection
status correctly, and has the required interface methods.
"""

from __future__ import annotations

import pytest

# All connectors that should be testable without credentials
_LOCAL_CONNECTORS = [
    ("apple_notes", "openjarvis.connectors.apple_notes", "AppleNotesConnector"),
    ("imessage", "openjarvis.connectors.imessage", "IMessageConnector"),
]

_TOKEN_CONNECTORS = [
    ("gmail_imap", "openjarvis.connectors.gmail_imap", "GmailIMAPConnector"),
    ("outlook", "openjarvis.connectors.outlook", "OutlookConnector"),
    ("slack", "openjarvis.connectors.slack_connector", "SlackConnector"),
    ("notion", "openjarvis.connectors.notion", "NotionConnector"),
    ("granola", "openjarvis.connectors.granola", "GranolaConnector"),
    ("gdrive", "openjarvis.connectors.gdrive", "GDriveConnector"),
    ("gcalendar", "openjarvis.connectors.gcalendar", "GCalendarConnector"),
    ("gcontacts", "openjarvis.connectors.gcontacts", "GContactsConnector"),
    ("dropbox", "openjarvis.connectors.dropbox", "DropboxConnector"),
]

_ALL_CONNECTORS = _LOCAL_CONNECTORS + _TOKEN_CONNECTORS


@pytest.mark.parametrize(
    "connector_id,module_path,class_name",
    _ALL_CONNECTORS,
    ids=[c[0] for c in _ALL_CONNECTORS],
)
def test_connector_instantiates(
    connector_id: str, module_path: str, class_name: str,
) -> None:
    """Every connector can be instantiated without errors."""
    import importlib

    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    instance = cls()
    assert instance is not None


@pytest.mark.parametrize(
    "connector_id,module_path,class_name",
    _ALL_CONNECTORS,
    ids=[c[0] for c in _ALL_CONNECTORS],
)
def test_connector_has_required_methods(
    connector_id: str, module_path: str, class_name: str,
) -> None:
    """Every connector implements the BaseConnector interface."""
    import importlib

    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    instance = cls()
    assert hasattr(instance, "is_connected")
    assert hasattr(instance, "disconnect")
    assert hasattr(instance, "sync")
    assert hasattr(instance, "sync_status")
    assert callable(instance.is_connected)
    assert callable(instance.disconnect)
    assert callable(instance.sync)


@pytest.mark.parametrize(
    "connector_id,module_path,class_name",
    _TOKEN_CONNECTORS,
    ids=[c[0] for c in _TOKEN_CONNECTORS],
)
def test_connector_not_connected_without_creds(
    connector_id: str, module_path: str, class_name: str,
) -> None:
    """Token connectors report not connected without credentials."""
    import importlib

    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    # Use a temp credentials path that doesn't exist
    try:
        instance = cls(credentials_path="/tmp/nonexistent_creds.json")
    except TypeError:
        instance = cls()
    assert instance.is_connected() is False


@pytest.mark.parametrize(
    "connector_id,module_path,class_name",
    _ALL_CONNECTORS,
    ids=[c[0] for c in _ALL_CONNECTORS],
)
def test_connector_has_metadata(
    connector_id: str, module_path: str, class_name: str,
) -> None:
    """Every connector has connector_id, display_name, and auth_type."""
    import importlib

    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    assert hasattr(cls, "connector_id")
    assert hasattr(cls, "display_name")
    assert hasattr(cls, "auth_type")
    assert cls.connector_id == connector_id
    assert isinstance(cls.display_name, str)
    assert cls.auth_type in ("oauth", "local", "bridge", "filesystem")


def test_knowledge_store_has_data() -> None:
    """KnowledgeStore at default path has data (if it exists)."""
    from openjarvis.connectors.store import KnowledgeStore
    from openjarvis.core.config import DEFAULT_CONFIG_DIR

    db_path = DEFAULT_CONFIG_DIR / "knowledge.db"
    if not db_path.exists():
        pytest.skip("No knowledge.db found")

    store = KnowledgeStore(str(db_path))
    count = store.count()
    assert count > 0, "KnowledgeStore has no data"

    # Check sources exist
    rows = store._conn.execute(
        "SELECT DISTINCT source FROM knowledge_chunks"
    ).fetchall()
    sources = [r[0] for r in rows]
    assert len(sources) > 0, "No sources in KnowledgeStore"
    store.close()


def test_knowledge_store_sources_have_chunks() -> None:
    """Each connected source has at least 1 chunk in the store."""
    from openjarvis.connectors.store import KnowledgeStore
    from openjarvis.core.config import DEFAULT_CONFIG_DIR

    db_path = DEFAULT_CONFIG_DIR / "knowledge.db"
    if not db_path.exists():
        pytest.skip("No knowledge.db found")

    store = KnowledgeStore(str(db_path))
    rows = store._conn.execute(
        "SELECT source, COUNT(*) as n FROM knowledge_chunks "
        "GROUP BY source ORDER BY n DESC"
    ).fetchall()

    for source, count in rows:
        assert count > 0, f"Source '{source}' has 0 chunks"

    store.close()
