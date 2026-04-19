#!/usr/bin/env python3
"""OpenJarvis Twitter Bot — @OpenJarvisAI reactive mention handler.

Listens for @mentions and responds: answers questions, creates GitHub issues
for bugs/feature requests, acknowledges praise, ignores spam. Like @grok.

Usage:
    python examples/twitter_bot/twitter_bot.py --demo
    python examples/twitter_bot/twitter_bot.py --live
    python examples/twitter_bot/twitter_bot.py --live --index-docs
"""

from __future__ import annotations

import signal
import sys
import threading
from typing import Optional

import click


class _DemoChannel:
    """Stub channel for demo mode.

    Accepts ``send()`` calls and records the content so the demo can
    display exactly what would be tweeted — instead of the agent's
    post-error fallback text (which bypasses the voice rules).
    """

    channel_id = "demo"

    def __init__(self) -> None:
        self.last_sent: str | None = None

    def send(
        self,
        channel: str,
        content: str,
        *,
        conversation_id: str = "",
        metadata: dict | None = None,
    ) -> bool:
        self.last_sent = content
        return True

    # Unused in demo but required by ChannelSendTool duck-typing
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...


DEMO_TWEETS = [
    {
        "id": "1000000000000000001",
        "author": "alice_dev",
        "text": "@OpenJarvisAI how do I add a new channel integration?",
    },
    {
        "id": "1000000000000000002",
        "author": "bob_user",
        "text": (
            "@OpenJarvisAI bug: the memory_search tool crashes "
            "when the index is empty"
        ),
    },
    {
        "id": "1000000000000000003",
        "author": "carol_eng",
        "text": "@OpenJarvisAI it would be great to have a built-in scheduler UI",
    },
    {
        "id": "1000000000000000004",
        "author": "dave_fan",
        "text": "@OpenJarvisAI just discovered this project, absolutely love it!",
    },
    {
        "id": "1000000000000000005",
        "author": "spambot99",
        "text": "@OpenJarvisAI BUY CRYPTO NOW 🚀🚀🚀 LINK IN BIO",
    },
]

# ---------------------------------------------------------------------------
# Retrieval-grounded question handling
# ---------------------------------------------------------------------------
#
# For QUESTION mentions we do dense retrieval in Python before the agent
# runs, then route to one of two prompts based on the top-1 cosine score:
#
#   * ``_build_question_grounded_prompt`` — top-1 >= SCORE_THRESHOLD.
#     The retrieved context is embedded directly in the prompt. The model
#     only needs ``channel_send``.
#   * ``_build_question_deferral_prompt`` — top-1 <  SCORE_THRESHOLD.
#     No context worth grounding on. The model is told to post a short
#     honest deferral.
#
# Threshold rationale: see tests/tools/storage/test_dense.py. With
# nomic-embed-text on the OpenJarvis fixture corpus, relevant queries
# top-1 scored 0.50-0.74 (median 0.68) and off-topic scored 0.40-0.51
# (median 0.47). 0.55 biases toward deferral on borderline queries —
# safer for public Twitter than grounding on a weak match.
SCORE_THRESHOLD = 0.55

# Voice rules included in every per-call prompt so the model always sees them
_VOICE = (
    "Rules for your reply:\n"
    "- lowercase prose; preserve URLs, code identifiers, and technical terms "
    "(model names, library names, file paths) as written.\n"
    "- <=280 characters.\n"
    "- no emojis. no hashtags.\n"
    "- casual and direct, like a dev helping another dev.\n"
    "- do not invent URLs, issue numbers, stats, commands, performance claims, "
    "or feature names. if you're not sure, don't guess.\n"
)


def _format_context(results) -> str:
    """Render top retrieved chunks as a numbered list for the prompt."""
    out = []
    for i, r in enumerate(results, 1):
        src = r.source or "?"
        breadcrumb = r.metadata.get("breadcrumb", "") if r.metadata else ""
        header = f"[{i}] {src}"
        if breadcrumb and breadcrumb not in src:
            header += f"  —  {breadcrumb}"
        out.append(f"{header}\n{r.content}")
    return "\n\n---\n\n".join(out)


def _build_question_grounded_prompt(
    author: str,
    tweet_id: str,
    text: str,
    context: str,
    top_score: float,
) -> str:
    """Prompt used when retrieval surfaces relevant content (top score >= threshold)."""
    return (
        "You are @OpenJarvisAI. Someone asked a question. We retrieved "
        f"context from the docs with top similarity {top_score:.2f}.\n\n"
        f"Tweet from @{author} (tweet ID: {tweet_id}):\n"
        f'"{text}"\n\n'
        "Retrieved context:\n"
        "=================\n"
        f"{context}\n"
        "=================\n\n"
        "Compose a reply ONLY from facts in the context above. Do not add "
        "details that are not in the context. If the context doesn't fully "
        "cover the question, answer the part that IS covered and defer on "
        "the rest (e.g. \"...not sure on the rest — will check\"). Then "
        f'call channel_send with conversation_id="{tweet_id}".\n\n'
        + _VOICE
    )


def _build_question_deferral_prompt(author: str, tweet_id: str, text: str) -> str:
    """Prompt used when retrieval has nothing relevant (top score < threshold).

    The model is told NOT to answer — because attempting to answer without
    grounding is the exact failure mode we're trying to avoid.
    """
    return (
        "You are @OpenJarvisAI. Someone asked a question, but our docs "
        "search did not find relevant material — so we do NOT have a "
        "grounded answer.\n\n"
        f"Tweet from @{author} (tweet ID: {tweet_id}):\n"
        f'"{text}"\n\n'
        "Reply with a short honest deferral. Something like:\n"
        '  "not sure off the top of my head — let me check and get back to you"\n'
        '  "good question, need to double-check the answer — back with details soon"\n'
        "Do NOT guess. Do NOT make up facts. A deferral is always safer "
        "than a wrong public answer.\n\n"
        f'Then call channel_send with conversation_id="{tweet_id}".\n\n'
        + _VOICE
    )


# Kept for backwards-compat with tests; delegates to the grounded variant
# with an empty context (forcing the model to defer in its own words).
def _build_question_prompt(author: str, tweet_id: str, text: str) -> str:
    return _build_question_deferral_prompt(author, tweet_id, text)


def _build_bug_prompt(author: str, tweet_id: str, text: str) -> str:
    return (
        "You are @OpenJarvisAI. Someone reported a bug.\n\n"
        f"Tweet from @{author} (tweet ID: {tweet_id}):\n"
        f'"{text}"\n\n'
        "1. call http_request to create a github issue:\n"
        "   url: https://api.github.com/repos/open-jarvis/OpenJarvis/issues\n"
        "   method: POST\n"
        '   headers: {"Authorization": "Bearer $GITHUB_TOKEN", '
        '"Accept": "application/vnd.github+json"}\n'
        f'   body: {{"title": "<short title>", "body": "reported via twitter '
        f"by @{author}: {text}\", "
        '"labels": ["bug", "from-twitter"]}}\n'
        f'2. call channel_send with conversation_id="{tweet_id}" and a short '
        "reply like: \"opened an issue for this — we'll look into it. "
        'thanks for the report"\n\n'
        "do NOT include a github issue URL in your reply — you don't know "
        "the issue number yet.\n\n"
        + _VOICE
    )


def _build_feature_prompt(author: str, tweet_id: str, text: str) -> str:
    return (
        "You are @OpenJarvisAI. Someone requested a feature.\n\n"
        f"Tweet from @{author} (tweet ID: {tweet_id}):\n"
        f'"{text}"\n\n'
        "1. call http_request to create a github issue:\n"
        "   url: https://api.github.com/repos/open-jarvis/OpenJarvis/issues\n"
        "   method: POST\n"
        f'   body: {{"title": "feature request: <title>", "body": "requested '
        f"via twitter by @{author}: {text}\", "
        '"labels": ["enhancement", "from-twitter"]}}\n'
        f'2. call channel_send with conversation_id="{tweet_id}" and a short '
        "reply like: \"love this idea — opened an issue to track it\"\n\n"
        "do NOT include a github issue URL in your reply — you don't know "
        "the issue number yet.\n\n"
        + _VOICE
    )


def _build_praise_prompt(author: str, tweet_id: str, text: str) -> str:
    return (
        "You are @OpenJarvisAI. Someone said something nice.\n\n"
        f"Tweet from @{author} (tweet ID: {tweet_id}):\n"
        f'"{text}"\n\n'
        f'call channel_send with conversation_id="{tweet_id}" and a genuine, '
        "short thank-you. be real, not corporate.\n\n"
        + _VOICE
    )


_BUG_KEYWORDS = (
    "bug:", "bug ", "crash", "error", "fails", "broken", "segfault",
)
_FEATURE_KEYWORDS = (
    "feature", "would love", "would be great", "wish",
    "please add", "can you add", "any plans",
)
_PRAISE_KEYWORDS = (
    "love", "amazing", "awesome", "impressed",
    "great work", "switched from", "incredible",
)
_SPAM_KEYWORDS = (
    "buy", "crypto", "income", "free download",
    "link in bio", "10x", "guaranteed",
)


def _classify_mention(text: str) -> str:
    """Simple keyword-based classification to avoid wasting a model turn."""
    lower = text.lower()
    if any(w in lower for w in _BUG_KEYWORDS):
        return "BUG_REPORT"
    if any(w in lower for w in _FEATURE_KEYWORDS):
        return "FEATURE_REQUEST"
    if any(w in lower for w in _PRAISE_KEYWORDS):
        return "PRAISE"
    if any(w in lower for w in _SPAM_KEYWORDS):
        return "SPAM"
    return "QUESTION"


def _resolve_question_prompt(backend, author: str, tweet_id: str, text: str):
    """Do retrieval in Python and pick grounded vs deferral prompt.

    Returns ``(prompt, top_score)``. If *backend* is None or retrieval
    returns nothing, falls back to the deferral prompt.
    """
    if backend is None:
        return _build_question_deferral_prompt(author, tweet_id, text), 0.0

    hits = backend.retrieve(text, top_k=3)
    if not hits:
        return _build_question_deferral_prompt(author, tweet_id, text), 0.0

    top_score = hits[0].score
    if top_score < SCORE_THRESHOLD:
        return _build_question_deferral_prompt(author, tweet_id, text), top_score

    # Grounded: include the top hits in the prompt verbatim
    return (
        _build_question_grounded_prompt(
            author,
            tweet_id,
            text,
            _format_context(hits),
            top_score,
        ),
        top_score,
    )


def _build_dense_backend_or_none():
    """Try to build the DenseMemory index from README + docs/.

    Returns None on any failure (Ollama down, embedding model missing,
    docs missing). Demo mode falls back to the deferral prompt in that
    case, which keeps the demo runnable without a full setup.
    """
    try:
        import pathlib as _pl
        import sys as _sys

        _sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[2] / "scripts"))
        try:
            from index_docs import build_index  # type: ignore
        finally:
            _sys.path.pop(0)

        repo_root = _pl.Path(__file__).resolve().parents[2]
        return build_index(repo_root)
    except Exception as exc:
        click.echo(
            f"  [warn] dense retrieval unavailable — {exc}\n"
            "         questions will use the deferral path.",
            err=True,
        )
        return None


def _run_demo(model: str, engine_key: str) -> None:
    """Process sample mentions through the agent without Twitter API access."""
    try:
        from openjarvis import Jarvis
    except ImportError:
        click.echo(
            "Error: openjarvis is not installed. "
            "Install it with:  uv sync --extra dev",
            err=True,
        )
        sys.exit(1)

    click.echo("OpenJarvis Twitter Bot — Demo Mode (reactive only)")
    click.echo(f"Model: {model}  |  Engine: {engine_key}")
    click.echo("=" * 60)

    try:
        j = Jarvis(model=model, engine_key=engine_key)
    except Exception as exc:
        click.echo(
            f"Error: could not initialize Jarvis — {exc}\n\n"
            "Make sure your engine is running. For Ollama:\n"
            "  ollama serve\n"
            "  ollama pull qwen3:32b\n\n"
            "For cloud engines, ensure API keys are set in your .env file.",
            err=True,
        )
        sys.exit(1)

    click.echo("Building dense retrieval index from README + docs/...")
    backend = _build_dense_backend_or_none()
    if backend is not None:
        click.echo(f"Indexed {backend.count()} doc chunks.\n")
    click.echo(f"Processing {len(DEMO_TWEETS)} sample mentions...\n")

    # In demo mode, inject a stub channel so channel_send succeeds and
    # we can capture the model's actual reply (what it would tweet) —
    # rather than its post-error fallback text.
    demo_channel = _DemoChannel()

    try:
        for idx, tweet in enumerate(DEMO_TWEETS, 1):
            mention_type = _classify_mention(tweet["text"])
            click.echo(
                f"  [{idx}/{len(DEMO_TWEETS)}] [{mention_type}] @{tweet['author']}: "
                f"{tweet['text'][:60]}...",
            )

            if mention_type == "SPAM":
                click.echo("           -> [ignored]")
                click.echo()
                continue

            if mention_type == "QUESTION":
                prompt, top_score = _resolve_question_prompt(
                    backend, tweet["author"], tweet["id"], tweet["text"],
                )
                tools = ["channel_send"]
                ground_state = (
                    f"grounded({top_score:.2f})"
                    if top_score >= SCORE_THRESHOLD
                    else f"deferred({top_score:.2f})"
                )
                click.echo(f"           [{ground_state}]")
            elif mention_type == "BUG_REPORT":
                prompt = _build_bug_prompt(tweet["author"], tweet["id"], tweet["text"])
                tools = ["http_request", "channel_send"]
            elif mention_type == "FEATURE_REQUEST":
                prompt = _build_feature_prompt(
                    tweet["author"], tweet["id"], tweet["text"],
                )
                tools = ["http_request", "channel_send"]
            else:
                prompt = _build_praise_prompt(
                    tweet["author"], tweet["id"], tweet["text"],
                )
                tools = ["channel_send"]

            demo_channel.last_sent = None
            response = j.ask(
                prompt,
                agent="orchestrator",
                tools=tools,
                temperature=0.4,
                channel=demo_channel,
            )
            # Prefer the actual channel_send content (the tweet the model
            # composed under voice rules) over the agent's final summary.
            reply = demo_channel.last_sent or response
            click.echo(f"           -> {reply[:160]}")
            click.echo()
    except Exception as exc:
        click.echo(f"Error during processing: {exc}", err=True)
        sys.exit(1)
    finally:
        j.close()

    click.echo("Demo complete.")


def _index_docs(j) -> None:  # noqa: ANN001
    """Pre-index docs/ and README.md into memory for RAG."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    docs_dir = root / "docs"
    readme = root / "README.md"

    files_to_index: list[pathlib.Path] = []
    if readme.exists():
        files_to_index.append(readme)
    if docs_dir.is_dir():
        files_to_index.extend(sorted(docs_dir.rglob("*.md")))

    if not files_to_index:
        click.echo("No docs found to index.")
        return

    click.echo(f"Indexing {len(files_to_index)} doc files into memory...")
    for fpath in files_to_index:
        try:
            text = fpath.read_text(encoding="utf-8")
            chunk_size = 2000
            for i in range(0, len(text), chunk_size):
                chunk = text[i : i + chunk_size]
                j.ask(
                    f"Store this documentation excerpt from {fpath.name}:\n\n{chunk}",
                    agent="orchestrator",
                    tools=["memory_store"],
                    temperature=0.1,
                )
        except Exception as exc:
            click.echo(f"  Warning: could not index {fpath.name}: {exc}")
    click.echo("Indexing complete.\n")


def _seed_since_id_to_newest(channel) -> Optional[str]:
    """Fetch the current newest mention and set ``_since_id`` so that the
    subsequent poll loop only surfaces mentions that arrive AFTER now.

    Returns the id we seeded with, or ``None`` if the inbox is empty /
    the call failed. This is how dry-run (and live first-boot) avoid
    processing the historical backlog.
    """
    import httpx

    try:
        resp = httpx.get(
            f"https://api.twitter.com/2/users/{channel._bot_user_id}/mentions",
            headers={"Authorization": f"Bearer {channel._bearer}"},
            params={"max_results": 5},
            timeout=10.0,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get("meta", {}).get("result_count", 0) == 0:
            return None
        newest = data.get("meta", {}).get("newest_id") or (
            data["data"][0]["id"] if data.get("data") else None
        )
        if newest:
            channel._since_id = newest
        return newest
    except Exception:
        return None


def _run_live(
    model: str,
    engine_key: str,
    index_docs: bool,
    *,
    dry_run: bool = False,
) -> None:
    """Connect to Twitter and handle mentions in real time.

    When ``dry_run`` is True, every side-effect is intercepted:
      * ``channel_send`` prints the draft reply instead of posting.
      * ``http_request`` prints the intended call (e.g. GitHub issue
        creation) and returns a fake success result so the agent loop
        completes as it would in live mode.
      * ``since_id`` is seeded to the newest existing mention so we only
        react to mentions that arrive AFTER boot.
    """
    try:
        from openjarvis import Jarvis
        from openjarvis.channels._stubs import ChannelStatus
        from openjarvis.channels.twitter_channel import TwitterChannel
        from openjarvis.core.types import ToolResult
    except ImportError:
        click.echo(
            "Error: openjarvis is not installed. "
            "Install it with:  uv sync --extra dev",
            err=True,
        )
        sys.exit(1)

    mode_label = "Dry-Run" if dry_run else "Live"
    click.echo(f"OpenJarvis Twitter Bot — {mode_label} Mode")
    click.echo(f"Model: {model}  |  Engine: {engine_key}")
    click.echo("=" * 60)

    try:
        j = Jarvis(model=model, engine_key=engine_key)
    except Exception as exc:
        click.echo(f"Error: could not initialize Jarvis — {exc}", err=True)
        sys.exit(1)

    click.echo("Building dense retrieval index from README + docs/...")
    backend = _build_dense_backend_or_none()
    if backend is not None:
        click.echo(f"Indexed {backend.count()} doc chunks.")

    # ------------------------------------------------------------------
    # Channel — real posting, or a dry-run subclass that just prints.
    # ------------------------------------------------------------------
    if dry_run:
        class _DryRunTwitterChannel(TwitterChannel):
            """Subclass whose ``send`` prints the draft reply but never POSTs."""

            def send(self, channel, content, *, conversation_id="", metadata=None):
                click.echo("")
                click.echo("  ┌── DRY-RUN: would post tweet ──")
                click.echo(f"  │  in_reply_to: {conversation_id or '(none)'}")
                click.echo(f"  │  text ({len(content)} chars): {content[:280]}")
                click.echo("  └──────────────────────────────")
                return True

        channel = _DryRunTwitterChannel()
    else:
        channel = TwitterChannel()

    channel.connect()

    if channel.status() == ChannelStatus.ERROR:
        click.echo(
            "Error: could not connect to Twitter.\n"
            "Ensure these env vars are set:\n"
            "  TWITTER_BEARER_TOKEN\n"
            "  TWITTER_API_KEY / TWITTER_API_SECRET\n"
            "  TWITTER_ACCESS_TOKEN / TWITTER_ACCESS_SECRET\n"
            "  TWITTER_BOT_USER_ID",
            err=True,
        )
        j.close()
        sys.exit(1)

    seeded = _seed_since_id_to_newest(channel)
    if seeded:
        click.echo(
            f"Seeded since_id={seeded} — only new mentions after "
            "this point will trigger the bot.",
        )
    else:
        click.echo(
            "No existing mentions found (or couldn't read inbox) — "
            "bot will start processing from the next one onward.",
        )

    # ------------------------------------------------------------------
    # In dry-run, also intercept http_request so bug/feature mentions
    # don't actually create GitHub issues.
    # ------------------------------------------------------------------
    http_restore = None
    if dry_run:
        from openjarvis.tools.http_request import HttpRequestTool
        _orig_execute = HttpRequestTool.execute

        def _dry_http_execute(self, **params):  # noqa: ANN001
            url = params.get("url", "")
            method = params.get("method", "GET")
            body = params.get("body", "")
            click.echo("")
            click.echo("  ┌── DRY-RUN: would HTTP call ──")
            click.echo(f"  │  {method} {url}")
            if body:
                body_str = body if isinstance(body, str) else str(body)
                suffix = "..." if len(body_str) > 300 else ""
                click.echo(f"  │  body: {body_str[:300]}{suffix}")
            click.echo("  └──────────────────────────────")
            # Return a fake success response so the agent loop finishes.
            return ToolResult(
                tool_name="http_request",
                success=True,
                content=(
                    '{"number": 999, "html_url": '
                    '"https://github.com/open-jarvis/OpenJarvis/issues/999"}'
                ),
            )

        HttpRequestTool.execute = _dry_http_execute
        http_restore = (HttpRequestTool, _orig_execute)

    mode_hint = (
        "[DRY-RUN] Nothing will actually be posted or filed."
        if dry_run
        else "[LIVE] Real tweets will be posted."
    )
    click.echo(f"\n{mode_hint}")
    click.echo("Waiting for @OpenJarvisAI mentions (poll every 60s). Ctrl+C to stop.\n")

    def _handle_mention(msg):  # noqa: ANN001
        """Process an incoming mention through the agent."""
        mention_type = _classify_mention(msg.content)
        click.echo("=" * 60)
        click.echo(f"[📨] mention {msg.message_id} from @{msg.sender}: {msg.content}")
        click.echo(f"     classified: {mention_type}")

        if mention_type == "SPAM":
            click.echo("     -> [ignored]\n")
            return

        if mention_type == "QUESTION":
            prompt, top_score = _resolve_question_prompt(
                backend, msg.sender, msg.message_id, msg.content,
            )
            tools = ["channel_send"]
            state = "grounded" if top_score >= SCORE_THRESHOLD else "deferred"
            click.echo(f"     retrieval top-1 score: {top_score:.3f} -> {state}")
        elif mention_type == "BUG_REPORT":
            prompt = _build_bug_prompt(msg.sender, msg.message_id, msg.content)
            tools = ["http_request", "channel_send"]
        elif mention_type == "FEATURE_REQUEST":
            prompt = _build_feature_prompt(msg.sender, msg.message_id, msg.content)
            tools = ["http_request", "channel_send"]
        else:
            prompt = _build_praise_prompt(msg.sender, msg.message_id, msg.content)
            tools = ["channel_send"]

        try:
            j.ask(
                prompt,
                agent="orchestrator",
                tools=tools,
                temperature=0.4,
                channel=channel,
            )
        except Exception as exc:
            click.echo(f"     ERROR processing mention: {exc}\n")

    channel.on_message(_handle_mention)

    # Block until interrupted
    stop = threading.Event()

    def _signal_handler(sig, frame):  # noqa: ANN001
        click.echo("\nShutting down...")
        stop.set()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    stop.wait()

    if http_restore is not None:
        http_restore[0].execute = http_restore[1]
    channel.disconnect()
    j.close()
    click.echo("Stopped.")


@click.command()
@click.option(
    "--model",
    default="qwen3:32b",
    show_default=True,
    help="Model to use for mention handling.",
)
@click.option(
    "--engine",
    "engine_key",
    default="ollama",
    show_default=True,
    help="Engine backend (ollama, cloud, vllm, etc.).",
)
@click.option(
    "--demo",
    is_flag=True,
    default=False,
    help="Run in demo mode with sample mentions (no Twitter API required).",
)
@click.option(
    "--live",
    is_flag=True,
    default=False,
    help="Run in live mode, polling Twitter for real mentions.",
)
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    default=False,
    help="Poll Twitter live, but print draft replies instead of posting "
    "them and simulate GitHub issue creation. Safe for end-to-end testing.",
)
@click.option(
    "--index-docs",
    is_flag=True,
    default=False,
    help="Pre-index docs/ and README.md into memory before starting.",
)
def main(
    model: str,
    engine_key: str,
    demo: bool,
    live: bool,
    dry_run: bool,
    index_docs: bool,
) -> None:
    """OpenJarvis Twitter bot — reactive @OpenJarvisAI mention handler.

    Polls for @mentions, classifies them (question, bug, feature request,
    praise, spam), and responds appropriately — including creating GitHub
    issues for bug reports and feature requests. Similar to how @grok works.

    \b
    Demo mode (no Twitter credentials needed):
        python examples/twitter_bot/twitter_bot.py --demo

    \b
    Live mode (requires Twitter + GitHub credentials):
        python examples/twitter_bot/twitter_bot.py --live
        python examples/twitter_bot/twitter_bot.py --live --index-docs
    """
    if demo:
        _run_demo(model, engine_key)
    elif dry_run:
        _run_live(model, engine_key, index_docs, dry_run=True)
    elif live:
        _run_live(model, engine_key, index_docs, dry_run=False)
    else:
        click.echo(
            "Please specify --demo, --dry-run, or --live mode.\n"
            "Run with --help for usage details.",
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
