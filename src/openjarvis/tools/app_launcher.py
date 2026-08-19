"""App Launcher tool — open/close already-installed desktop applications by name.

Discovers installed programs from the OS's own registries of installed
software (Windows: the ``App Paths`` registry key and Start Menu shortcuts)
rather than depending on a hardcoded path. Deliberately narrow in scope:

- Never installs new software (no "install" action exists at all).
- Never runs a file the caller supplies directly — the only input is a free-
  text ``app_name``; every launchable path comes from OS-level discovery of
  *already installed* programs, never from an arbitrary caller-provided path.
- Never requests administrator elevation (plain, unelevated process start).

Currently implements full discovery on Windows (the ``sys.platform`` this
project is being used on); macOS/Linux fall back to a minimal PATH-only
lookup rather than crashing.
"""

from __future__ import annotations

import difflib
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AppEntry:
    """A discovered installed application (or a running process, for close)."""

    name: str
    path: str
    source: str = ""  # "app_paths" | "start_menu" | "path" | "process"


@dataclass(slots=True)
class MatchOutcome:
    """Result of matching a spoken/typed name against discovered candidates."""

    status: str  # "found" | "not_found" | "ambiguous"
    match: Optional[AppEntry] = None
    candidates: List[AppEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Nickname normalization — maps a spoken generic term to search terms or a
# well-known OS command name (never a hardcoded absolute install path).
# ---------------------------------------------------------------------------

_DEFAULT_BROWSER_TERMS = {"navegador", "navegador padrao", "browser", "default browser"}

_ALIASES: Dict[str, List[str]] = {
    "calculadora": ["calc", "calculator"],
    "calculator": ["calc", "calculator"],
    "bloco de notas": ["notepad"],
    "notepad": ["notepad"],
    "paint": ["mspaint", "paint"],
    "explorador de arquivos": ["explorer", "file explorer"],
    "file explorer": ["explorer", "file explorer"],
    "terminal": ["windows terminal", "wt"],
    "prompt de comando": ["cmd"],
    "chrome": ["chrome", "google chrome"],
    "google chrome": ["chrome", "google chrome"],
    "edge": ["msedge", "microsoft edge"],
    "microsoft edge": ["msedge", "microsoft edge"],
    "firefox": ["firefox", "mozilla firefox"],
    "word": ["winword", "microsoft word"],
    "excel": ["excel", "microsoft excel"],
    "vscode": ["code", "visual studio code"],
    "vs code": ["code", "visual studio code"],
    "visual studio code": ["code", "visual studio code"],
}


def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def _normalize(text: str) -> str:
    text = _strip_accents((text or "").strip().lower())
    text = re.sub(r"\.(exe|lnk|app)$", "", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _expand_query_terms(query: str) -> List[str]:
    norm = _normalize(query)
    terms = [norm]
    if norm in _ALIASES:
        terms.extend(_normalize(t) for t in _ALIASES[norm])
    return terms


def is_default_browser_query(app_name: str) -> bool:
    return _normalize(app_name) in _DEFAULT_BROWSER_TERMS


# ---------------------------------------------------------------------------
# Discovery — Windows: App Paths registry + Start Menu shortcuts + PATH.
# Best-effort PATH-only fallback on other platforms.
# ---------------------------------------------------------------------------


def _discover_app_paths_registry() -> List[AppEntry]:
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []

    entries: List[AppEntry] = []
    roots = [
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths",
        ),
        (
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths",
        ),
    ]
    for hive, subkey in roots:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                i = 0
                while True:
                    try:
                        name = winreg.EnumKey(key, i)
                    except OSError:
                        break
                    i += 1
                    try:
                        with winreg.OpenKey(key, name) as app_key:
                            path, _ = winreg.QueryValueEx(app_key, "")
                    except OSError:
                        continue
                    if path:
                        display = re.sub(r"\.exe$", "", name, flags=re.IGNORECASE)
                        entries.append(
                            AppEntry(name=display, path=path, source="app_paths")
                        )
        except OSError:
            continue
    return entries


def _start_menu_dirs() -> List[Path]:
    dirs: List[Path] = []
    program_data = os.environ.get("ProgramData")
    if program_data:
        dirs.append(
            Path(program_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        )
    app_data = os.environ.get("APPDATA")
    if app_data:
        dirs.append(
            Path(app_data) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        )
    return [d for d in dirs if d.is_dir()]


def _resolve_shortcut_target(lnk_path: str) -> Optional[str]:
    """Resolve a .lnk shortcut's target path via the Windows Shell COM API."""
    try:
        import win32com.client  # type: ignore[import-not-found]

        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(lnk_path)
        target = shortcut.Targetpath
        return target or None
    except Exception:  # noqa: BLE001 - pywin32 missing, or a malformed shortcut
        return None


def _discover_start_menu_apps() -> List[AppEntry]:
    if sys.platform != "win32":
        return []
    entries: List[AppEntry] = []
    for base in _start_menu_dirs():
        try:
            lnk_files = list(base.rglob("*.lnk"))
        except OSError:
            continue
        for lnk in lnk_files:
            target = _resolve_shortcut_target(str(lnk))
            if not target:
                continue
            entries.append(AppEntry(name=lnk.stem, path=target, source="start_menu"))
    return entries


# Small in-memory cache: Start Menu scanning resolves each shortcut via COM,
# which has real per-call overhead — avoid re-scanning on every tool call.
_CACHE_TTL_SECONDS = 300.0
_discovery_cache: Optional[Tuple[float, List[AppEntry]]] = None


def discover_apps(*, force_refresh: bool = False) -> List[AppEntry]:
    """Return all discovered installed applications (cached for a few minutes)."""
    global _discovery_cache
    now = time.time()
    if (
        not force_refresh
        and _discovery_cache is not None
        and now - _discovery_cache[0] < _CACHE_TTL_SECONDS
    ):
        return _discovery_cache[1]

    entries = _discover_app_paths_registry() + _discover_start_menu_apps()
    _discovery_cache = (now, entries)
    return entries


# ---------------------------------------------------------------------------
# Matching — pure functions, independent of discovery, for easy testing.
# ---------------------------------------------------------------------------


def find_app(query: str, candidates: List[AppEntry]) -> MatchOutcome:
    """Match *query* (a free-text app name) against discovered *candidates*.

    Three ordered phases, each trying exact-then-substring matching only
    (no fuzzy matching yet):
      1. The raw query term alone.
      2. Alias-expansion terms (e.g. "calculadora" -> "calc"), only if (1)
         found nothing — this matters for ambiguity: if the user says
         "chrome" and both "Google Chrome" and "Google Chrome Canary" are
         installed, the raw term "chrome" substring-matches both and
         correctly asks which one; pulling in an alias's exact-match term
         at the same time would instead silently pick one and hide the
         other.
      4. Fuzzy matching (difflib) against every term (raw + alias) combined,
         tried last and only when phases 1-2 found nothing at all — kept
         separate from the earlier phases because a lenient fuzzy cutoff can
         produce coincidental false positives (e.g. "calculadora" ~ "CapCut")
         that would otherwise block a perfectly good alias match.
    """
    if not candidates:
        return MatchOutcome(status="not_found")

    raw_term = _normalize(query)
    if not raw_term:
        return MatchOutcome(status="not_found")

    outcome = _match_precise([raw_term], candidates)
    if outcome.status != "not_found":
        return outcome

    alias_terms = [_normalize(t) for t in _ALIASES.get(raw_term, []) if t]
    if alias_terms:
        outcome = _match_precise(alias_terms, candidates)
        if outcome.status != "not_found":
            return outcome

    # Fuzzy matching is deliberately only tried against the user's own raw
    # term, never against alias terms — an alias is already a precise,
    # curated name; if it has no exact/substring match, that means the app
    # genuinely isn't discoverable, and fuzzy-matching a short alias like
    # "calc" against unrelated app names produces false positives (e.g.
    # "calc"/"calculator" ~ "CapCut" both score above a 0.6 cutoff).
    return _match_fuzzy([raw_term], candidates)


def _match_precise(terms: List[str], candidates: List[AppEntry]) -> MatchOutcome:
    """Exact, then substring, matching for *terms* against *candidates*."""
    terms = [t for t in terms if t]
    if not terms:
        return MatchOutcome(status="not_found")

    exact = _unique_by_path([c for c in candidates if _normalize(c.name) in terms])
    if exact:
        return _group_outcome(exact)

    substring_matches = _unique_by_path(
        [
            c
            for c in candidates
            if any(
                t in (norm_name := _normalize(c.name)) or norm_name in t for t in terms
            )
        ]
    )
    if substring_matches:
        return _group_outcome(substring_matches)

    return MatchOutcome(status="not_found")


def _match_fuzzy(terms: List[str], candidates: List[AppEntry]) -> MatchOutcome:
    """Fuzzy (difflib) matching for *terms* against *candidates* — last resort."""
    name_to_entries: Dict[str, List[AppEntry]] = {}
    for c in candidates:
        name_to_entries.setdefault(_normalize(c.name), []).append(c)

    fuzzy_matches: List[AppEntry] = []
    for term in terms:
        close = difflib.get_close_matches(
            term, list(name_to_entries.keys()), n=5, cutoff=0.6
        )
        for name in close:
            fuzzy_matches.extend(name_to_entries[name])

    fuzzy_matches = _unique_by_path(fuzzy_matches)[:5]
    if fuzzy_matches:
        return _group_outcome(fuzzy_matches)
    return MatchOutcome(status="not_found")


def _unique_by_path(entries: List[AppEntry]) -> List[AppEntry]:
    seen: set = set()
    unique: List[AppEntry] = []
    for e in entries:
        if e.path not in seen:
            seen.add(e.path)
            unique.append(e)
    return unique


def _group_outcome(matches: List[AppEntry]) -> MatchOutcome:
    """Collapse matches into found/ambiguous, grouping by *display name*.

    Candidates that share the same normalized display name but different
    paths (e.g. two shortcuts both literally named "Discord" — one via the
    Update.exe wrapper, one pointing at the versioned exe) are not
    meaningfully distinguishable to the user either, so they collapse to one
    representative entry (preferring an ``app_paths``-sourced entry, the
    more canonical source, over a Start Menu shortcut). Genuine ambiguity —
    different *names* — is what actually gets surfaced.
    """
    by_name: Dict[str, List[AppEntry]] = {}
    for m in matches:
        by_name.setdefault(_normalize(m.name), []).append(m)

    if len(by_name) == 1:
        group = next(iter(by_name.values()))
        representative = next((e for e in group if e.source == "app_paths"), group[0])
        return MatchOutcome(status="found", match=representative)

    representatives = [group[0] for group in by_name.values()]
    return MatchOutcome(status="ambiguous", candidates=representatives)


# ---------------------------------------------------------------------------
# Launching / closing
# ---------------------------------------------------------------------------


def _executable_exists(path: str) -> bool:
    """Check whether *path* is a real file or resolvable via PATH."""
    return Path(path).exists() or bool(shutil.which(path))


def _launch_default_browser() -> Tuple[bool, str]:
    try:
        ok = webbrowser.open("about:blank")
        return (
            (True, "")
            if ok
            else (False, "Nenhum navegador padrão configurado no sistema.")
        )
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _launch_path(path: str) -> Tuple[bool, str]:
    """Start *path* as a normal, unelevated process (never via a shell)."""
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 - path came from OS-level app discovery only
        else:
            subprocess.Popen([path])
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _list_running_processes() -> List[AppEntry]:
    if sys.platform != "win32":
        return []
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:  # noqa: BLE001
        return []
    entries: List[AppEntry] = []
    for line in result.stdout.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) < 2:
            continue
        name = parts[0].lstrip('"')
        try:
            pid = int(parts[1])
        except ValueError:
            continue
        entries.append(
            AppEntry(
                name=re.sub(r"\.exe$", "", name, flags=re.IGNORECASE),
                path=str(pid),
                source="process",
            )
        )
    return entries


def _terminate_process(pid: int) -> Tuple[bool, str]:
    """Gracefully close a process by PID, escalating to a forced kill if needed."""
    try:
        graceful = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if graceful.returncode == 0:
            return True, ""
        forced = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if forced.returncode == 0:
            return True, ""
        return False, (forced.stderr or graceful.stderr or "").strip()
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


@ToolRegistry.register("app_launcher")
class AppLauncherTool(BaseTool):
    """Open or close an already-installed desktop application by name."""

    tool_id = "app_launcher"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="app_launcher",
            description=(
                "Open or close an already-installed desktop application by name "
                "(e.g. 'Chrome', 'calculadora', 'Discord'). Discovers installed "
                "programs from the OS's own registry of installed software and "
                "Start Menu shortcuts — never installs new software, never runs "
                "a caller-supplied file path, and never requests administrator "
                "elevation. If the name is ambiguous, returns the list of "
                "matching applications instead of guessing."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["open", "close"],
                        "description": "Whether to open or close the application.",
                    },
                    "app_name": {
                        "type": "string",
                        "description": (
                            "The application's name as spoken/typed by the user "
                            "(e.g. 'Chrome', 'calculadora', 'navegador')."
                        ),
                    },
                },
                "required": ["action", "app_name"],
            },
            category="system",
            required_capabilities=["code:execute"],
            timeout_seconds=15.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        action = params.get("action", "open")
        app_name = (params.get("app_name") or "").strip()
        if not app_name:
            return ToolResult(
                tool_name="app_launcher",
                content="Informe o nome do aplicativo.",
                success=False,
            )

        if action == "open":
            return self._open(app_name)
        if action == "close":
            return self._close(app_name)
        return ToolResult(
            tool_name="app_launcher",
            content=f"Ação desconhecida: {action!r} (use 'open' ou 'close').",
            success=False,
        )

    def _open(self, app_name: str) -> ToolResult:
        if is_default_browser_query(app_name):
            ok, err = _launch_default_browser()
            if ok:
                return ToolResult(
                    tool_name="app_launcher",
                    content="Abrindo o navegador padrão.",
                    success=True,
                    metadata={"app": "default_browser"},
                )
            return ToolResult(
                tool_name="app_launcher",
                content=f"Não consegui abrir o navegador padrão: {err}",
                success=False,
            )

        candidates = discover_apps()
        outcome = find_app(app_name, candidates)

        if outcome.status == "not_found":
            return ToolResult(
                tool_name="app_launcher",
                content=f"Não encontrei o aplicativo '{app_name}' instalado.",
                success=False,
            )

        if outcome.status == "ambiguous":
            names = sorted({c.name for c in outcome.candidates})
            return ToolResult(
                tool_name="app_launcher",
                content=(
                    f"Encontrei mais de um aplicativo parecido com '{app_name}': "
                    f"{', '.join(names)}. Qual deles você quer abrir?"
                ),
                success=False,
                metadata={"ambiguous": True, "candidates": names},
            )

        entry = outcome.match
        assert entry is not None
        if not _executable_exists(entry.path):
            return ToolResult(
                tool_name="app_launcher",
                content=(
                    f"O executável de '{entry.name}' não foi encontrado em "
                    f"'{entry.path}' (pode ter sido desinstalado)."
                ),
                success=False,
            )

        ok, err = _launch_path(entry.path)
        if not ok:
            return ToolResult(
                tool_name="app_launcher",
                content=f"Não consegui abrir '{entry.name}': {err}",
                success=False,
            )
        return ToolResult(
            tool_name="app_launcher",
            content=f"Abrindo {entry.name}.",
            success=True,
            metadata={"app": entry.name, "path": entry.path},
        )

    def _close(self, app_name: str) -> ToolResult:
        running = _list_running_processes()
        if not running:
            return ToolResult(
                tool_name="app_launcher",
                content=(
                    "Não consegui listar os processos em execução neste sistema."
                    if sys.platform == "win32"
                    else "Fechar aplicativos por nome não é suportado nesta plataforma."
                ),
                success=False,
            )

        outcome = find_app(app_name, running)

        if outcome.status == "not_found":
            return ToolResult(
                tool_name="app_launcher",
                content=f"'{app_name}' não parece estar em execução.",
                success=False,
            )

        if outcome.status == "ambiguous":
            names = sorted({c.name for c in outcome.candidates})
            return ToolResult(
                tool_name="app_launcher",
                content=(
                    f"Encontrei mais de um processo parecido com '{app_name}': "
                    f"{', '.join(names)}. Qual deles você quer fechar?"
                ),
                success=False,
                metadata={"ambiguous": True, "candidates": names},
            )

        entry = outcome.match
        assert entry is not None
        pid = int(entry.path)
        ok, err = _terminate_process(pid)
        if not ok:
            return ToolResult(
                tool_name="app_launcher",
                content=f"Não consegui fechar '{entry.name}': {err}",
                success=False,
            )
        return ToolResult(
            tool_name="app_launcher",
            content=f"{entry.name} foi fechado.",
            success=True,
            metadata={"app": entry.name, "pid": pid},
        )


__all__ = [
    "AppEntry",
    "AppLauncherTool",
    "MatchOutcome",
    "discover_apps",
    "find_app",
    "is_default_browser_query",
]
