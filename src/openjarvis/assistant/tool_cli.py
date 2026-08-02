"""Bounded local tools callable by an approved Codex/App-Server action turn."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

from openjarvis.browser import (
    BrowserArtifactStore,
    BrowserProcessManager,
    BrowserProfilePolicy,
    CdpBrowserAdapter,
    PublicBrowserNetworkPolicy,
    WebInjectionGuard,
)
from openjarvis.desktop import Win32SemanticBackend, WindowsDesktopSession

_FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,119}\.(?:txt|md)$")
_MAX_TEXT = 20_000
_MAX_QUERY = 300


def _normal_root(environment_name: str) -> Path:
    raw = os.environ.get(environment_name, "")
    if not raw:
        raise RuntimeError(f"{environment_name} is unavailable")
    root = Path(raw).resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise RuntimeError(f"{environment_name} is invalid")
    return root


def _artifact_root() -> Path:
    root = _normal_root("OPENJARVIS_TOOL_ARTIFACT_ROOT")
    root.mkdir(parents=True, exist_ok=True)
    return root


def desktop_note(filename: str, text: str) -> dict[str, object]:
    """Enter text in an owned visible editor and save one new workspace file."""

    if not _FILE_NAME.fullmatch(filename) or Path(filename).name != filename:
        raise ValueError("desktop filename is not allowed")
    if not text or len(text) > _MAX_TEXT:
        raise ValueError("desktop text length is outside the allowed range")
    workspace = _normal_root("OPENJARVIS_ASSISTANT_WORKSPACE")
    destination = workspace / filename
    if destination.exists():
        raise FileExistsError("refusing to overwrite an existing assistant file")
    editor = Path(__file__).with_name("safe_editor_app.py").resolve(strict=True)
    events: list[str] = []
    session = WindowsDesktopSession(
        backend=Win32SemanticBackend(),
        artifact_root=_artifact_root() / "desktop",
        event_sink=lambda name, _payload: events.append(name),
    )
    window_pid = 0
    try:
        window = session.start_test_application(
            executable=getattr(sys, "_base_executable", sys.executable),
            script=editor,
            arguments=(filename, str(os.getpid())),
            expected_title="OpenJarvis Safe Text Editor",
            allowed_root=editor.parent,
            timeout=15,
        )
        window_pid = window.process_id
        edit = session.element(automation_id=1001, role="edit")
        save = session.element(automation_id=1002, role="button")
        observed = session.set_text(edit, text)
        session.click(
            save,
            verifier=lambda: session.element(
                automation_id=1003,
                role="static",
            ).name
            == "Saved",
        )
        artifact = session.screenshot()
        saved = destination.read_text(encoding="utf-8")
        if saved != text or observed != text:
            raise RuntimeError("desktop note verification failed")
        return {
            "status": "passed",
            "kind": "desktop_note",
            "relative_path": filename,
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "size_bytes": destination.stat().st_size,
            "window_pid": window_pid,
            "screenshot_sha256": artifact.sha256,
            "verified": True,
            "event_types": events,
        }
    finally:
        session.close()


def _edge_executable() -> Path:
    candidates = (
        Path(os.environ.get("PROGRAMFILES(X86)", ""))
        / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", ""))
        / "Microsoft/Edge/Application/msedge.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve(strict=True)
    raise RuntimeError("Microsoft Edge is not installed in a standard location")


def _page(control: CdpBrowserAdapter) -> dict[str, str]:
    value = control.evaluate(
        """(() => ({url:location.href,title:document.title,
        text:document.body ? document.body.innerText : ''}))()"""
    )
    if not isinstance(value, dict):
        raise RuntimeError("browser page observation is invalid")
    return {
        "url": str(value.get("url", "")),
        "title": str(value.get("title", ""))[:500],
        "text": str(value.get("text", ""))[:200_000],
    }


def _canonical_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def _candidate_links(control: CdpBrowserAdapter) -> list[str]:
    value = control.evaluate(
        """(() => {
          const links=[];
          const selectors=[
            'div.mw-search-result-heading a',
            '.references a.external',
            '.mw-parser-output a.external',
            '#mw-content-text a[href^="/wiki/"]'
          ];
          for (const selector of selectors) {
            for (const anchor of document.querySelectorAll(selector)) {
              if(anchor.href && !links.includes(anchor.href)) links.push(anchor.href);
              if(links.length>=40) return links;
            }
          }
          return links;
        })()"""
    )
    return [str(item) for item in value] if isinstance(value, list) else []


def browser_research(query: str) -> dict[str, object]:
    """Search in an owned temporary browser and read multiple public sources."""

    query = " ".join(query.split())
    if not query or len(query) > _MAX_QUERY:
        raise ValueError("research query length is outside the allowed range")
    artifacts = _artifact_root() / "browser"
    profile_root = artifacts / "profiles"
    manager = BrowserProcessManager(
        executable=_edge_executable(),
        profile_policy=BrowserProfilePolicy(profile_root),
        visible=True,
    )
    session = manager.create_session()
    control = CdpBrowserAdapter()
    network = PublicBrowserNetworkPolicy()
    guard = WebInjectionGuard()
    sources: list[dict[str, object]] = []
    blocked: list[dict[str, object]] = []
    seen: set[str] = set()
    queued: list[str] = []
    screenshot_sha256 = ""
    try:
        manager.start(session, timeout=30)
        if not control.connect(session):
            raise RuntimeError("owned browser control connection failed")
        search_url = "https://en.wikipedia.org/w/index.php?" + urlencode(
            {"search": query}
        )
        network.validate(search_url)
        control.navigate(search_url, timeout=30)
        search_page = _page(control)
        network.validate(search_page["url"])
        current = _canonical_url(search_page["url"])
        if "/wiki/" in urlsplit(current).path:
            queued.append(current)
        queued.extend(_candidate_links(control))

        while queued and len(sources) < 3:
            target = _canonical_url(queued.pop(0))
            if target in seen or target.lower().endswith(".pdf"):
                continue
            seen.add(target)
            try:
                network.validate(target)
                control.navigate(target, timeout=30)
                page = _page(control)
                final_url = _canonical_url(page["url"])
                network.validate(final_url)
            except Exception as exc:
                blocked.append(
                    {"url": target, "reason": type(exc).__name__}
                )
                continue
            assessment = guard.scan(page["text"])
            if not assessment.clean:
                blocked.append(
                    {
                        "url": final_url,
                        "reason": "untrusted_instruction_pattern",
                        "findings": list(assessment.findings),
                    }
                )
                continue
            readable = "\n".join(
                line.strip() for line in page["text"].splitlines() if line.strip()
            )
            if len(readable) < 200:
                blocked.append({"url": final_url, "reason": "insufficient_text"})
                continue
            sources.append(
                {
                    "title": page["title"],
                    "url": final_url,
                    "excerpt": readable[:6_000],
                }
            )
            if len(sources) == 1:
                queued.extend(_candidate_links(control))

        if len(sources) < 2:
            raise RuntimeError("browser research found fewer than two safe sources")
        screenshot = BrowserArtifactStore(artifacts).put(
            kind="browser_research_screenshot",
            data=control.screenshot(),
            suffix=".png",
            media_type="image/png",
        )
        screenshot_sha256 = screenshot.sha256
        return {
            "status": "passed",
            "kind": "browser_research",
            "query": query,
            "source_count": len(sources),
            "sources": sources,
            "blocked_source_count": len(blocked),
            "blocked_sources": blocked,
            "screenshot_sha256": screenshot_sha256,
            "temporary_profile": True,
            "external_effects": False,
        }
    finally:
        control.close()
        manager.close(session)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenJarvis bounded assistant tools")
    commands = parser.add_subparsers(dest="command", required=True)
    desktop = commands.add_parser("desktop-note")
    desktop.add_argument("--filename", required=True)
    desktop.add_argument("--text", required=True)
    browser = commands.add_parser("browser-research")
    browser.add_argument("--query", required=True)
    args = parser.parse_args(argv)
    try:
        result = (
            desktop_note(args.filename, args.text)
            if args.command == "desktop-note"
            else browser_research(args.query)
        )
        # ASCII JSON is lossless and survives localized Windows console code pages.
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {"status": "failed", "error_category": type(exc).__name__},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
