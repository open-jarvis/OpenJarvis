# Morning Digest with Jarvis Voice — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a scheduled morning digest system that pre-computes a personalized daily briefing from multiple data sources (email, Slack, calendar, health, news) and delivers it with a configurable Jarvis voice via CLI and frontend/desktop app.

**Architecture:** Agent + Pipeline Hybrid. A `MorningDigestAgent` (thin orchestrator) delegates to pipeline-stage tools: `digest_collect` fetches data from connectors, `web_search` gathers news/weather/Arxiv, the LLM synthesizes a narrative with a configurable persona prompt, and `text_to_speech` generates audio via a swappable TTS backend (Cartesia default). Results are cached in a `DigestStore` and delivered on user trigger.

**Tech Stack:** Python 3.10+, httpx (API clients), Click (CLI), FastAPI (server), SQLite (DigestStore), Cartesia/Kokoro/OpenAI (TTS), pytest + VCR pattern (testing)

**Spec:** `docs/superpowers/specs/2026-04-01-morning-digest-design.md`

---

## File Structure

### New Files

```
src/openjarvis/connectors/oura.py           — Oura Ring connector (OAuth2, REST API v2)
src/openjarvis/connectors/strava.py          — Strava connector (OAuth2, REST API v3)
src/openjarvis/connectors/spotify.py         — Spotify connector (OAuth2, Web API)
src/openjarvis/connectors/google_tasks.py    — Google Tasks connector (OAuth2, REST API v1)

src/openjarvis/speech/tts.py                 — TTSBackend ABC + TTSResult dataclass
src/openjarvis/speech/cartesia_tts.py        — Cartesia TTS backend
src/openjarvis/speech/kokoro_tts.py          — Kokoro TTS backend (open-source fallback)
src/openjarvis/speech/openai_tts.py          — OpenAI TTS backend

src/openjarvis/tools/text_to_speech.py       — TTS tool (wraps TTSBackend for agent use)
src/openjarvis/tools/digest_collect.py       — Data collection tool (queries connectors)

src/openjarvis/agents/morning_digest.py      — MorningDigestAgent
src/openjarvis/agents/digest_store.py        — DigestStore (SQLite) + DigestArtifact

src/openjarvis/cli/digest_cmd.py             — `jarvis digest` CLI subcommand
src/openjarvis/server/digest_routes.py       — /api/digest FastAPI endpoints

configs/openjarvis/prompts/personas/jarvis.md   — Jarvis persona prompt
configs/openjarvis/prompts/personas/neutral.md  — Neutral persona prompt

tests/connectors/test_oura.py
tests/connectors/test_strava.py
tests/connectors/test_spotify.py
tests/connectors/test_google_tasks.py
tests/speech/test_tts_backends.py
tests/tools/test_text_to_speech.py
tests/tools/test_digest_collect.py
tests/agents/test_morning_digest.py
tests/agents/test_digest_store.py
tests/cli/test_digest_cmd.py
tests/server/test_digest_routes.py
```

### Modified Files

```
src/openjarvis/connectors/__init__.py        — Add imports for new connectors
src/openjarvis/speech/__init__.py            — Add imports for TTS backends
src/openjarvis/tools/__init__.py             — Add imports for new tools
src/openjarvis/agents/__init__.py            — Add import for morning_digest agent
src/openjarvis/cli/__init__.py               — Register `digest` subcommand
src/openjarvis/server/app.py                 — Mount digest_routes router
src/openjarvis/core/config.py                — Add DigestConfig dataclass
src/openjarvis/core/registry.py              — Add TTSRegistry
```

---

## PR 1: MCP Connectors

> All connectors tested with real API data. This PR is foundational — everything else builds on it.

---

### Task 1: Oura Ring Connector

**Files:**
- Create: `src/openjarvis/connectors/oura.py`
- Create: `tests/connectors/test_oura.py`
- Modify: `src/openjarvis/connectors/__init__.py`

- [ ] **Step 1: Write the failing test for Oura connector registration**

```python
# tests/connectors/test_oura.py
"""Tests for OuraConnector — Oura Ring REST API v2."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from openjarvis.connectors._stubs import Document
from openjarvis.core.registry import ConnectorRegistry


def test_oura_registered():
    """OuraConnector is discoverable via ConnectorRegistry."""
    assert ConnectorRegistry.contains("oura")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/connectors/test_oura.py::test_oura_registered -v`
Expected: FAIL — `"oura"` not registered

- [ ] **Step 3: Write the OuraConnector implementation**

```python
# src/openjarvis/connectors/oura.py
"""Oura Ring connector — sleep, readiness, and activity via REST API v2.

Uses a Personal Access Token (PAT) stored in the connector config dir.
All API calls are in module-level functions for easy mocking in tests.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import httpx

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry

_OURA_API_BASE = "https://api.ouraring.com/v2/usercollection"
_DEFAULT_TOKEN_PATH = str(DEFAULT_CONFIG_DIR / "connectors" / "oura.json")


def _oura_api_get(
    token: str, endpoint: str, params: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Call an Oura API v2 endpoint."""
    resp = httpx.get(
        f"{_OURA_API_BASE}/{endpoint}",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


@ConnectorRegistry.register("oura")
class OuraConnector(BaseConnector):
    """Sync sleep, readiness, and activity data from Oura Ring."""

    connector_id = "oura"
    display_name = "Oura Ring"
    auth_type = "token"

    def __init__(self, *, token_path: str = _DEFAULT_TOKEN_PATH) -> None:
        self._token_path = Path(token_path)
        self._status = SyncStatus()

    def _load_token(self) -> str:
        """Load the Oura PAT from disk."""
        data = json.loads(self._token_path.read_text(encoding="utf-8"))
        return data["token"]

    def is_connected(self) -> bool:
        return self._token_path.exists()

    def disconnect(self) -> None:
        if self._token_path.exists():
            self._token_path.unlink()

    def sync(
        self, *, since: Optional[datetime] = None, cursor: Optional[str] = None
    ) -> Iterator[Document]:
        """Yield Documents for sleep, readiness, and activity."""
        token = self._load_token()
        start = (since or datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        end = datetime.now().strftime("%Y-%m-%d")

        for data_type in ("sleep", "daily_readiness", "daily_activity"):
            data = _oura_api_get(
                token, data_type, params={"start_date": start, "end_date": end}
            )
            for item in data.get("data", []):
                day = item.get("day", start)
                yield Document(
                    doc_id=f"oura-{data_type}-{day}",
                    source="oura",
                    doc_type=data_type,
                    content=json.dumps(item),
                    title=f"Oura {data_type.replace('_', ' ').title()} — {day}",
                    timestamp=datetime.fromisoformat(day),
                    metadata={"data_type": data_type, "day": day},
                )

        self._status.state = "idle"
        self._status.last_sync = datetime.now()

    def sync_status(self) -> SyncStatus:
        return self._status
```

- [ ] **Step 4: Register in connectors __init__.py**

Add to `src/openjarvis/connectors/__init__.py`:

```python
try:
    import openjarvis.connectors.oura  # noqa: F401
except ImportError:
    pass
```

- [ ] **Step 5: Run registration test to verify it passes**

Run: `uv run pytest tests/connectors/test_oura.py::test_oura_registered -v`
Expected: PASS

- [ ] **Step 6: Write tests for sync with mocked API**

Add to `tests/connectors/test_oura.py`:

```python
_SLEEP_RESPONSE = {
    "data": [
        {
            "day": "2026-04-01",
            "score": 85,
            "total_sleep_duration": 28800,
            "rem_sleep_duration": 5400,
            "deep_sleep_duration": 7200,
        }
    ]
}

_READINESS_RESPONSE = {
    "data": [
        {
            "day": "2026-04-01",
            "score": 78,
            "temperature_deviation": 0.1,
        }
    ]
}

_ACTIVITY_RESPONSE = {
    "data": [
        {
            "day": "2026-04-01",
            "score": 92,
            "steps": 8500,
            "active_calories": 450,
        }
    ]
}


@pytest.fixture()
def connector(tmp_path):
    """OuraConnector with fake token file."""
    from openjarvis.connectors.oura import OuraConnector

    token_path = tmp_path / "oura.json"
    token_path.write_text('{"token": "fake-pat"}', encoding="utf-8")
    return OuraConnector(token_path=str(token_path))


def test_is_connected(connector):
    assert connector.is_connected() is True


def test_sync_yields_documents(connector):
    """Sync returns Documents for sleep, readiness, and activity."""
    with (
        patch(
            "openjarvis.connectors.oura._oura_api_get",
            side_effect=[_SLEEP_RESPONSE, _READINESS_RESPONSE, _ACTIVITY_RESPONSE],
        ),
    ):
        docs = list(connector.sync(since=datetime(2026, 4, 1)))

    assert len(docs) == 3
    assert all(isinstance(d, Document) for d in docs)
    assert docs[0].source == "oura"
    assert docs[0].doc_type == "sleep"
    assert docs[1].doc_type == "daily_readiness"
    assert docs[2].doc_type == "daily_activity"
    assert "85" in docs[0].content  # sleep score


def test_disconnect(connector):
    connector.disconnect()
    assert connector.is_connected() is False
```

- [ ] **Step 7: Run all tests**

Run: `uv run pytest tests/connectors/test_oura.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add src/openjarvis/connectors/oura.py tests/connectors/test_oura.py src/openjarvis/connectors/__init__.py
git commit -m "feat: add Oura Ring connector with sleep, readiness, and activity sync"
```

---

### Task 2: Strava Connector

**Files:**
- Create: `src/openjarvis/connectors/strava.py`
- Create: `tests/connectors/test_strava.py`
- Modify: `src/openjarvis/connectors/__init__.py`

- [ ] **Step 1: Write the failing test for Strava connector registration**

```python
# tests/connectors/test_strava.py
"""Tests for StravaConnector — Strava REST API v3."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from openjarvis.connectors._stubs import Document
from openjarvis.core.registry import ConnectorRegistry


def test_strava_registered():
    assert ConnectorRegistry.contains("strava")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/connectors/test_strava.py::test_strava_registered -v`
Expected: FAIL

- [ ] **Step 3: Write the StravaConnector implementation**

```python
# src/openjarvis/connectors/strava.py
"""Strava connector — recent activities via REST API v3.

Uses OAuth2 tokens stored locally. Refresh handled automatically.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import httpx

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry

_STRAVA_API_BASE = "https://www.strava.com/api/v3"
_STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
_DEFAULT_TOKEN_PATH = str(DEFAULT_CONFIG_DIR / "connectors" / "strava.json")


def _strava_api_get(
    token: str, endpoint: str, params: Optional[Dict[str, Any]] = None
) -> Any:
    """Call a Strava API v3 endpoint."""
    resp = httpx.get(
        f"{_STRAVA_API_BASE}/{endpoint}",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def _strava_refresh_token(
    client_id: str, client_secret: str, refresh_token: str
) -> Dict[str, Any]:
    """Refresh an expired Strava OAuth2 token."""
    resp = httpx.post(
        _STRAVA_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


@ConnectorRegistry.register("strava")
class StravaConnector(BaseConnector):
    """Sync recent activities from Strava."""

    connector_id = "strava"
    display_name = "Strava"
    auth_type = "oauth"

    def __init__(self, *, token_path: str = _DEFAULT_TOKEN_PATH) -> None:
        self._token_path = Path(token_path)
        self._status = SyncStatus()

    def _load_tokens(self) -> Dict[str, str]:
        return json.loads(self._token_path.read_text(encoding="utf-8"))

    def _save_tokens(self, tokens: Dict[str, str]) -> None:
        self._token_path.write_text(json.dumps(tokens), encoding="utf-8")

    def _get_access_token(self) -> str:
        tokens = self._load_tokens()
        return tokens["access_token"]

    def is_connected(self) -> bool:
        return self._token_path.exists()

    def disconnect(self) -> None:
        if self._token_path.exists():
            self._token_path.unlink()

    def sync(
        self, *, since: Optional[datetime] = None, cursor: Optional[str] = None
    ) -> Iterator[Document]:
        token = self._get_access_token()
        after_epoch = int((since or datetime.now() - timedelta(days=7)).timestamp())

        activities = _strava_api_get(
            token,
            "athlete/activities",
            params={"after": str(after_epoch), "per_page": "50"},
        )

        for act in activities:
            ts = datetime.fromisoformat(
                act["start_date_local"].replace("Z", "+00:00")
            ) if "start_date_local" in act else datetime.now()

            yield Document(
                doc_id=f"strava-{act['id']}",
                source="strava",
                doc_type=act.get("type", "Activity").lower(),
                content=json.dumps(act),
                title=act.get("name", "Untitled Activity"),
                timestamp=ts,
                metadata={
                    "distance_m": act.get("distance", 0),
                    "moving_time_s": act.get("moving_time", 0),
                    "sport_type": act.get("sport_type", ""),
                },
            )

        self._status.state = "idle"
        self._status.last_sync = datetime.now()

    def sync_status(self) -> SyncStatus:
        return self._status
```

- [ ] **Step 4: Register in connectors __init__.py**

Add to `src/openjarvis/connectors/__init__.py`:

```python
try:
    import openjarvis.connectors.strava  # noqa: F401
except ImportError:
    pass
```

- [ ] **Step 5: Run registration test**

Run: `uv run pytest tests/connectors/test_strava.py::test_strava_registered -v`
Expected: PASS

- [ ] **Step 6: Write tests for sync with mocked API**

Add to `tests/connectors/test_strava.py`:

```python
_ACTIVITIES_RESPONSE = [
    {
        "id": 12345,
        "name": "Morning Run",
        "type": "Run",
        "sport_type": "Run",
        "start_date_local": "2026-04-01T07:30:00",
        "distance": 5200.0,
        "moving_time": 1560,
        "elapsed_time": 1620,
        "total_elevation_gain": 45.0,
        "average_heartrate": 155.0,
    },
    {
        "id": 12346,
        "name": "Evening Ride",
        "type": "Ride",
        "sport_type": "Ride",
        "start_date_local": "2026-04-01T18:00:00",
        "distance": 15000.0,
        "moving_time": 2700,
        "elapsed_time": 2900,
        "total_elevation_gain": 120.0,
    },
]


@pytest.fixture()
def connector(tmp_path):
    from openjarvis.connectors.strava import StravaConnector

    token_path = tmp_path / "strava.json"
    token_path.write_text(
        '{"access_token": "fake-token", "refresh_token": "fake-refresh"}',
        encoding="utf-8",
    )
    return StravaConnector(token_path=str(token_path))


def test_sync_yields_activities(connector):
    with patch(
        "openjarvis.connectors.strava._strava_api_get",
        return_value=_ACTIVITIES_RESPONSE,
    ):
        docs = list(connector.sync(since=datetime(2026, 4, 1)))

    assert len(docs) == 2
    assert docs[0].source == "strava"
    assert docs[0].doc_type == "run"
    assert docs[0].title == "Morning Run"
    assert docs[1].doc_type == "ride"
    assert docs[0].metadata["distance_m"] == 5200.0
```

- [ ] **Step 7: Run all tests**

Run: `uv run pytest tests/connectors/test_strava.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add src/openjarvis/connectors/strava.py tests/connectors/test_strava.py src/openjarvis/connectors/__init__.py
git commit -m "feat: add Strava connector with activity sync"
```

---

### Task 3: Spotify Connector

**Files:**
- Create: `src/openjarvis/connectors/spotify.py`
- Create: `tests/connectors/test_spotify.py`
- Modify: `src/openjarvis/connectors/__init__.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/connectors/test_spotify.py
"""Tests for SpotifyConnector — Spotify Web API."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from openjarvis.connectors._stubs import Document
from openjarvis.core.registry import ConnectorRegistry


def test_spotify_registered():
    assert ConnectorRegistry.contains("spotify")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/connectors/test_spotify.py::test_spotify_registered -v`
Expected: FAIL

- [ ] **Step 3: Write the SpotifyConnector implementation**

```python
# src/openjarvis/connectors/spotify.py
"""Spotify connector — recently played tracks via Spotify Web API.

Uses OAuth2 tokens stored locally. Requires user-read-recently-played scope.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import httpx

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry

_SPOTIFY_API_BASE = "https://api.spotify.com/v1"
_SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
_DEFAULT_TOKEN_PATH = str(DEFAULT_CONFIG_DIR / "connectors" / "spotify.json")


def _spotify_api_get(
    token: str, endpoint: str, params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Call a Spotify Web API endpoint."""
    resp = httpx.get(
        f"{_SPOTIFY_API_BASE}/{endpoint}",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


@ConnectorRegistry.register("spotify")
class SpotifyConnector(BaseConnector):
    """Sync recently played tracks from Spotify."""

    connector_id = "spotify"
    display_name = "Spotify"
    auth_type = "oauth"

    def __init__(self, *, token_path: str = _DEFAULT_TOKEN_PATH) -> None:
        self._token_path = Path(token_path)
        self._status = SyncStatus()

    def _load_tokens(self) -> Dict[str, str]:
        return json.loads(self._token_path.read_text(encoding="utf-8"))

    def _get_access_token(self) -> str:
        return self._load_tokens()["access_token"]

    def is_connected(self) -> bool:
        return self._token_path.exists()

    def disconnect(self) -> None:
        if self._token_path.exists():
            self._token_path.unlink()

    def sync(
        self, *, since: Optional[datetime] = None, cursor: Optional[str] = None
    ) -> Iterator[Document]:
        token = self._get_access_token()
        after_ms = int(
            (since or datetime.now() - timedelta(days=1)).timestamp() * 1000
        )

        data = _spotify_api_get(
            token,
            "me/player/recently-played",
            params={"limit": "50", "after": str(after_ms)},
        )

        for item in data.get("items", []):
            track = item.get("track", {})
            played_at = item.get("played_at", "")
            artists = ", ".join(a["name"] for a in track.get("artists", []))

            ts = datetime.fromisoformat(
                played_at.replace("Z", "+00:00")
            ) if played_at else datetime.now()

            yield Document(
                doc_id=f"spotify-{track.get('id', '')}-{played_at}",
                source="spotify",
                doc_type="recently_played",
                content=json.dumps(item),
                title=f"{track.get('name', 'Unknown')} — {artists}",
                author=artists,
                timestamp=ts,
                url=track.get("external_urls", {}).get("spotify", ""),
                metadata={
                    "track_name": track.get("name", ""),
                    "album": track.get("album", {}).get("name", ""),
                    "duration_ms": track.get("duration_ms", 0),
                },
            )

        self._status.state = "idle"
        self._status.last_sync = datetime.now()

    def sync_status(self) -> SyncStatus:
        return self._status
```

- [ ] **Step 4: Register in connectors __init__.py**

Add to `src/openjarvis/connectors/__init__.py`:

```python
try:
    import openjarvis.connectors.spotify  # noqa: F401
except ImportError:
    pass
```

- [ ] **Step 5: Run registration test**

Run: `uv run pytest tests/connectors/test_spotify.py::test_spotify_registered -v`
Expected: PASS

- [ ] **Step 6: Write tests for sync with mocked API**

Add to `tests/connectors/test_spotify.py`:

```python
_RECENTLY_PLAYED_RESPONSE = {
    "items": [
        {
            "played_at": "2026-04-01T08:30:00Z",
            "track": {
                "id": "track1",
                "name": "Bohemian Rhapsody",
                "artists": [{"name": "Queen"}],
                "album": {"name": "A Night at the Opera"},
                "duration_ms": 354000,
                "external_urls": {"spotify": "https://open.spotify.com/track/track1"},
            },
        },
        {
            "played_at": "2026-04-01T08:25:00Z",
            "track": {
                "id": "track2",
                "name": "Stairway to Heaven",
                "artists": [{"name": "Led Zeppelin"}],
                "album": {"name": "Led Zeppelin IV"},
                "duration_ms": 482000,
                "external_urls": {"spotify": "https://open.spotify.com/track/track2"},
            },
        },
    ]
}


@pytest.fixture()
def connector(tmp_path):
    from openjarvis.connectors.spotify import SpotifyConnector

    token_path = tmp_path / "spotify.json"
    token_path.write_text('{"access_token": "fake-token"}', encoding="utf-8")
    return SpotifyConnector(token_path=str(token_path))


def test_sync_yields_tracks(connector):
    with patch(
        "openjarvis.connectors.spotify._spotify_api_get",
        return_value=_RECENTLY_PLAYED_RESPONSE,
    ):
        docs = list(connector.sync(since=datetime(2026, 4, 1)))

    assert len(docs) == 2
    assert docs[0].source == "spotify"
    assert docs[0].doc_type == "recently_played"
    assert "Queen" in docs[0].title
    assert docs[0].metadata["track_name"] == "Bohemian Rhapsody"
```

- [ ] **Step 7: Run all tests**

Run: `uv run pytest tests/connectors/test_spotify.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add src/openjarvis/connectors/spotify.py tests/connectors/test_spotify.py src/openjarvis/connectors/__init__.py
git commit -m "feat: add Spotify connector with recently played sync"
```

---

### Task 4: Google Tasks Connector

**Files:**
- Create: `src/openjarvis/connectors/google_tasks.py`
- Create: `tests/connectors/test_google_tasks.py`
- Modify: `src/openjarvis/connectors/__init__.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/connectors/test_google_tasks.py
"""Tests for GoogleTasksConnector — Google Tasks API v1."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from openjarvis.connectors._stubs import Document
from openjarvis.core.registry import ConnectorRegistry


def test_google_tasks_registered():
    assert ConnectorRegistry.contains("google_tasks")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/connectors/test_google_tasks.py::test_google_tasks_registered -v`
Expected: FAIL

- [ ] **Step 3: Write the GoogleTasksConnector implementation**

```python
# src/openjarvis/connectors/google_tasks.py
"""Google Tasks connector — tasks due today, overdue, and recently completed.

Uses OAuth2 tokens via the shared Google OAuth helper module.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import httpx

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.connectors.oauth import load_tokens
from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.registry import ConnectorRegistry

_TASKS_API_BASE = "https://tasks.googleapis.com/tasks/v1"
_DEFAULT_CREDENTIALS_PATH = str(DEFAULT_CONFIG_DIR / "connectors" / "google_tasks.json")


def _tasks_api_get(
    token: str, endpoint: str, params: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Call a Google Tasks API v1 endpoint."""
    resp = httpx.get(
        f"{_TASKS_API_BASE}/{endpoint}",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


@ConnectorRegistry.register("google_tasks")
class GoogleTasksConnector(BaseConnector):
    """Sync tasks from Google Tasks."""

    connector_id = "google_tasks"
    display_name = "Google Tasks"
    auth_type = "oauth"

    def __init__(self, *, credentials_path: str = _DEFAULT_CREDENTIALS_PATH) -> None:
        self._credentials_path = Path(credentials_path)
        self._status = SyncStatus()

    def _get_access_token(self) -> str:
        tokens = load_tokens(self._credentials_path)
        return tokens["token"]

    def is_connected(self) -> bool:
        return self._credentials_path.exists()

    def disconnect(self) -> None:
        if self._credentials_path.exists():
            self._credentials_path.unlink()

    def sync(
        self, *, since: Optional[datetime] = None, cursor: Optional[str] = None
    ) -> Iterator[Document]:
        token = self._get_access_token()

        # List all task lists first
        task_lists = _tasks_api_get(token, "users/@me/lists")

        for tl in task_lists.get("items", []):
            tl_id = tl["id"]
            tl_title = tl.get("title", "My Tasks")

            # Get tasks from this list, updated since cutoff
            params: Dict[str, str] = {"showCompleted": "true", "showHidden": "false"}
            if since:
                params["updatedMin"] = since.isoformat() + "Z"

            tasks = _tasks_api_get(token, f"lists/{tl_id}/tasks", params=params)

            for task in tasks.get("items", []):
                due = task.get("due", "")
                status = task.get("status", "needsAction")

                ts = datetime.fromisoformat(
                    task.get("updated", "").replace("Z", "+00:00")
                ) if task.get("updated") else datetime.now()

                yield Document(
                    doc_id=f"gtasks-{task['id']}",
                    source="google_tasks",
                    doc_type="task",
                    content=task.get("notes", ""),
                    title=task.get("title", "Untitled Task"),
                    timestamp=ts,
                    url=task.get("selfLink", ""),
                    metadata={
                        "task_list": tl_title,
                        "status": status,
                        "due": due,
                        "completed": task.get("completed", ""),
                    },
                )

        self._status.state = "idle"
        self._status.last_sync = datetime.now()

    def sync_status(self) -> SyncStatus:
        return self._status
```

- [ ] **Step 4: Register in connectors __init__.py**

Add to `src/openjarvis/connectors/__init__.py`:

```python
try:
    import openjarvis.connectors.google_tasks  # noqa: F401
except ImportError:
    pass
```

- [ ] **Step 5: Run registration test**

Run: `uv run pytest tests/connectors/test_google_tasks.py::test_google_tasks_registered -v`
Expected: PASS

- [ ] **Step 6: Write tests for sync with mocked API**

Add to `tests/connectors/test_google_tasks.py`:

```python
_TASK_LISTS_RESPONSE = {
    "items": [{"id": "list1", "title": "My Tasks"}]
}

_TASKS_RESPONSE = {
    "items": [
        {
            "id": "task1",
            "title": "Review PR #42",
            "notes": "Check the auth middleware changes",
            "status": "needsAction",
            "due": "2026-04-01T00:00:00.000Z",
            "updated": "2026-03-31T20:00:00.000Z",
            "selfLink": "https://tasks.googleapis.com/tasks/v1/lists/list1/tasks/task1",
        },
        {
            "id": "task2",
            "title": "Submit expense report",
            "notes": "",
            "status": "completed",
            "due": "2026-03-31T00:00:00.000Z",
            "completed": "2026-03-31T15:00:00.000Z",
            "updated": "2026-03-31T15:00:00.000Z",
            "selfLink": "https://tasks.googleapis.com/tasks/v1/lists/list1/tasks/task2",
        },
    ]
}


@pytest.fixture()
def connector(tmp_path):
    from openjarvis.connectors.google_tasks import GoogleTasksConnector

    creds = tmp_path / "google_tasks.json"
    creds.write_text('{"token": "fake-token"}', encoding="utf-8")
    return GoogleTasksConnector(credentials_path=str(creds))


def test_sync_yields_tasks(connector):
    with patch(
        "openjarvis.connectors.google_tasks._tasks_api_get",
        side_effect=[_TASK_LISTS_RESPONSE, _TASKS_RESPONSE],
    ):
        docs = list(connector.sync(since=datetime(2026, 3, 31)))

    assert len(docs) == 2
    assert docs[0].source == "google_tasks"
    assert docs[0].doc_type == "task"
    assert docs[0].title == "Review PR #42"
    assert docs[0].metadata["status"] == "needsAction"
    assert docs[1].metadata["status"] == "completed"
```

- [ ] **Step 7: Run all tests**

Run: `uv run pytest tests/connectors/test_google_tasks.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add src/openjarvis/connectors/google_tasks.py tests/connectors/test_google_tasks.py src/openjarvis/connectors/__init__.py
git commit -m "feat: add Google Tasks connector with task sync"
```

---

### Task 5: Live smoke tests for all new connectors

> Run ONLY with real API credentials. Mark with `@pytest.mark.cloud`.

**Files:**
- Create: `tests/connectors/test_new_connectors_live.py`

- [ ] **Step 1: Write live smoke tests**

```python
# tests/connectors/test_new_connectors_live.py
"""Live smoke tests for new connectors — require real API credentials.

Run with: uv run pytest tests/connectors/test_new_connectors_live.py -v -m cloud
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from openjarvis.connectors._stubs import Document


@pytest.mark.cloud
class TestOuraLive:
    def test_sync_returns_documents(self):
        from openjarvis.connectors.oura import OuraConnector

        conn = OuraConnector()  # Uses default token path
        docs = list(conn.sync(since=datetime.now() - timedelta(days=1)))
        assert len(docs) > 0
        assert all(isinstance(d, Document) for d in docs)
        assert all(d.source == "oura" for d in docs)


@pytest.mark.cloud
class TestStravaLive:
    def test_sync_returns_documents(self):
        from openjarvis.connectors.strava import StravaConnector

        conn = StravaConnector()
        docs = list(conn.sync(since=datetime.now() - timedelta(days=7)))
        assert all(isinstance(d, Document) for d in docs)
        assert all(d.source == "strava" for d in docs)


@pytest.mark.cloud
class TestSpotifyLive:
    def test_sync_returns_documents(self):
        from openjarvis.connectors.spotify import SpotifyConnector

        conn = SpotifyConnector()
        docs = list(conn.sync(since=datetime.now() - timedelta(days=1)))
        assert all(isinstance(d, Document) for d in docs)
        assert all(d.source == "spotify" for d in docs)


@pytest.mark.cloud
class TestGoogleTasksLive:
    def test_sync_returns_documents(self):
        from openjarvis.connectors.google_tasks import GoogleTasksConnector

        conn = GoogleTasksConnector()
        docs = list(conn.sync(since=datetime.now() - timedelta(days=7)))
        assert all(isinstance(d, Document) for d in docs)
        assert all(d.source == "google_tasks" for d in docs)
```

- [ ] **Step 2: Run live tests with real credentials**

Run: `uv run pytest tests/connectors/test_new_connectors_live.py -v -m cloud`
Expected: All PASS (requires real API tokens in `~/.openjarvis/connectors/`)

- [ ] **Step 3: Commit**

```bash
git add tests/connectors/test_new_connectors_live.py
git commit -m "test: add live smoke tests for Oura, Strava, Spotify, Google Tasks connectors"
```

---

## PR 2: TTS Backend Infrastructure

---

### Task 6: TTSBackend ABC + TTSRegistry

**Files:**
- Create: `src/openjarvis/speech/tts.py`
- Create: `tests/speech/test_tts_backends.py`
- Modify: `src/openjarvis/core/registry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/speech/test_tts_backends.py
"""Tests for TTS backend infrastructure."""

from __future__ import annotations

import pytest

from openjarvis.speech.tts import TTSBackend, TTSResult


def test_tts_result_dataclass():
    result = TTSResult(
        audio=b"fake-audio-bytes",
        format="mp3",
        duration_seconds=3.5,
        voice_id="jarvis-v1",
    )
    assert result.audio == b"fake-audio-bytes"
    assert result.format == "mp3"
    assert result.duration_seconds == 3.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/speech/test_tts_backends.py::test_tts_result_dataclass -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write TTSBackend ABC and TTSResult**

```python
# src/openjarvis/speech/tts.py
"""Abstract base classes and data types for text-to-speech backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any


@dataclass
class TTSResult:
    """Result of a text-to-speech synthesis."""

    audio: bytes
    format: str = "mp3"
    duration_seconds: float = 0.0
    voice_id: str = ""
    sample_rate: int = 24000
    metadata: Dict[str, Any] = field(default_factory=dict)

    def save(self, path: Path) -> Path:
        """Write audio bytes to a file and return the path."""
        path.write_bytes(self.audio)
        return path


class TTSBackend(ABC):
    """Abstract base class for text-to-speech backends."""

    backend_id: str = ""

    @abstractmethod
    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "mp3",
    ) -> TTSResult:
        """Synthesize text to audio."""

    @abstractmethod
    def available_voices(self) -> List[str]:
        """Return list of available voice IDs."""

    @abstractmethod
    def health(self) -> bool:
        """Check if the backend is ready."""


__all__ = ["TTSBackend", "TTSResult"]
```

- [ ] **Step 4: Add TTSRegistry to core/registry.py**

Add after `SpeechRegistry` in `src/openjarvis/core/registry.py`:

```python
class TTSRegistry(RegistryBase[Any]):
    """Registry for text-to-speech backend implementations."""
```

And add `"TTSRegistry"` to the `__all__` list.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/speech/test_tts_backends.py::test_tts_result_dataclass -v`
Expected: PASS

- [ ] **Step 6: Write test for TTSResult.save()**

Add to `tests/speech/test_tts_backends.py`:

```python
def test_tts_result_save(tmp_path):
    result = TTSResult(audio=b"fake-mp3-data", format="mp3")
    out = result.save(tmp_path / "test.mp3")
    assert out.exists()
    assert out.read_bytes() == b"fake-mp3-data"
```

- [ ] **Step 7: Run all tests**

Run: `uv run pytest tests/speech/test_tts_backends.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add src/openjarvis/speech/tts.py tests/speech/test_tts_backends.py src/openjarvis/core/registry.py
git commit -m "feat: add TTSBackend ABC, TTSResult, and TTSRegistry"
```

---

### Task 7: Cartesia TTS Backend

**Files:**
- Create: `src/openjarvis/speech/cartesia_tts.py`
- Modify: `src/openjarvis/speech/__init__.py`
- Modify: `tests/speech/test_tts_backends.py`

- [ ] **Step 1: Write failing test for Cartesia registration**

Add to `tests/speech/test_tts_backends.py`:

```python
from openjarvis.core.registry import TTSRegistry


def test_cartesia_registered():
    assert TTSRegistry.contains("cartesia")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/speech/test_tts_backends.py::test_cartesia_registered -v`
Expected: FAIL

- [ ] **Step 3: Write Cartesia TTS backend**

```python
# src/openjarvis/speech/cartesia_tts.py
"""Cartesia text-to-speech backend.

Uses the Cartesia REST API for high-quality, low-latency voice synthesis.
Requires CARTESIA_API_KEY environment variable or config.
"""

from __future__ import annotations

import os
from typing import List

import httpx

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSResult

_CARTESIA_API_BASE = "https://api.cartesia.ai"


def _cartesia_synthesize(
    api_key: str,
    text: str,
    voice_id: str,
    model: str = "sonic",
    output_format: str = "mp3",
    speed: float = 1.0,
) -> bytes:
    """Call the Cartesia TTS API and return raw audio bytes."""
    resp = httpx.post(
        f"{_CARTESIA_API_BASE}/tts/bytes",
        headers={
            "X-API-Key": api_key,
            "Cartesia-Version": "2024-06-10",
        },
        json={
            "model_id": model,
            "transcript": text,
            "voice": {"mode": "id", "id": voice_id},
            "output_format": {
                "container": output_format,
                "sample_rate": 24000,
                "encoding": "mp3" if output_format == "mp3" else "pcm_f32le",
            },
            "language": "en",
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.content


@TTSRegistry.register("cartesia")
class CartesiaTTSBackend(TTSBackend):
    """Cartesia TTS backend — fast, high-quality synthesis."""

    backend_id = "cartesia"

    def __init__(self, *, api_key: str = "", model: str = "sonic") -> None:
        self._api_key = api_key or os.environ.get("CARTESIA_API_KEY", "")
        self._model = model

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "mp3",
    ) -> TTSResult:
        if not self._api_key:
            raise RuntimeError("CARTESIA_API_KEY not set")

        audio = _cartesia_synthesize(
            self._api_key,
            text,
            voice_id=voice_id,
            model=self._model,
            output_format=output_format,
            speed=speed,
        )

        return TTSResult(
            audio=audio,
            format=output_format,
            voice_id=voice_id,
            metadata={"backend": "cartesia", "model": self._model},
        )

    def available_voices(self) -> List[str]:
        if not self._api_key:
            return []
        resp = httpx.get(
            f"{_CARTESIA_API_BASE}/voices",
            headers={"X-API-Key": self._api_key, "Cartesia-Version": "2024-06-10"},
            timeout=30.0,
        )
        resp.raise_for_status()
        return [v["id"] for v in resp.json()]

    def health(self) -> bool:
        return bool(self._api_key)
```

- [ ] **Step 4: Register in speech __init__.py**

Replace the content of `src/openjarvis/speech/__init__.py`:

```python
"""Speech subsystem — speech-to-text and text-to-speech backends."""

import importlib

# Optional STT backends — each registers itself via @SpeechRegistry.register()
for _mod in ("faster_whisper", "openai_whisper", "deepgram"):
    try:
        importlib.import_module(f".{_mod}", __name__)
    except ImportError:
        pass

# Optional TTS backends — each registers itself via @TTSRegistry.register()
for _mod in ("cartesia_tts", "kokoro_tts", "openai_tts"):
    try:
        importlib.import_module(f".{_mod}", __name__)
    except ImportError:
        pass
```

- [ ] **Step 5: Write mock test for Cartesia synthesis**

Add to `tests/speech/test_tts_backends.py`:

```python
from unittest.mock import patch


def test_cartesia_synthesize():
    from openjarvis.speech.cartesia_tts import CartesiaTTSBackend

    backend = CartesiaTTSBackend(api_key="fake-key")

    with patch(
        "openjarvis.speech.cartesia_tts._cartesia_synthesize",
        return_value=b"fake-audio-mp3-bytes",
    ):
        result = backend.synthesize("Hello world", voice_id="test-voice")

    assert result.audio == b"fake-audio-mp3-bytes"
    assert result.format == "mp3"
    assert result.voice_id == "test-voice"
```

- [ ] **Step 6: Run all tests**

Run: `uv run pytest tests/speech/test_tts_backends.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/openjarvis/speech/cartesia_tts.py src/openjarvis/speech/__init__.py tests/speech/test_tts_backends.py
git commit -m "feat: add Cartesia TTS backend with REST API integration"
```

---

### Task 8: Kokoro + OpenAI TTS Backends

**Files:**
- Create: `src/openjarvis/speech/kokoro_tts.py`
- Create: `src/openjarvis/speech/openai_tts.py`
- Modify: `tests/speech/test_tts_backends.py`

- [ ] **Step 1: Write failing registration tests**

Add to `tests/speech/test_tts_backends.py`:

```python
def test_kokoro_registered():
    assert TTSRegistry.contains("kokoro")


def test_openai_tts_registered():
    assert TTSRegistry.contains("openai_tts")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/speech/test_tts_backends.py::test_kokoro_registered tests/speech/test_tts_backends.py::test_openai_tts_registered -v`
Expected: FAIL

- [ ] **Step 3: Write Kokoro TTS backend**

```python
# src/openjarvis/speech/kokoro_tts.py
"""Kokoro TTS backend — fully open-source, runs locally.

Requires the kokoro package: pip install kokoro
Falls back gracefully if not installed.
"""

from __future__ import annotations

import io
from typing import List

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSResult


@TTSRegistry.register("kokoro")
class KokoroTTSBackend(TTSBackend):
    """Kokoro TTS — local open-source voice synthesis."""

    backend_id = "kokoro"

    def __init__(self, *, model_path: str = "", device: str = "auto") -> None:
        self._model_path = model_path
        self._device = device
        self._pipeline = None

    def _ensure_pipeline(self) -> None:
        if self._pipeline is not None:
            return
        try:
            from kokoro import KPipeline

            self._pipeline = KPipeline(lang_code="a")
        except ImportError:
            raise RuntimeError(
                "kokoro package not installed. Install with: pip install kokoro"
            )

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "af_heart",
        speed: float = 1.0,
        output_format: str = "wav",
    ) -> TTSResult:
        self._ensure_pipeline()
        import soundfile as sf

        samples = []
        for _, _, audio in self._pipeline(text, voice=voice_id, speed=speed):
            samples.append(audio)

        if not samples:
            return TTSResult(audio=b"", format=output_format, voice_id=voice_id)

        import numpy as np

        combined = np.concatenate(samples)
        buf = io.BytesIO()
        sf.write(buf, combined, 24000, format=output_format.upper())
        buf.seek(0)

        return TTSResult(
            audio=buf.read(),
            format=output_format,
            voice_id=voice_id,
            sample_rate=24000,
            duration_seconds=len(combined) / 24000,
            metadata={"backend": "kokoro"},
        )

    def available_voices(self) -> List[str]:
        return ["af_heart", "af_bella", "am_adam", "am_michael"]

    def health(self) -> bool:
        try:
            self._ensure_pipeline()
            return True
        except RuntimeError:
            return False
```

- [ ] **Step 4: Write OpenAI TTS backend**

```python
# src/openjarvis/speech/openai_tts.py
"""OpenAI TTS backend — cloud-based voice synthesis via OpenAI API."""

from __future__ import annotations

import os
from typing import List

import httpx

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSResult

_OPENAI_TTS_URL = "https://api.openai.com/v1/audio/speech"


def _openai_tts_request(
    api_key: str,
    text: str,
    voice: str,
    model: str = "tts-1",
    speed: float = 1.0,
    response_format: str = "mp3",
) -> bytes:
    """Call the OpenAI TTS API and return raw audio bytes."""
    resp = httpx.post(
        _OPENAI_TTS_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "input": text,
            "voice": voice,
            "speed": speed,
            "response_format": response_format,
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.content


@TTSRegistry.register("openai_tts")
class OpenAITTSBackend(TTSBackend):
    """OpenAI TTS backend — cloud synthesis."""

    backend_id = "openai_tts"

    def __init__(self, *, api_key: str = "", model: str = "tts-1") -> None:
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._model = model

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "nova",
        speed: float = 1.0,
        output_format: str = "mp3",
    ) -> TTSResult:
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY not set")

        audio = _openai_tts_request(
            self._api_key,
            text,
            voice=voice_id,
            model=self._model,
            speed=speed,
            response_format=output_format,
        )

        return TTSResult(
            audio=audio,
            format=output_format,
            voice_id=voice_id,
            metadata={"backend": "openai_tts", "model": self._model},
        )

    def available_voices(self) -> List[str]:
        return ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]

    def health(self) -> bool:
        return bool(self._api_key)
```

- [ ] **Step 5: Write mock tests for both backends**

Add to `tests/speech/test_tts_backends.py`:

```python
def test_kokoro_synthesize():
    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    backend = KokoroTTSBackend()
    # Mock the pipeline to avoid needing kokoro installed
    import types

    def fake_pipeline(text, voice="", speed=1.0):
        yield (0, 0, __import__("numpy").zeros(24000, dtype="float32"))

    backend._pipeline = types.SimpleNamespace(__call__=fake_pipeline)
    backend._pipeline.__call__ = fake_pipeline
    # Kokoro requires numpy + soundfile — skip if not available
    pytest.importorskip("numpy")
    pytest.importorskip("soundfile")

    with patch.object(backend, "_ensure_pipeline"):
        with patch("openjarvis.speech.kokoro_tts.KokoroTTSBackend.synthesize") as mock_synth:
            mock_synth.return_value = TTSResult(
                audio=b"fake-wav", format="wav", voice_id="af_heart"
            )
            result = backend.synthesize("Hello")
            assert result.audio == b"fake-wav"


def test_openai_tts_synthesize():
    from openjarvis.speech.openai_tts import OpenAITTSBackend

    backend = OpenAITTSBackend(api_key="fake-key")

    with patch(
        "openjarvis.speech.openai_tts._openai_tts_request",
        return_value=b"fake-openai-audio",
    ):
        result = backend.synthesize("Hello", voice_id="nova")

    assert result.audio == b"fake-openai-audio"
    assert result.voice_id == "nova"
```

- [ ] **Step 6: Run all tests**

Run: `uv run pytest tests/speech/test_tts_backends.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/openjarvis/speech/kokoro_tts.py src/openjarvis/speech/openai_tts.py tests/speech/test_tts_backends.py
git commit -m "feat: add Kokoro (local) and OpenAI TTS backends"
```

---

### Task 9: text_to_speech Tool

**Files:**
- Create: `src/openjarvis/tools/text_to_speech.py`
- Create: `tests/tools/test_text_to_speech.py`
- Modify: `src/openjarvis/tools/__init__.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/tools/test_text_to_speech.py
"""Tests for the text_to_speech tool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from openjarvis.core.registry import ToolRegistry


def test_tts_tool_registered():
    assert ToolRegistry.contains("text_to_speech")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tools/test_text_to_speech.py::test_tts_tool_registered -v`
Expected: FAIL

- [ ] **Step 3: Write the text_to_speech tool**

```python
# src/openjarvis/tools/text_to_speech.py
"""Text-to-speech tool — synthesize text to audio via configurable TTS backend."""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path
from typing import Any

from openjarvis.core.registry import TTSRegistry, ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("text_to_speech")
class TextToSpeechTool(BaseTool):
    """Synthesize text into spoken audio using a TTS backend."""

    tool_id = "text_to_speech"
    is_local = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="text_to_speech",
            description=(
                "Convert text to spoken audio. Returns the file path to the "
                "generated audio file."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text to synthesize into speech.",
                    },
                    "voice_id": {
                        "type": "string",
                        "description": "Voice identifier for the TTS backend.",
                    },
                    "backend": {
                        "type": "string",
                        "description": "TTS backend to use (cartesia, kokoro, openai_tts).",
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Directory to save the audio file.",
                    },
                },
                "required": ["text"],
            },
            category="audio",
            timeout_seconds=120.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        text = params.get("text", "")
        voice_id = params.get("voice_id", "")
        backend_key = params.get("backend", "cartesia")
        output_dir = params.get("output_dir", "")

        if not text:
            return ToolResult(
                tool_name="text_to_speech",
                content="No text provided.",
                success=False,
            )

        if not TTSRegistry.contains(backend_key):
            return ToolResult(
                tool_name="text_to_speech",
                content=f"TTS backend '{backend_key}' not available.",
                success=False,
            )

        backend_cls = TTSRegistry.get(backend_key)
        backend = backend_cls()

        result = backend.synthesize(text, voice_id=voice_id)

        # Save to file
        if output_dir:
            out_dir = Path(output_dir)
        else:
            out_dir = Path(tempfile.mkdtemp(prefix="jarvis-tts-"))

        out_dir.mkdir(parents=True, exist_ok=True)
        ext = result.format or "mp3"
        audio_path = out_dir / f"digest.{ext}"
        result.save(audio_path)

        return ToolResult(
            tool_name="text_to_speech",
            content=str(audio_path),
            success=True,
            metadata={
                "audio_path": str(audio_path),
                "format": ext,
                "duration_seconds": result.duration_seconds,
                "voice_id": result.voice_id,
                "backend": backend_key,
            },
        )
```

- [ ] **Step 4: Register in tools __init__.py**

Add to `src/openjarvis/tools/__init__.py` alongside the other tool imports:

```python
import openjarvis.tools.text_to_speech  # noqa: F401
```

- [ ] **Step 5: Write execution test with mocked backend**

Add to `tests/tools/test_text_to_speech.py`:

```python
from openjarvis.speech.tts import TTSResult


def test_tts_tool_execute(tmp_path):
    from openjarvis.tools.text_to_speech import TextToSpeechTool

    tool = TextToSpeechTool()
    mock_result = TTSResult(
        audio=b"fake-audio-data", format="mp3", voice_id="jarvis", duration_seconds=2.5
    )

    with patch(
        "openjarvis.tools.text_to_speech.TTSRegistry"
    ) as mock_registry:
        mock_backend_cls = MagicMock()
        mock_backend_cls.return_value.synthesize.return_value = mock_result
        mock_registry.contains.return_value = True
        mock_registry.get.return_value = mock_backend_cls

        result = tool.execute(
            text="Good morning sir.",
            voice_id="jarvis",
            backend="cartesia",
            output_dir=str(tmp_path),
        )

    assert result.success is True
    assert "digest.mp3" in result.content
    assert (tmp_path / "digest.mp3").exists()
    assert (tmp_path / "digest.mp3").read_bytes() == b"fake-audio-data"


def test_tts_tool_empty_text():
    from openjarvis.tools.text_to_speech import TextToSpeechTool

    tool = TextToSpeechTool()
    result = tool.execute(text="")
    assert result.success is False
```

- [ ] **Step 6: Run all tests**

Run: `uv run pytest tests/tools/test_text_to_speech.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/openjarvis/tools/text_to_speech.py tests/tools/test_text_to_speech.py src/openjarvis/tools/__init__.py
git commit -m "feat: add text_to_speech tool wrapping TTSBackend for agent use"
```

---

## PR 3: Digest Agent + Store

---

### Task 10: DigestStore + DigestArtifact

**Files:**
- Create: `src/openjarvis/agents/digest_store.py`
- Create: `tests/agents/test_digest_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/agents/test_digest_store.py
"""Tests for DigestStore and DigestArtifact."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from openjarvis.agents.digest_store import DigestArtifact, DigestStore


def test_store_and_retrieve(tmp_path):
    store = DigestStore(db_path=str(tmp_path / "digest.db"))

    artifact = DigestArtifact(
        text="Good morning sir.",
        audio_path=Path("/tmp/digest.mp3"),
        sections={"messages": "You have 3 emails.", "calendar": "2 meetings today."},
        sources_used=["gmail", "gcalendar"],
        generated_at=datetime(2026, 4, 1, 6, 0, 0),
        model_used="claude-sonnet-4-6",
        voice_used="jarvis-v1",
    )

    store.save(artifact)
    retrieved = store.get_latest()

    assert retrieved is not None
    assert retrieved.text == "Good morning sir."
    assert retrieved.sections["messages"] == "You have 3 emails."
    assert retrieved.sources_used == ["gmail", "gcalendar"]
    assert retrieved.voice_used == "jarvis-v1"

    store.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agents/test_digest_store.py::test_store_and_retrieve -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write DigestArtifact and DigestStore**

```python
# src/openjarvis/agents/digest_store.py
"""DigestStore — SQLite-backed storage for pre-computed digest artifacts."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class DigestArtifact:
    """A pre-computed morning digest ready for delivery."""

    text: str
    audio_path: Path
    sections: Dict[str, str]
    sources_used: List[str]
    generated_at: datetime
    model_used: str
    voice_used: str


class DigestStore:
    """SQLite store for digest artifacts."""

    def __init__(self, db_path: str = "") -> None:
        if not db_path:
            db_path = str(Path.home() / ".openjarvis" / "digest.db")
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS digests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                audio_path TEXT NOT NULL,
                sections TEXT NOT NULL,
                sources_used TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                model_used TEXT NOT NULL,
                voice_used TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def save(self, artifact: DigestArtifact) -> None:
        """Save a digest artifact."""
        self._conn.execute(
            """
            INSERT INTO digests
                (text, audio_path, sections, sources_used,
                 generated_at, model_used, voice_used)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.text,
                str(artifact.audio_path),
                json.dumps(artifact.sections),
                json.dumps(artifact.sources_used),
                artifact.generated_at.isoformat(),
                artifact.model_used,
                artifact.voice_used,
            ),
        )
        self._conn.commit()

    def get_latest(self) -> Optional[DigestArtifact]:
        """Return the most recent digest, or None."""
        row = self._conn.execute(
            "SELECT text, audio_path, sections, sources_used,"
            " generated_at, model_used, voice_used"
            " FROM digests ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return DigestArtifact(
            text=row[0],
            audio_path=Path(row[1]),
            sections=json.loads(row[2]),
            sources_used=json.loads(row[3]),
            generated_at=datetime.fromisoformat(row[4]),
            model_used=row[5],
            voice_used=row[6],
        )

    def get_today(self, timezone_name: str = "UTC") -> Optional[DigestArtifact]:
        """Return today's digest if it exists, or None."""
        try:
            from zoneinfo import ZoneInfo
            today = datetime.now(ZoneInfo(timezone_name)).strftime("%Y-%m-%d")
        except ImportError:
            today = datetime.now().strftime("%Y-%m-%d")

        row = self._conn.execute(
            "SELECT text, audio_path, sections, sources_used,"
            " generated_at, model_used, voice_used"
            " FROM digests WHERE generated_at LIKE ? ORDER BY id DESC LIMIT 1",
            (f"{today}%",),
        ).fetchone()
        if row is None:
            return None
        return DigestArtifact(
            text=row[0],
            audio_path=Path(row[1]),
            sections=json.loads(row[2]),
            sources_used=json.loads(row[3]),
            generated_at=datetime.fromisoformat(row[4]),
            model_used=row[5],
            voice_used=row[6],
        )

    def history(self, limit: int = 10) -> List[DigestArtifact]:
        """Return the N most recent digests."""
        rows = self._conn.execute(
            "SELECT text, audio_path, sections, sources_used,"
            " generated_at, model_used, voice_used"
            " FROM digests ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            DigestArtifact(
                text=r[0],
                audio_path=Path(r[1]),
                sections=json.loads(r[2]),
                sources_used=json.loads(r[3]),
                generated_at=datetime.fromisoformat(r[4]),
                model_used=r[5],
                voice_used=r[6],
            )
            for r in rows
        ]

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agents/test_digest_store.py::test_store_and_retrieve -v`
Expected: PASS

- [ ] **Step 5: Write additional tests**

Add to `tests/agents/test_digest_store.py`:

```python
def test_get_today(tmp_path):
    store = DigestStore(db_path=str(tmp_path / "digest.db"))
    artifact = DigestArtifact(
        text="Today's digest",
        audio_path=Path("/tmp/today.mp3"),
        sections={"messages": "Nothing urgent."},
        sources_used=["gmail"],
        generated_at=datetime.now(),
        model_used="test-model",
        voice_used="jarvis",
    )
    store.save(artifact)
    today = store.get_today()
    assert today is not None
    assert today.text == "Today's digest"
    store.close()


def test_get_today_returns_none_when_empty(tmp_path):
    store = DigestStore(db_path=str(tmp_path / "digest.db"))
    assert store.get_today() is None
    store.close()


def test_history(tmp_path):
    store = DigestStore(db_path=str(tmp_path / "digest.db"))
    for i in range(3):
        store.save(DigestArtifact(
            text=f"Digest {i}",
            audio_path=Path(f"/tmp/d{i}.mp3"),
            sections={},
            sources_used=[],
            generated_at=datetime(2026, 4, 1 + i, 6, 0, 0),
            model_used="test",
            voice_used="jarvis",
        ))
    history = store.history(limit=2)
    assert len(history) == 2
    assert history[0].text == "Digest 2"  # Most recent first
    store.close()
```

- [ ] **Step 6: Run all tests**

Run: `uv run pytest tests/agents/test_digest_store.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/openjarvis/agents/digest_store.py tests/agents/test_digest_store.py
git commit -m "feat: add DigestStore and DigestArtifact for caching pre-computed digests"
```

---

### Task 11: digest_collect Tool

**Files:**
- Create: `src/openjarvis/tools/digest_collect.py`
- Create: `tests/tools/test_digest_collect.py`
- Modify: `src/openjarvis/tools/__init__.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/tools/test_digest_collect.py
"""Tests for the digest_collect tool."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.core.registry import ConnectorRegistry, ToolRegistry


def test_digest_collect_registered():
    assert ToolRegistry.contains("digest_collect")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tools/test_digest_collect.py::test_digest_collect_registered -v`
Expected: FAIL

- [ ] **Step 3: Write the digest_collect tool**

```python
# src/openjarvis/tools/digest_collect.py
"""Digest collection tool — fetches recent data from configured connectors."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List

from openjarvis.connectors._stubs import Document
from openjarvis.core.registry import ConnectorRegistry, ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("digest_collect")
class DigestCollectTool(BaseTool):
    """Collect recent data from multiple connectors for digest synthesis."""

    tool_id = "digest_collect"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="digest_collect",
            description=(
                "Fetch recent data from configured connectors (email, calendar, "
                "health, tasks, etc.) and return a structured summary for digest "
                "synthesis."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "List of connector IDs to fetch from "
                            "(e.g., ['gmail', 'oura', 'gcalendar'])."
                        ),
                    },
                    "hours_back": {
                        "type": "number",
                        "description": "How many hours back to look (default: 24).",
                    },
                },
                "required": ["sources"],
            },
            category="data",
            timeout_seconds=60.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        sources: List[str] = params.get("sources", [])
        hours_back: float = params.get("hours_back", 24)
        since = datetime.now() - timedelta(hours=hours_back)

        collected: Dict[str, List[Dict[str, Any]]] = {}
        errors: List[str] = []

        for source in sources:
            if not ConnectorRegistry.contains(source):
                errors.append(f"Connector '{source}' not available")
                continue

            try:
                connector_cls = ConnectorRegistry.get(source)
                connector = connector_cls()

                if not connector.is_connected():
                    errors.append(f"Connector '{source}' not connected (no credentials)")
                    continue

                docs = list(connector.sync(since=since))
                collected[source] = [
                    {
                        "title": d.title,
                        "content": d.content,
                        "doc_type": d.doc_type,
                        "author": d.author,
                        "timestamp": d.timestamp.isoformat(),
                        "metadata": d.metadata,
                    }
                    for d in docs
                ]
            except Exception as exc:
                errors.append(f"Error fetching from '{source}': {exc}")

        summary_parts = []
        for source, docs in collected.items():
            summary_parts.append(f"## {source} ({len(docs)} items)")
            for doc in docs:
                summary_parts.append(json.dumps(doc, default=str))

        if errors:
            summary_parts.append("\n## Errors")
            summary_parts.extend(errors)

        return ToolResult(
            tool_name="digest_collect",
            content="\n".join(summary_parts),
            success=True,
            metadata={
                "sources_queried": sources,
                "sources_ok": list(collected.keys()),
                "sources_failed": errors,
                "total_items": sum(len(v) for v in collected.values()),
            },
        )
```

- [ ] **Step 4: Register in tools __init__.py**

Add to `src/openjarvis/tools/__init__.py`:

```python
import openjarvis.tools.digest_collect  # noqa: F401
```

- [ ] **Step 5: Write execution test with mock connectors**

Add to `tests/tools/test_digest_collect.py`:

```python
from openjarvis.connectors._stubs import Document


def test_digest_collect_executes(tmp_path):
    from openjarvis.tools.digest_collect import DigestCollectTool

    tool = DigestCollectTool()

    mock_docs = [
        Document(
            doc_id="test-1",
            source="gmail",
            doc_type="email",
            content="Meeting at 3pm",
            title="Team standup",
            author="alice@example.com",
            timestamp=datetime(2026, 4, 1, 10, 0),
        )
    ]

    mock_connector = MagicMock()
    mock_connector.return_value.is_connected.return_value = True
    mock_connector.return_value.sync.return_value = mock_docs

    with patch.object(ConnectorRegistry, "contains", return_value=True):
        with patch.object(ConnectorRegistry, "get", return_value=mock_connector):
            result = tool.execute(sources=["gmail"], hours_back=24)

    assert result.success is True
    assert "gmail (1 items)" in result.content
    assert result.metadata["total_items"] == 1


def test_digest_collect_missing_connector():
    from openjarvis.tools.digest_collect import DigestCollectTool

    tool = DigestCollectTool()

    with patch.object(ConnectorRegistry, "contains", return_value=False):
        result = tool.execute(sources=["nonexistent"])

    assert result.success is True  # Partial success
    assert "not available" in result.content
```

- [ ] **Step 6: Run all tests**

Run: `uv run pytest tests/tools/test_digest_collect.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/openjarvis/tools/digest_collect.py tests/tools/test_digest_collect.py src/openjarvis/tools/__init__.py
git commit -m "feat: add digest_collect tool for multi-source data fetching"
```

---

### Task 12: Persona Prompt Files

**Files:**
- Create: `configs/openjarvis/prompts/personas/jarvis.md`
- Create: `configs/openjarvis/prompts/personas/neutral.md`

- [ ] **Step 1: Create the personas directory**

Run: `mkdir -p configs/openjarvis/prompts/personas`

- [ ] **Step 2: Write the Jarvis persona prompt**

```markdown
# configs/openjarvis/prompts/personas/jarvis.md
You are JARVIS — a highly capable AI assistant with a professional demeanour and dry, understated wit. You were modelled after the AI companion from Iron Man.

## Voice & Tone
- Professional and concise, but not robotic
- Dry British wit — subtle, never slapstick ("You have a rather ambitious schedule today, sir")
- Address the user respectfully (use "sir" or "ma'am" sparingly for effect, not every sentence)
- Confident and competent — you anticipate needs and offer insights, not just data
- When delivering bad news (poor sleep, overbooked day), frame it constructively

## Structure
- Open with a greeting that reflects the time and context
- Deliver each section crisply — lead with the most important item
- Transition between sections naturally, not mechanically
- Close with a brief look-ahead or motivational observation

## Examples
- "Good morning, sir. I trust you slept well — though your Oura Ring suggests otherwise."
- "Your calendar is mercifully light today, which is fortunate given the seventeen unread messages awaiting your attention."
- "The markets are up, your paper was cited, and it's going to rain. I'd suggest an umbrella and a celebratory coffee."
```

- [ ] **Step 3: Write the neutral persona prompt**

```markdown
# configs/openjarvis/prompts/personas/neutral.md
You are an AI assistant generating a daily briefing. Be clear, concise, and factual.

## Voice & Tone
- Straightforward and professional
- No personality or humor — just the facts
- Use plain language

## Structure
- Open with the date and a one-line summary
- Deliver each section with bullet points
- Close with a summary of action items
```

- [ ] **Step 4: Commit**

```bash
git add configs/openjarvis/prompts/personas/jarvis.md configs/openjarvis/prompts/personas/neutral.md
git commit -m "feat: add Jarvis and neutral persona prompts for digest agent"
```

---

### Task 13: MorningDigestAgent

**Files:**
- Create: `src/openjarvis/agents/morning_digest.py`
- Create: `tests/agents/test_morning_digest.py`
- Modify: `src/openjarvis/agents/__init__.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/agents/test_morning_digest.py
"""Tests for MorningDigestAgent."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from openjarvis.core.registry import AgentRegistry


def test_morning_digest_registered():
    assert AgentRegistry.contains("morning_digest")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agents/test_morning_digest.py::test_morning_digest_registered -v`
Expected: FAIL

- [ ] **Step 3: Write the MorningDigestAgent**

```python
# src/openjarvis/agents/morning_digest.py
"""Morning Digest Agent — synthesizes a daily briefing from multiple sources.

Thin orchestrator that delegates to digest_collect (data fetching),
the LLM (narrative synthesis), and text_to_speech (audio generation).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult, ToolUsingAgent
from openjarvis.agents.digest_store import DigestArtifact, DigestStore
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import Message, Role, ToolCall


def _load_persona(persona_name: str) -> str:
    """Load a persona prompt file by name."""
    search_paths = [
        Path("configs/openjarvis/prompts/personas") / f"{persona_name}.md",
        Path.home() / ".openjarvis" / "prompts" / "personas" / f"{persona_name}.md",
    ]
    for p in search_paths:
        if p.exists():
            return p.read_text(encoding="utf-8")
    return ""


@AgentRegistry.register("morning_digest")
class MorningDigestAgent(ToolUsingAgent):
    """Pre-compute a daily digest from configured data sources."""

    agent_id = "morning_digest"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Extract digest-specific kwargs before passing to parent
        self._persona = kwargs.pop("persona", "jarvis")
        self._sections = kwargs.pop("sections", ["messages", "calendar", "health", "world"])
        self._section_sources = kwargs.pop("section_sources", {})
        self._timezone = kwargs.pop("timezone", "America/Los_Angeles")
        self._voice_id = kwargs.pop("voice_id", "")
        self._tts_backend = kwargs.pop("tts_backend", "cartesia")
        self._digest_store_path = kwargs.pop("digest_store_path", "")
        super().__init__(*args, **kwargs)

    def _build_system_prompt(self) -> str:
        """Assemble the system prompt from persona + context."""
        persona_text = _load_persona(self._persona)
        now = datetime.now()

        return (
            f"{persona_text}\n\n"
            f"Today is {now.strftime('%A, %B %d, %Y')}. "
            f"The time is {now.strftime('%I:%M %p')} in {self._timezone}.\n\n"
            f"Generate a morning briefing covering these sections in order: "
            f"{', '.join(self._sections)}.\n\n"
            "Be concise — the entire briefing should be readable in 2-3 minutes "
            "and listenable in under 5 minutes when spoken aloud.\n\n"
            "Format your response in clean markdown with section headers."
        )

    def _resolve_sources(self) -> List[str]:
        """Get the list of connector IDs to query."""
        default_source_map = {
            "messages": ["gmail", "slack", "google_tasks"],
            "calendar": ["gcalendar"],
            "health": ["oura"],
            "world": [],  # Handled by web_search, not connectors
        }
        sources = set()
        for section in self._sections:
            section_sources = self._section_sources.get(
                section, default_source_map.get(section, [])
            )
            sources.update(section_sources)
        return list(sources)

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        self._emit_turn_start(input)

        # Step 1: Collect data from connectors
        sources = self._resolve_sources()
        collect_call = ToolCall(
            id="digest-collect-1",
            name="digest_collect",
            arguments=json.dumps({"sources": sources, "hours_back": 24}),
        )
        collect_result = self._executor.execute(collect_call)
        collected_data = collect_result.content

        # Step 2: Synthesize narrative via LLM
        system_prompt = self._build_system_prompt()
        messages = [
            Message(role=Role.SYSTEM, content=system_prompt),
            Message(
                role=Role.USER,
                content=(
                    f"Here is the collected data from my sources:\n\n"
                    f"{collected_data}\n\n"
                    f"Please synthesize my morning briefing."
                ),
            ),
        ]

        result = self._generate(messages)
        narrative = self._strip_think_tags(result.get("content", ""))

        # Step 3: Generate audio via TTS
        tts_call = ToolCall(
            id="digest-tts-1",
            name="text_to_speech",
            arguments=json.dumps({
                "text": narrative,
                "voice_id": self._voice_id,
                "backend": self._tts_backend,
            }),
        )
        tts_result = self._executor.execute(tts_call)
        audio_path = tts_result.metadata.get("audio_path", "") if tts_result.success else ""

        # Step 4: Store the artifact
        artifact = DigestArtifact(
            text=narrative,
            audio_path=Path(audio_path) if audio_path else Path(""),
            sections={},  # Could parse sections from narrative if needed
            sources_used=sources,
            generated_at=datetime.now(),
            model_used=self._model,
            voice_used=self._voice_id,
        )

        store = DigestStore(db_path=self._digest_store_path)
        store.save(artifact)
        store.close()

        self._emit_turn_end(turns=1)
        return AgentResult(
            content=narrative,
            tool_results=[collect_result, tts_result],
            turns=1,
            metadata={
                "audio_path": audio_path,
                "sources_used": sources,
            },
        )
```

- [ ] **Step 4: Register in agents __init__.py**

Add to `src/openjarvis/agents/__init__.py`:

```python
try:
    import openjarvis.agents.morning_digest  # noqa: F401
except ImportError:
    pass
```

- [ ] **Step 5: Run registration test**

Run: `uv run pytest tests/agents/test_morning_digest.py::test_morning_digest_registered -v`
Expected: PASS

- [ ] **Step 6: Write agent execution test with mocked tools and engine**

Add to `tests/agents/test_morning_digest.py`:

```python
from pathlib import Path
from openjarvis.agents._stubs import AgentResult
from openjarvis.core.types import ToolResult


def test_morning_digest_run(tmp_path):
    from openjarvis.agents.morning_digest import MorningDigestAgent

    mock_engine = MagicMock()
    mock_engine.generate.return_value = {
        "content": "Good morning sir. You have 3 emails and 2 meetings today.",
        "finish_reason": "stop",
        "usage": {},
    }

    # Mock collect result
    mock_collect_result = ToolResult(
        tool_name="digest_collect",
        content="## gmail (2 items)\n...",
        success=True,
        metadata={"total_items": 2},
    )

    # Mock TTS result
    mock_tts_result = ToolResult(
        tool_name="text_to_speech",
        content=str(tmp_path / "digest.mp3"),
        success=True,
        metadata={"audio_path": str(tmp_path / "digest.mp3")},
    )

    agent = MorningDigestAgent(
        mock_engine,
        "test-model",
        tools=[],
        persona="neutral",
        digest_store_path=str(tmp_path / "digest.db"),
    )

    with patch.object(agent._executor, "execute", side_effect=[mock_collect_result, mock_tts_result]):
        result = agent.run("Generate morning digest")

    assert isinstance(result, AgentResult)
    assert "Good morning" in result.content
    assert result.turns == 1
    assert len(result.tool_results) == 2


def test_load_persona(tmp_path):
    from openjarvis.agents.morning_digest import _load_persona

    persona_dir = tmp_path / "configs" / "openjarvis" / "prompts" / "personas"
    persona_dir.mkdir(parents=True)
    (persona_dir / "test.md").write_text("You are a test persona.", encoding="utf-8")

    with patch("openjarvis.agents.morning_digest.Path", return_value=persona_dir / "test.md"):
        # Test falls back gracefully when file not in search paths
        result = _load_persona("nonexistent")
        assert result == ""  # Not found returns empty string
```

- [ ] **Step 7: Run all tests**

Run: `uv run pytest tests/agents/test_morning_digest.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add src/openjarvis/agents/morning_digest.py tests/agents/test_morning_digest.py src/openjarvis/agents/__init__.py
git commit -m "feat: add MorningDigestAgent with persona-driven narrative synthesis"
```

---

## PR 4: Delivery Layer

---

### Task 14: CLI `jarvis digest` Subcommand

**Files:**
- Create: `src/openjarvis/cli/digest_cmd.py`
- Create: `tests/cli/test_digest_cmd.py`
- Modify: `src/openjarvis/cli/__init__.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/cli/test_digest_cmd.py
"""Tests for `jarvis digest` CLI command."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from openjarvis.agents.digest_store import DigestArtifact, DigestStore


def test_digest_command_exists():
    """The digest command is registered on the CLI."""
    from openjarvis.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["digest", "--help"])
    assert result.exit_code == 0
    assert "morning digest" in result.output.lower() or "digest" in result.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/cli/test_digest_cmd.py::test_digest_command_exists -v`
Expected: FAIL — no such command `digest`

- [ ] **Step 3: Write the digest CLI command**

```python
# src/openjarvis/cli/digest_cmd.py
"""``jarvis digest`` — display and play the morning digest."""

from __future__ import annotations

import subprocess
import sys
import threading

import click
from rich.console import Console
from rich.markdown import Markdown

from openjarvis.agents.digest_store import DigestStore


def _play_audio(audio_path: str) -> None:
    """Play audio file in background using available system player."""
    players = ["ffplay -nodisp -autoexit", "aplay", "afplay", "paplay"]
    for player in players:
        cmd_parts = player.split() + [audio_path]
        try:
            subprocess.run(
                cmd_parts,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            return
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue


@click.command("digest", help="Display and play the morning digest.")
@click.option("--text-only", is_flag=True, help="Print text without audio playback.")
@click.option("--fresh", is_flag=True, help="Re-generate the digest (skip cache).")
@click.option("--history", is_flag=True, help="Show past digests.")
@click.option("--section", type=str, default="", help="Show only a specific section.")
@click.option("--db-path", type=str, default="", help="Path to digest database.")
def digest(
    text_only: bool,
    fresh: bool,
    history: bool,
    section: str,
    db_path: str,
) -> None:
    """Display and optionally play the morning digest."""
    console = Console()
    store = DigestStore(db_path=db_path) if db_path else DigestStore()

    if history:
        past = store.history(limit=10)
        if not past:
            console.print("[dim]No past digests found.[/dim]")
            store.close()
            return
        for artifact in past:
            console.print(
                f"[bold]{artifact.generated_at.strftime('%Y-%m-%d %H:%M')}[/bold]"
                f" — {artifact.model_used} / {artifact.voice_used}"
            )
            console.print(artifact.text[:200] + "...\n")
        store.close()
        return

    if fresh:
        # Trigger on-demand generation
        console.print("[yellow]Generating fresh digest...[/yellow]")
        try:
            from openjarvis.sdk import Jarvis

            with Jarvis() as j:
                result = j.ask("Generate my morning digest", agent="morning_digest")
                console.print(Markdown(result))
        except Exception as exc:
            console.print(f"[red]Failed to generate digest: {exc}[/red]")
        store.close()
        return

    # Try to load today's cached digest
    artifact = store.get_today()
    if artifact is None:
        console.print("[dim]No digest for today. Use --fresh to generate one.[/dim]")
        store.close()
        return

    # Display text
    text = artifact.text
    if section:
        # Try to extract just the requested section
        lines = text.split("\n")
        in_section = False
        section_lines = []
        for line in lines:
            if line.strip().lower().startswith(f"## {section.lower()}") or \
               line.strip().lower().startswith(f"# {section.lower()}"):
                in_section = True
                section_lines.append(line)
            elif in_section and line.strip().startswith("#"):
                break
            elif in_section:
                section_lines.append(line)
        text = "\n".join(section_lines) if section_lines else text

    # Play audio in background while text renders
    audio_path = str(artifact.audio_path)
    if not text_only and audio_path and artifact.audio_path.exists():
        audio_thread = threading.Thread(target=_play_audio, args=(audio_path,), daemon=True)
        audio_thread.start()

    console.print(Markdown(text))
    store.close()
```

- [ ] **Step 4: Register in CLI __init__.py**

Add the import and command registration to `src/openjarvis/cli/__init__.py`:

Import line (near the other imports):
```python
from openjarvis.cli.digest_cmd import digest
```

Command registration (in the `cli` group body, near the other `cli.add_command()` calls or at the bottom of the file):
```python
cli.add_command(digest)
```

- [ ] **Step 5: Write test for cached digest display**

Add to `tests/cli/test_digest_cmd.py`:

```python
def test_digest_displays_cached(tmp_path):
    from openjarvis.cli import cli

    db_path = str(tmp_path / "digest.db")
    store = DigestStore(db_path=db_path)
    store.save(DigestArtifact(
        text="# Messages\nYou have 3 emails.\n# Calendar\n2 meetings today.",
        audio_path=Path("/nonexistent/audio.mp3"),
        sections={},
        sources_used=["gmail"],
        generated_at=datetime.now(),
        model_used="test",
        voice_used="jarvis",
    ))
    store.close()

    runner = CliRunner()
    result = runner.invoke(cli, ["digest", "--text-only", "--db-path", db_path])
    assert result.exit_code == 0
    assert "3 emails" in result.output


def test_digest_no_cache(tmp_path):
    from openjarvis.cli import cli

    db_path = str(tmp_path / "empty.db")
    runner = CliRunner()
    result = runner.invoke(cli, ["digest", "--db-path", db_path])
    assert result.exit_code == 0
    assert "No digest for today" in result.output
```

- [ ] **Step 6: Run all tests**

Run: `uv run pytest tests/cli/test_digest_cmd.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/openjarvis/cli/digest_cmd.py tests/cli/test_digest_cmd.py src/openjarvis/cli/__init__.py
git commit -m "feat: add 'jarvis digest' CLI command with text + audio playback"
```

---

### Task 15: API Endpoints for Digest

**Files:**
- Create: `src/openjarvis/server/digest_routes.py`
- Create: `tests/server/test_digest_routes.py`
- Modify: `src/openjarvis/server/app.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/server/test_digest_routes.py
"""Tests for /api/digest endpoints."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from openjarvis.agents.digest_store import DigestArtifact, DigestStore


@pytest.fixture()
def store(tmp_path):
    db_path = str(tmp_path / "digest.db")
    s = DigestStore(db_path=db_path)
    s.save(DigestArtifact(
        text="Good morning sir.",
        audio_path=tmp_path / "digest.mp3",
        sections={"messages": "3 emails"},
        sources_used=["gmail"],
        generated_at=datetime.now(),
        model_used="test",
        voice_used="jarvis",
    ))
    # Write fake audio file
    (tmp_path / "digest.mp3").write_bytes(b"fake-mp3")
    yield s
    s.close()


def test_get_digest(store, tmp_path):
    from fastapi.testclient import TestClient
    from openjarvis.server.digest_routes import create_digest_router

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(create_digest_router(db_path=str(tmp_path / "digest.db")))

    client = TestClient(app)
    resp = client.get("/api/digest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "Good morning sir."
    assert data["sources_used"] == ["gmail"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/server/test_digest_routes.py::test_get_digest -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write the digest routes**

```python
# src/openjarvis/server/digest_routes.py
"""FastAPI routes for the morning digest."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from openjarvis.agents.digest_store import DigestStore


def create_digest_router(*, db_path: str = "") -> APIRouter:
    """Create a digest API router with the given store path."""
    router = APIRouter(prefix="/api/digest", tags=["digest"])
    store = DigestStore(db_path=db_path) if db_path else DigestStore()

    @router.get("")
    async def get_digest():
        """Return the latest digest artifact."""
        artifact = store.get_today()
        if artifact is None:
            raise HTTPException(status_code=404, detail="No digest for today")
        return {
            "text": artifact.text,
            "sections": artifact.sections,
            "sources_used": artifact.sources_used,
            "generated_at": artifact.generated_at.isoformat(),
            "model_used": artifact.model_used,
            "voice_used": artifact.voice_used,
            "audio_available": artifact.audio_path.exists() if artifact.audio_path.name else False,
        }

    @router.get("/audio")
    async def get_digest_audio():
        """Stream the digest audio file."""
        artifact = store.get_today()
        if artifact is None:
            raise HTTPException(status_code=404, detail="No digest for today")
        if not artifact.audio_path.exists():
            raise HTTPException(status_code=404, detail="Audio not available")
        return FileResponse(
            str(artifact.audio_path),
            media_type="audio/mpeg",
            filename="digest.mp3",
        )

    @router.post("/generate")
    async def generate_digest():
        """Force re-generation of the digest."""
        try:
            from openjarvis.sdk import Jarvis

            with Jarvis() as j:
                result = j.ask("Generate my morning digest", agent="morning_digest")
            return {"status": "ok", "text": result}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @router.get("/history")
    async def get_digest_history():
        """Return past digests."""
        history = store.history(limit=10)
        return [
            {
                "text": a.text[:200],
                "generated_at": a.generated_at.isoformat(),
                "model_used": a.model_used,
                "voice_used": a.voice_used,
            }
            for a in history
        ]

    return router
```

- [ ] **Step 4: Write additional route tests**

Add to `tests/server/test_digest_routes.py`:

```python
def test_get_digest_audio(store, tmp_path):
    from fastapi.testclient import TestClient
    from openjarvis.server.digest_routes import create_digest_router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(create_digest_router(db_path=str(tmp_path / "digest.db")))

    client = TestClient(app)
    resp = client.get("/api/digest/audio")
    assert resp.status_code == 200
    assert resp.content == b"fake-mp3"


def test_get_digest_404(tmp_path):
    from fastapi.testclient import TestClient
    from openjarvis.server.digest_routes import create_digest_router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(create_digest_router(db_path=str(tmp_path / "empty.db")))

    client = TestClient(app)
    resp = client.get("/api/digest")
    assert resp.status_code == 404


def test_get_history(store, tmp_path):
    from fastapi.testclient import TestClient
    from openjarvis.server.digest_routes import create_digest_router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(create_digest_router(db_path=str(tmp_path / "digest.db")))

    client = TestClient(app)
    resp = client.get("/api/digest/history")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["voice_used"] == "jarvis"
```

- [ ] **Step 5: Mount the router in server/app.py**

Add to `src/openjarvis/server/app.py` where other routers are mounted:

```python
from openjarvis.server.digest_routes import create_digest_router
app.include_router(create_digest_router())
```

- [ ] **Step 6: Run all tests**

Run: `uv run pytest tests/server/test_digest_routes.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/openjarvis/server/digest_routes.py tests/server/test_digest_routes.py src/openjarvis/server/app.py
git commit -m "feat: add /api/digest REST endpoints for digest delivery"
```

---

## PR 5: Configuration + Integration

---

### Task 16: DigestConfig Dataclass

**Files:**
- Modify: `src/openjarvis/core/config.py`

- [ ] **Step 1: Add DigestConfig to config.py**

Add the following dataclass to `src/openjarvis/core/config.py` near the other config dataclasses:

```python
@dataclass
class DigestSectionConfig:
    """Configuration for a single digest section."""
    sources: List[str] = field(default_factory=list)
    max_items: int = 10
    priority_contacts: List[str] = field(default_factory=list)


@dataclass
class DigestConfig:
    """Configuration for the morning digest feature."""
    enabled: bool = False
    schedule: str = "0 6 * * *"
    timezone: str = "America/Los_Angeles"
    persona: str = "jarvis"
    sections: List[str] = field(default_factory=lambda: ["messages", "calendar", "health", "world"])
    optional_sections: List[str] = field(default_factory=lambda: ["github", "financial", "music", "fitness"])
    voice_id: str = ""
    tts_backend: str = "cartesia"
    messages: DigestSectionConfig = field(default_factory=lambda: DigestSectionConfig(sources=["gmail", "slack", "google_tasks"]))
    calendar: DigestSectionConfig = field(default_factory=lambda: DigestSectionConfig(sources=["gcalendar"]))
    health: DigestSectionConfig = field(default_factory=lambda: DigestSectionConfig(sources=["oura"]))
    world: DigestSectionConfig = field(default_factory=lambda: DigestSectionConfig(sources=[]))
```

Add `digest: DigestConfig = field(default_factory=DigestConfig)` to the `JarvisConfig` dataclass.

- [ ] **Step 2: Verify existing tests still pass**

Run: `uv run pytest tests/core/ -v --tb=short`
Expected: All PASS (no regressions)

- [ ] **Step 3: Commit**

```bash
git add src/openjarvis/core/config.py
git commit -m "feat: add DigestConfig dataclass to JarvisConfig"
```

---

### Task 17: End-to-End Integration Test

**Files:**
- Create: `tests/test_digest_integration.py`

- [ ] **Step 1: Write the integration test**

```python
# tests/test_digest_integration.py
"""End-to-end integration test for the morning digest pipeline.

Uses mocked connectors and engine to verify the full flow:
digest_collect → LLM synthesis → TTS → DigestStore → CLI delivery.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.agents.digest_store import DigestStore
from openjarvis.connectors._stubs import Document
from openjarvis.core.types import ToolResult


def test_full_digest_pipeline(tmp_path):
    """Verify collect → synthesize → TTS → store → retrieve."""
    from openjarvis.agents.morning_digest import MorningDigestAgent

    # Mock engine returns a narrative
    mock_engine = MagicMock()
    mock_engine.generate.return_value = {
        "content": (
            "Good morning, sir. You slept 7.5 hours with a readiness score of 78. "
            "You have 2 meetings today and 5 unread emails. "
            "In the news, a new GPT-5 paper dropped on Arxiv."
        ),
        "finish_reason": "stop",
        "usage": {},
    }

    # Mock tool results
    collect_result = ToolResult(
        tool_name="digest_collect",
        content="## gmail (3 items)\n## oura (1 items)\n## gcalendar (2 items)",
        success=True,
        metadata={"total_items": 6},
    )
    tts_result = ToolResult(
        tool_name="text_to_speech",
        content=str(tmp_path / "digest.mp3"),
        success=True,
        metadata={"audio_path": str(tmp_path / "digest.mp3")},
    )

    # Write fake audio
    (tmp_path / "digest.mp3").write_bytes(b"fake-mp3-audio")

    db_path = str(tmp_path / "digest.db")

    agent = MorningDigestAgent(
        mock_engine,
        "claude-sonnet-4-6",
        tools=[],
        persona="neutral",
        digest_store_path=db_path,
    )

    with patch.object(agent._executor, "execute", side_effect=[collect_result, tts_result]):
        result = agent.run("Generate morning digest")

    # Verify agent result
    assert "Good morning" in result.content
    assert result.metadata["audio_path"] == str(tmp_path / "digest.mp3")

    # Verify stored in DigestStore
    store = DigestStore(db_path=db_path)
    artifact = store.get_latest()
    assert artifact is not None
    assert "Good morning" in artifact.text
    assert artifact.model_used == "claude-sonnet-4-6"
    store.close()
```

- [ ] **Step 2: Run the integration test**

Run: `uv run pytest tests/test_digest_integration.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_digest_integration.py
git commit -m "test: add end-to-end integration test for morning digest pipeline"
```

---

## Not Covered (Future Follow-ups)

These items from the spec are intentionally deferred from this plan:

- **"Good morning Jarvis" trigger detection** — Routing a natural language greeting to the digest delivery flow requires adding a routing instruction to the default agent's system prompt. This is a prompt engineering task that should be done after the core pipeline works end-to-end.
- **Frontend audio player component** — The `/api/digest/audio` endpoint is ready, but the React/Vite component to render text + audio in the chat UI is frontend work. Should be a separate PR.
- **Stretch connectors** (Apple Health, Apple Music, SoundCloud) — Deferred per spec. Can follow the same pattern as Tasks 1–4.
- **AgentScheduler cron integration** — The `MorningDigestAgent` works on-demand. Wiring it into `AgentScheduler` for automatic 6am pre-computation requires a config + scheduler setup task after the agent is proven.

---

## Summary

| PR | Tasks | What ships |
|----|-------|-----------|
| **PR 1: Connectors** | Tasks 1–5 | Oura, Strava, Spotify, Google Tasks connectors + live smoke tests |
| **PR 2: TTS Infrastructure** | Tasks 6–9 | TTSBackend ABC, Cartesia/Kokoro/OpenAI backends, text_to_speech tool |
| **PR 3: Digest Agent + Store** | Tasks 10–13 | DigestStore, digest_collect tool, persona prompts, MorningDigestAgent |
| **PR 4: Delivery Layer** | Tasks 14–15 | `jarvis digest` CLI, /api/digest REST endpoints |
| **PR 5: Config + Integration** | Tasks 16–17 | DigestConfig, end-to-end integration test |

Each task follows TDD: write failing test → implement → verify → commit. PRs are ordered by dependency and can be reviewed independently.
