"""Deterministic quick commands — instant local actions without the LLM.

The "powers" layer of voice assistants: common orders like "quelle heure
est-il", "ouvre le bloc-notes" or "verrouille le PC" are matched locally and
executed immediately (zero latency, works offline, no model tokens spent).
Windows-only actions are guarded by ``os.name``; unmatched text returns
``None`` so the caller falls through to the normal LLM path.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from typing import Callable, Optional

# App names the assistant is allowed to launch. Conservative and read-only
# in effect: these launch well-known applications only.
_KNOWN_APPS = {
    "bloc-notes": "notepad.exe",
    "notepad": "notepad.exe",
    "calculatrice": "calc.exe",
    "calc": "calc.exe",
    "explorateur de fichiers": "explorer.exe",
    "explorateur": "explorer.exe",
    "explorer": "explorer.exe",
    "invite de commandes": "cmd.exe",
    "cmd": "cmd.exe",
    "terminal": "cmd.exe",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "edge": "msedge.exe",
    "navigateur": "msedge.exe",
    "fichiers": "explorer.exe",
}

_TIME_PATTERNS = (
    "quelle heure",
    "l'heure",
    "il est quelle heure",
    "what time",
    "the time",
    "quel jour",
    "quelle date",
    "la date",
    "date du jour",
    "on est quel jour",
    "what day",
    "the date",
)

_LOCK_PATTERNS = (
    "verrouille le pc",
    "verrouille l'ordinateur",
    "verrouille la session",
    "verrouille",
    "lock the pc",
    "lock the computer",
    "lock",
)

_VOLUME_DOWN_PATTERNS = ("volume plus bas", "baisse le volume", "volume bas")
_VOLUME_UP_PATTERNS = ("volume plus haut", "monte le volume", "volume haut")
_VOLUME_MUTE_PATTERNS = ("coupe le son", "muet", "mute", "couper le son")

# Natural-language requests for live headlines. Kept narrow: the RSS handler
# answers with real sources instead of letting a local model hallucinate news.
_NEWS_PATTERNS = (
    "dernières nouvelles",
    "dernieres nouvelles",
    "les actualités",
    "les actualites",
    "l'actualité",
    "l'actualite",
    "actualités du jour",
    "actualites du jour",
    "nouvelles du monde",
    "actualités du monde",
    "actualites du monde",
    "actualité mondiale",
    "actualite mondiale",
    "quoi de neuf",
    "news du jour",
    "les infos du jour",
    "world news",
    "latest news",
)

# Country -> city used by the world-clock command. Only countries whose
# capital (or largest city already in CITY_TZ_MAP) is mapped there.
_COUNTRY_CAPITALS = {
    "allemagne": "Berlin",
    "espagne": "Madrid",
    "italie": "Rome",
    "royaume-uni": "Londres",
    "angleterre": "Londres",
    "japon": "Tokyo",
    "chine": "Pékin",
    "australie": "Sydney",
    "canada": "Toronto",
    "états-unis": "New York",
    "etats-unis": "New York",
    "usa": "New York",
    "brésil": "Rio",
    "bresil": "Rio",
    "mexique": "Mexico",
    "inde": "Mumbai",
    "russie": "Moscou",
    "turquie": "Istanbul",
    "égypte": "Le Caire",
    "egypte": "Le Caire",
    "maroc": "Casablanca",
    "tunisie": "Tunis",
    "sénégal": "Dakar",
    "senegal": "Dakar",
    "suisse": "Genève",
    "belgique": "Bruxelles",
    "pays-bas": "Amsterdam",
    "suède": "Stockholm",
    "suede": "Stockholm",
    "norvège": "Oslo",
    "norvege": "Oslo",
    "finlande": "Helsinki",
    "grèce": "Athènes",
    "grece": "Athènes",
    "portugal": "Lisbonne",
    "corée du sud": "Séoul",
    "coree du sud": "Séoul",
    "thaïlande": "Bangkok",
    "thailande": "Bangkok",
    "indonésie": "Jakarta",
    "indonesie": "Jakarta",
}


def _french_time(now_fn: Callable[[], time.struct_time]) -> str:
    """Return the current date/time in French."""
    days = (
        "lundi",
        "mardi",
        "mercredi",
        "jeudi",
        "vendredi",
        "samedi",
        "dimanche",
    )
    months = (
        "janvier",
        "février",
        "mars",
        "avril",
        "mai",
        "juin",
        "juillet",
        "août",
        "septembre",
        "octobre",
        "novembre",
        "décembre",
    )
    now = now_fn()
    return (
        f"Il est {now.tm_hour:02d}h{now.tm_min:02d} — "
        f"{days[now.tm_wday]} {now.tm_mday} {months[now.tm_mon - 1]} "
        f"{now.tm_year}."
    )


def _launch(app_name: str, executable: str) -> str:
    """Start *executable* detached; returns the spoken confirmation."""
    if os.name != "nt":
        return None  # Windows-only app launching
    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "", executable],
            close_fds=True,
        )
    except Exception as exc:  # noqa: BLE001 — a failed launch is reported
        return f"Je n'ai pas pu ouvrir {app_name} ({exc})."
    return f"J'ouvre {app_name}."


def _lock_pc() -> Optional[str]:
    """Lock the workstation (Windows only)."""
    if os.name != "nt":
        return None
    try:
        subprocess.Popen(
            ["rundll32.exe", "user32.dll,LockWorkStation"],
            close_fds=True,
        )
    except Exception as exc:  # noqa: BLE001 — reported to the user
        return f"Je n'ai pas pu verrouiller l'écran ({exc})."
    return "Écran verrouillé."


def _set_volume(level: str) -> str:
    """Adjust system volume via PowerShell (Windows only)."""
    if os.name != "nt":
        return "Le réglage du volume n'est disponible que sous Windows."
    # PowerShell WScript.SendKeys volume keys: simple, no extra dependencies.
    script = {
        "up": "(new-object -comobject wscript.shell).SendKeys([char]175)",
        "down": "(new-object -comobject wscript.shell).SendKeys([char]174)",
        "mute": "(new-object -comobject wscript.shell).SendKeys([char]173)",
    }[level]
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", script],
            close_fds=True,
        )
    except Exception as exc:  # noqa: BLE001 — reported to the user
        return f"Je n'ai pas pu régler le volume ({exc})."
    return "Volume ajusté."


def _extract_city(text: str) -> Optional[str]:
    """Return a known city/country mentioned after à/en/au/in/de/at, or None."""
    # Typed and dictated questions normally end with punctuation; the patterns
    # anchor on the end of the string, so strip it first.
    text = text.rstrip(" \t?.!,;:")
    from openjarvis.tools.net import CITY_TZ_MAP, _normalize_city

    match = re.search(
        r"\b(?:à|in|at|de)\s+([a-zà-ÿ0-9' -]{2,30})\s*$",
        text,
    )
    if match is not None:
        candidate = match.group(1).strip()
        if _normalize_city(candidate) in CITY_TZ_MAP:
            # Preserve a display-friendly casing ("new york" → "New York").
            return candidate.title()

    # "quelle heure est-il en Allemagne / au Japon / aux États-Unis ?"
    country = re.search(r"\b(?:en|au|aux|in)\s+([a-zà-ÿ-]{3,30})\s*$", text)
    if country is not None:
        capital = _COUNTRY_CAPITALS.get(country.group(1).strip())
        if capital and _normalize_city(capital) in CITY_TZ_MAP:
            return capital
    return None


def _news_reply(limit: int = 8) -> Optional[str]:
    """Fetch live RSS headlines; None when the network/feeds are unavailable."""
    try:
        from openjarvis.tools.net import headlines_for

        headlines = headlines_for("", limit=limit)
    except Exception:  # noqa: BLE001 - fall through to the LLM on failure
        return None
    if not headlines:
        return None
    lines = ["Voici les derniers titres :"]
    lines.extend(f"{index}. {title}" for index, title in enumerate(headlines, 1))
    return "\n".join(lines)


def time_text() -> str:
    """Return the current date/time in French (public helper)."""
    return _french_time(time.localtime)


def handle_quick_command(
    text: str,
    *,
    now_fn: Callable[[], time.struct_time] = time.localtime,
    launch_fn: Callable[[str, str], str] = _launch,
) -> Optional[str]:
    """Match *text* against deterministic commands; return the reply or None.

    ``now_fn`` and ``launch_fn`` are injection seams for tests.
    """
    lowered = " ".join(text.strip().lower().split())
    if not lowered:
        return None

    if any(pattern in lowered for pattern in _LOCK_PATTERNS):
        return _lock_pc()

    if any(pattern in lowered for pattern in _TIME_PATTERNS):
        city = _extract_city(lowered)
        if city:
            try:
                from openjarvis.tools.net import city_time

                return city_time(city)
            except Exception:  # noqa: BLE001 — unknown tz falls back locally
                pass
        return _french_time(now_fn)

    if any(pattern in lowered for pattern in _NEWS_PATTERNS):
        news = _news_reply()
        if news is not None:
            return news

    for app_name, executable in _KNOWN_APPS.items():
        for prefix in ("ouvre ", "lance "):
            if lowered.startswith(prefix):
                rest = lowered[len(prefix) :]
                # Ignore articles: "ouvre le bloc-notes" / "ouvre la calculette".
                for article in ("le ", "la ", "les ", "l'"):
                    if rest.startswith(article):
                        rest = rest[len(article) :]
                        break
                if rest == app_name:
                    return launch_fn(app_name, executable)

    if any(pattern in lowered for pattern in _VOLUME_UP_PATTERNS):
        return _set_volume("up")
    if any(pattern in lowered for pattern in _VOLUME_DOWN_PATTERNS):
        return _set_volume("down")
    if any(pattern in lowered for pattern in _VOLUME_MUTE_PATTERNS):
        return _set_volume("mute")

    return None


__all__ = ["handle_quick_command", "time_text"]
