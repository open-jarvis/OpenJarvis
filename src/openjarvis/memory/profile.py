"""Profile curator: keep USER.md and MEMORY.md up to date from learned facts.

The memory service extracts short facts from conversations into the fact store.
``SystemPromptBuilder`` puts ``USER.md`` (who the user is, preferences) and
``MEMORY.md`` (ongoing projects, plans, decisions) into every prompt, but
nothing kept those files current. The curator closes that loop: in the
background it waits for new trusted facts, then asks the model to merge them
into both files - rewriting, de-duplicating and dropping stale lines - so
Jarvis remembers across restarts without the prompt growing without bound.

* Runs at most every ``interval_seconds`` and only when new facts arrived.
* Facts flagged ``untrusted`` by the memory service are never used.
* The previous versions are copied to ``memory_backups/`` before each rewrite.
* Each file is capped at ``max_chars``.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_INTERVAL_SECONDS = 600
_MIN_NEW_FACTS = 2
_MAX_FACTS_IN_PROMPT = 80
_MAX_CHARS = 3000
_MAX_BACKUPS = 20

_PROMPT = """You maintain two short memory files for a personal AI assistant \
called Jarvis.

USER.md - durable facts about the user: name, location, work, family, \
preferences, habits, likes/dislikes, how they want Jarvis to behave.
MEMORY.md - ongoing context: current projects, plans, goals, decisions, \
upcoming events, things Jarvis promised to follow up on.

Merge the NEW FACTS into the CURRENT FILES and output both files in full.
Rules:
- Every bullet must restate a line from the CURRENT FILES or one NEW FACT, \
in plain words. Do NOT add interpretations, likes, habits, personality \
traits, advice, action items or follow-ups that are not literally stated.
- Keep every still-valid existing line; update lines the new facts change; \
remove duplicates and anything clearly outdated.
- Write about the user in the third person ("Lives in Kochi").
- Use "- " bullets under short "## " headings; leave out empty headings.
- Each file under {max_chars} characters. Never include secrets \
(passwords, card numbers, keys).

CURRENT USER.md:
{user_md}

CURRENT MEMORY.md:
{memory_md}

NEW FACTS (oldest first):
{facts}

Reply with exactly this layout and nothing else:
===USER.md===
<full new USER.md>
===MEMORY.md===
<full new MEMORY.md>
"""

_SECTION = re.compile(r"===\s*(USER|MEMORY)\.md\s*===\s*\n", re.IGNORECASE)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def parse_curated(text: str) -> Optional[Tuple[str, str]]:
    """Split model output into (user_md, memory_md); None if malformed."""
    text = _THINK.sub("", text or "")
    parts = _SECTION.split(text)
    # parts = [preamble, "USER", body, "MEMORY", body]
    found = {}
    for i in range(1, len(parts) - 1, 2):
        found[parts[i].upper()] = parts[i + 1].strip().strip("`").strip()
    user_md, memory_md = found.get("USER"), found.get("MEMORY")
    if not user_md or not memory_md:
        return None
    return user_md, memory_md


class ProfileCurator:
    """Background thread that rewrites USER.md / MEMORY.md from new facts."""

    def __init__(
        self,
        engine: Any,
        model: str,
        list_facts: Callable[[], List[Any]],
        *,
        user_path: Path,
        memory_path: Path,
        state_dir: Path,
        interval_seconds: int = _DEFAULT_INTERVAL_SECONDS,
        min_new_facts: int = _MIN_NEW_FACTS,
        max_chars: int = _MAX_CHARS,
    ) -> None:
        self._engine = engine
        self._model = model
        self._list_facts = list_facts
        self._user_path = Path(user_path).expanduser()
        self._memory_path = Path(memory_path).expanduser()
        self._state_path = Path(state_dir) / "profile_state.json"
        self._backup_dir = Path(state_dir) / "memory_backups"
        self._interval = max(60, int(interval_seconds))
        self._min_new = max(1, int(min_new_facts))
        self._max_chars = max_chars
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="jarvis-profile-curator"
        )
        self._thread.start()
        logger.info("Profile curator started (every %ds)", self._interval)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _loop(self) -> None:
        # First pass shortly after start-up, then on the interval.
        if self._stop.wait(timeout=30):
            return
        while not self._stop.is_set():
            try:
                self.curate()
            except Exception:
                logger.exception("Profile curation failed")
            self._stop.wait(timeout=self._interval)

    # -- state ------------------------------------------------------------

    def _last_ts(self) -> float:
        try:
            return float(
                json.loads(_read(self._state_path) or "{}").get("last_fact_ts", 0)
            )
        except (ValueError, TypeError):
            return 0.0

    def _save_state(self, last_ts: float) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps(
                {
                    "last_fact_ts": last_ts,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def _backup(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        for src in (self._user_path, self._memory_path):
            if src.exists():
                shutil.copy2(src, self._backup_dir / f"{src.stem}-{stamp}.md")
        backups = sorted(self._backup_dir.glob("*.md"))
        for old in backups[: max(0, len(backups) - _MAX_BACKUPS * 2)]:
            old.unlink(missing_ok=True)

    # -- work ---------------------------------------------------------------

    def pending_facts(self) -> List[Any]:
        since = self._last_ts()
        facts = [
            f
            for f in self._list_facts()
            if getattr(f, "trusted_for_recall", True)
            and float(getattr(f, "created_at", 0) or 0) > since
        ]
        facts.sort(key=lambda f: float(getattr(f, "created_at", 0) or 0))
        return facts

    def curate(self, *, force: bool = False) -> bool:
        """Merge new facts into the files. Returns True if they were rewritten."""
        with self._lock:
            facts = self.pending_facts()
            if not facts or (len(facts) < self._min_new and not force):
                return False
            batch = facts[-_MAX_FACTS_IN_PROMPT:]
            prompt = _PROMPT.format(
                max_chars=self._max_chars,
                user_md=_read(self._user_path).strip() or "# User Profile\n",
                memory_md=_read(self._memory_path).strip() or "# Agent Memory\n",
                facts="\n".join(f"- {f.text}" for f in batch),
            )
            from openjarvis.core.types import Message, Role

            result = self._engine.generate(
                [Message(role=Role.USER, content=prompt)],
                model=self._model,
                temperature=0.2,
                max_tokens=4096,
            )
            parsed = parse_curated(str(result.get("content") or ""))
            if parsed is None:
                logger.warning(
                    "Profile curator: model reply not in the expected layout"
                )
                return False
            user_md, memory_md = (
                part[: self._max_chars].rstrip() + "\n" for part in parsed
            )
            self._backup()
            self._user_path.parent.mkdir(parents=True, exist_ok=True)
            self._user_path.write_text(user_md, encoding="utf-8")
            self._memory_path.write_text(memory_md, encoding="utf-8")
            newest = max(float(getattr(f, "created_at", 0) or 0) for f in facts)
            self._save_state(newest)
            logger.info(
                "Profile curator merged %d fact(s) into USER.md / MEMORY.md", len(facts)
            )
            return True


def build_profile_curator(
    config: Any, engine: Any, model: str, memory_service: Any
) -> Optional[ProfileCurator]:
    """Create the curator when the memory service is running, else None."""
    if memory_service is None or engine is None or not model:
        return None
    from openjarvis.core.paths import get_config_dir

    files = getattr(config, "memory_files", None)
    base = get_config_dir()
    user_path = Path(getattr(files, "user_path", "") or base / "USER.md")
    memory_path = Path(getattr(files, "memory_path", "") or base / "MEMORY.md")
    extraction_model = getattr(getattr(config, "memory", None), "extraction_model", "")
    return ProfileCurator(
        engine,
        extraction_model or model,
        memory_service.list_facts,
        user_path=user_path,
        memory_path=memory_path,
        state_dir=base,
    )


__all__ = ["ProfileCurator", "build_profile_curator", "parse_curated"]
