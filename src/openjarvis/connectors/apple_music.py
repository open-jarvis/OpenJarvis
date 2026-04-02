"""Apple Music connector -- reads tracks from the local Music.app via AppleScript.

Uses ``osascript`` subprocess calls to query Music.app on macOS.  No API keys
or network access required; everything stays local.

Requires macOS (``sys.platform == "darwin"``) and the Music app to be
available.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import sys
from datetime import datetime
from typing import Iterator, Optional

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.core.registry import ConnectorRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AppleScript helpers
# ---------------------------------------------------------------------------

_LIBRARY_CHECK_SCRIPT = 'tell application "Music" to get name of playlist "Library"'

_TRACKS_SCRIPT = """
tell application "Music"
    set output to ""
    set allTracks to every track of playlist "Library"
    repeat with t in allTracks
        set trackName to name of t
        set trackArtist to artist of t
        set trackAlbum to album of t
        set trackDuration to duration of t
        set trackGenre to genre of t
        set trackPlayCount to played count of t
        try
            set pd to played date of t as string
        on error
            set pd to "never"
        end try
        set sep to "|||"
        set row to trackName & sep & trackArtist & sep & trackAlbum
        set row to row & sep & trackDuration & sep & trackGenre
        set row to row & sep & trackPlayCount & sep & pd
        set output to output & row & linefeed
    end repeat
    return output
end tell
"""


def _run_osascript(script: str, *, timeout: int = 120) -> Optional[str]:
    """Execute an AppleScript via ``osascript`` and return stdout.

    Returns None on failure.
    """
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        logger.debug("osascript failed (rc=%d): %s", result.returncode, result.stderr)
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.debug("osascript error: %s", exc)
        return None


def _track_doc_id(name: str, artist: str) -> str:
    """Deterministic doc_id from track name + artist."""
    key = f"{name}:{artist}"
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    return f"apple_music-{h}"


def _parse_played_date(raw: str) -> Optional[datetime]:
    """Try to parse an AppleScript date string; return None if unparseable."""
    if not raw or raw.strip().lower() == "never":
        return None
    # AppleScript renders dates in the user's locale.  Common macOS formats:
    # "Saturday, March 15, 2026 at 2:30:00 PM"
    # "2026-03-15 14:30:00"
    for fmt in (
        "%A, %B %d, %Y at %I:%M:%S %p",
        "%A, %B %d, %Y at %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%m/%d/%Y %I:%M:%S %p",
        "%d/%m/%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(raw.strip(), fmt)
        except ValueError:
            continue
    logger.debug("Could not parse played_date: %r", raw)
    return None


# ---------------------------------------------------------------------------
# AppleMusicConnector
# ---------------------------------------------------------------------------


@ConnectorRegistry.register("apple_music")
class AppleMusicConnector(BaseConnector):
    """Read tracks from the local Music.app library via AppleScript.

    Only works on macOS where ``osascript`` is available and Music.app is
    installed (ships with the OS).
    """

    connector_id = "apple_music"
    display_name = "Apple Music"
    auth_type = "local"

    def __init__(self) -> None:
        self._status = SyncStatus()

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Return True if running on macOS and Music.app responds."""
        if sys.platform != "darwin":
            return False
        result = _run_osascript(_LIBRARY_CHECK_SCRIPT, timeout=10)
        return result is not None

    def disconnect(self) -> None:
        """No-op -- local connector with no credentials to revoke."""

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,  # noqa: ARG002
    ) -> Iterator[Document]:
        """Query Music.app for all tracks and yield one Document per track.

        Parameters
        ----------
        since:
            If provided, only yield tracks whose last-played date is after
            this datetime.
        cursor:
            Not used for this local connector (included for API
            compatibility).

        Yields
        ------
        Document
            One document per track in the Music library.
        """
        raw = _run_osascript(_TRACKS_SCRIPT)
        if raw is None:
            logger.warning("Could not retrieve tracks from Music.app")
            self._status.state = "error"
            self._status.error = "AppleScript query failed"
            return

        lines = [line for line in raw.split("\n") if line.strip()]
        self._status.items_total = len(lines)
        synced = 0

        for line in lines:
            parts = line.split("|||")
            if len(parts) < 7:
                logger.debug("Skipping malformed line: %r", line)
                continue

            name = parts[0].strip()
            artist = parts[1].strip()
            album = parts[2].strip()
            duration_raw = parts[3].strip()
            genre = parts[4].strip()
            play_count_raw = parts[5].strip()
            played_date_raw = parts[6].strip()

            # Parse numeric fields
            try:
                duration_s = round(float(duration_raw), 2)
            except (ValueError, TypeError):
                duration_s = 0.0
            try:
                play_count = int(play_count_raw)
            except (ValueError, TypeError):
                play_count = 0

            played_date = _parse_played_date(played_date_raw)
            timestamp = played_date if played_date else datetime.now()

            # Apply since filter
            if since is not None and played_date is not None:
                if played_date <= since:
                    continue

            track_data = {
                "name": name,
                "artist": artist,
                "album": album,
                "duration_s": duration_s,
                "genre": genre,
                "play_count": play_count,
                "played_date": played_date_raw,
            }

            doc = Document(
                doc_id=_track_doc_id(name, artist),
                source="apple_music",
                doc_type="track",
                content=json.dumps(track_data),
                title=f"{name} \u2014 {artist}",
                author=artist,
                timestamp=timestamp,
                metadata={
                    "album": album,
                    "duration_s": duration_s,
                    "genre": genre,
                    "play_count": play_count,
                },
            )
            synced += 1
            yield doc

        self._status.items_synced = synced
        self._status.state = "idle"
        self._status.last_sync = datetime.now()
        self._status.error = None

    def sync_status(self) -> SyncStatus:
        """Return sync progress from the most recent :meth:`sync` call."""
        return self._status
