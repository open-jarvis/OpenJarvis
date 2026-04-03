"""Slack Socket Mode daemon — listens for DMs and responds with DeepResearch.

Run as a standalone process or import start_slack_daemon() to spawn
from the server. Uses slack-bolt for reliable Socket Mode handling.
"""

from __future__ import annotations

import logging
import os
import re
import signal
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PID_FILE = str(Path.home() / ".openjarvis" / "slack-daemon.pid")


def _to_slack_fmt(text: str) -> str:
    """Convert markdown to Slack mrkdwn format."""
    # Headers → bold
    text = re.sub(r"^#{1,6}\s+(.+)$", r"*\1*", text, flags=re.MULTILINE)
    # Bold: **text** → *text*
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    # Strikethrough: ~~text~~ → ~text~
    text = re.sub(r"~~(.+?)~~", r"~\1~", text)
    # Links: [text](url) → <url|text>
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r"<\2|\1>", text)
    # Remove LaTeX
    text = re.sub(r"\$\$.+?\$\$", "", text)
    text = re.sub(r"\$(.+?)\$", r"\1", text)
    # Clean whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def run_slack_daemon(
    bot_token: str,
    app_token: str,
    model: str = "qwen3.5:9b",
) -> None:
    """Run the Slack daemon (blocking). Handles DMs with DeepResearch."""
    import threading

    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    from openjarvis.agents.deep_research import DeepResearchAgent
    from openjarvis.engine.ollama import OllamaEngine
    from openjarvis.server.agent_manager_routes import (
        _build_deep_research_tools,
    )

    # Write PID
    pid_path = Path(_PID_FILE)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()))

    # Build agent
    engine = OllamaEngine()
    tools = _build_deep_research_tools(engine=engine, model=model)
    agent = DeepResearchAgent(
        engine=engine,
        model=model,
        tools=tools,
        max_turns=5,
    )
    logger.info("Slack daemon: agent ready with %d tools", len(tools))

    app = App(token=bot_token)

    processing = threading.Event()

    @app.event("message")
    def handle_dm(event: dict, say: Any) -> None:
        text = event.get("text", "")
        if not text:
            return

        ts = event.get("ts", "")
        logger.info("Slack DM: %s", text[:60])

        say(text="Message received! Working on it now...", thread_ts=ts)
        processing.set()

        # Progress updater
        stop = threading.Event()

        def _progress() -> None:
            while not stop.is_set():
                stop.wait(60)
                if stop.is_set():
                    break
                if processing.is_set():
                    say(
                        text="Still working! Will reply ASAP",
                        thread_ts=ts,
                    )

        pt = threading.Thread(target=_progress, daemon=True)
        pt.start()

        try:
            result = agent.run(text)
            reply = _to_slack_fmt(result.content or "No results found.")
        except Exception as exc:
            reply = f"Error: {exc}"
            logger.error("Slack daemon error: %s", exc)
        finally:
            processing.clear()
            stop.set()

        say(text=reply, thread_ts=ts)
        logger.info("Slack DM reply sent (%d chars)", len(reply))

    handler = SocketModeHandler(app, app_token)

    # Graceful shutdown
    def _stop(signum: int, frame: Any) -> None:
        logger.info("Slack daemon stopping...")
        handler.close()
        if pid_path.exists():
            pid_path.unlink()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    logger.info("Slack daemon started, listening for DMs...")
    handler.start()  # Blocks until close()


def start_slack_daemon(
    bot_token: str,
    app_token: str,
    model: str = "qwen3.5:9b",
) -> int:
    """Spawn the Slack daemon as a background subprocess.

    Returns the PID of the spawned process.
    """
    import subprocess

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "openjarvis.channels.slack_daemon",
            "--bot-token",
            bot_token,
            "--app-token",
            app_token,
            "--model",
            model,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return proc.pid


def is_running() -> bool:
    """Check if the Slack daemon is running."""
    pid_path = Path(_PID_FILE)
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        pid_path.unlink(missing_ok=True)
        return False


def stop_daemon() -> bool:
    """Stop the running Slack daemon."""
    pid_path = Path(_PID_FILE)
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        pid_path.unlink(missing_ok=True)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        pid_path.unlink(missing_ok=True)
        return False


if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("--bot-token", required=True)
    parser.add_argument("--app-token", required=True)
    parser.add_argument("--model", default="qwen3.5:9b")
    args = parser.parse_args()

    run_slack_daemon(
        bot_token=args.bot_token,
        app_token=args.app_token,
        model=args.model,
    )
