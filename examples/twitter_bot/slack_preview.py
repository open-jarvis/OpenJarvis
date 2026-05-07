#!/usr/bin/env python3
"""Overnight Slack preview — generates proactive tweets on a loop.

Posts to a single Slack thread so it doesn't spam the channel.
Run in tmux and check the thread in the morning.

Usage:
    python examples/twitter_bot/slack_preview.py
"""

from __future__ import annotations

import json
import os
import random
import time

import httpx

SLACK_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL = os.environ.get("SLACK_PREVIEW_CHANNEL", "")
INTERVAL_MINUTES = 30

TOPICS = [
    # Narrative — opinionated takes that happen to be about OpenJarvis
    "mainframe personal computer computing shift efficiency",
    "Intelligence Per Watt study local models queries latency",
    "personal data cloud APIs privacy terms of service",
    "energy consumption NVIDIA Apple Silicon dollar cost constraints",
    "learning loop local traces model weights prompts optimization",
    "Stanford open source Apache research Hazy Scaling Intelligence",
    "cloud dependency personal AI thin orchestration layer brain",
    "local inference consumer hardware battery laptop efficiency",
    "open source tools local AI available everyone research",
    # Technical — but framed as narrative search queries, not product lookups
    "channel integrations messaging platforms connect send disconnect",
    "composable primitives intelligence engine agents tools learning",
    "inference engines hardware detection auto configure local",
    "memory retrieval backends keyword search vector similarity",
]

FACTS = [
    "In the 70s and 80s computing moved from mainframes to personal computers. Not because PCs were more powerful, but because they became efficient enough for what people actually needed. AI is reaching a similar moment.",
    "In our Intelligence Per Watt study, we found that local language models can accurately service 88.7 percent of single-turn chat and reasoning queries at interactive latencies, with intelligence efficiency improving 5.3 times from 2023 to 2025.",
    "In nearly all personal AI projects today, the local component is a thin orchestration layer, while the brain lives in someone else data center. Your most personal data routes through cloud APIs, with their latency, their cost, and their terms of service. We built OpenJarvis to fix this.",
    "OpenJarvis is structured around five composable primitives: Intelligence, Engine, Agents, Tools and Memory, and Learning. Each primitive can be benchmarked, substituted, and optimized independently.",
    "OpenJarvis includes hardware-agnostic telemetry that profiles energy consumption across NVIDIA GPUs, AMD GPUs, and Apple Silicon. Energy and dollar cost are first-class design constraints alongside accuracy.",
    "The learning loop uses personal traces to synthesize training data, refine agent behavior, and improve model selection over time. Four optimization layers: model weights, LM prompts, agentic logic, inference engine.",
    "OpenJarvis is open source under Apache 2.0, built at Stanford at Hazy Research and the Scaling Intelligence Lab at SAIL. Because the tools for studying and building local-first AI should be available to everyone.",
    "OpenJarvis supports 27 channel integrations including Slack, Discord, Telegram, WhatsApp. Adding a new channel is one file implementing BaseChannel with connect, send, and disconnect.",
    "OpenJarvis supports multiple inference engines: Ollama, vLLM, SGLang, llama.cpp. jarvis init picks the right one for your hardware.",
    "Install OpenJarvis by running git clone https://github.com/open-jarvis/OpenJarvis.git then cd OpenJarvis then uv sync. Use jarvis init to auto-detect hardware and configure the engine.",
    "OpenJarvis memory and RAG supports four backends: SQLite FTS5 for keyword search, FAISS for vector similarity, ColBERT for token-level matching, and BM25 for probabilistic retrieval.",
    "OpenJarvis ships with nine example projects: deep_research, code_companion, messaging_hub, scheduled_ops, browser_assistant, security_scanner, daily_digest, doc_qa, and multi_model_router.",
]


def slack_send(text: str, thread_ts: str = "") -> str:
    payload: dict = {"channel": SLACK_CHANNEL, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    resp = httpx.post(
        "https://slack.com/api/chat.postMessage",
        headers={
            "Authorization": f"Bearer {SLACK_TOKEN}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=10.0,
    )
    return resp.json().get("ts", "")


def main() -> None:
    from openjarvis import Jarvis
    from openjarvis.core.events import EventType

    print("Starting overnight Slack preview...")
    print(f"Posting to #{SLACK_CHANNEL} every ~{INTERVAL_MINUTES} min")
    print()

    j = Jarvis(model="qwen3:32b", engine_key="ollama")
    j._config.agent.max_turns = 5

    # Clean and index
    db_path = os.path.expanduser("~/.openjarvis/memory.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    print("Indexing facts...")
    for fact in FACTS:
        j.ask_full(
            "Store:\n\n" + fact,
            agent="orchestrator",
            tools=["memory_store"],
            temperature=0.1,
        )
    print(f"Indexed {len(FACTS)} facts.\n")

    # Track tool calls
    tool_log: list[dict] = []

    def on_tool(event):
        tool_log.append({
            "tool": event.data.get("tool", ""),
            "args": event.data.get("arguments", ""),
        })

    j._bus.subscribe(EventType.TOOL_CALL_START, on_tool)

    # Post parent message
    parent_ts = slack_send(
        "*OpenJarvis Twitter Bot — Overnight Preview*\n"
        f"Generating a tweet every ~{INTERVAL_MINUTES} min. "
        "Check this thread in the morning.",
    )
    print(f"Parent message posted (ts={parent_ts})")

    recent: list[str] = []
    tweet_count = 0
    cycle = 0

    while True:
        cycle += 1
        topic = random.choice(TOPICS)

        recent_section = ""
        if recent:
            recent_list = "\n".join('  - "' + t + '"' for t in recent[-8:])
            recent_section = (
                "Your recent tweets (DO NOT repeat any of these ideas "
                "— write something completely different):\n"
                + recent_list
                + "\n"
            )

        tool_log.clear()
        r = j.ask_full(
            "You are @OpenJarvisAI — a researcher/dev who believes local-first "
            "AI is the future. Write one tweet. all lowercase, <=280 chars.\n\n"
            f'1. memory_search: "{topic}"\n'
            "2. Write a tweet that makes someone stop scrolling. Lead with "
            "an insight, a question, or a strong take. Use facts from "
            "the search results.\n"
            + recent_section
            + '3. channel_send channel="twitter", content=<tweet>. '
            "No conversation_id.\n\n"
            "Tweets we love:\n"
            '- "88.7% of queries run fine on local hardware. why is '
            'everyone still paying per API call?"\n'
            '- "your most personal data routes through someone else\'s '
            'server. we built openjarvis to fix that"\n'
            '- "in the 70s computing moved from mainframes to pcs. not '
            'because pcs were more powerful — because they got efficient '
            'enough. ai is at that moment right now"\n'
            '- "we measure energy per query the way most people measure '
            'accuracy. if your ai runs on battery, efficiency is the whole game"\n'
            '- "four rag backends, swap with one config change. been '
            'testing colbert on our docs and the retrieval quality jump is real"\n\n'
            "Only real facts. No invented stats. "
            "Link: https://github.com/open-jarvis/OpenJarvis",
            agent="orchestrator",
            tools=["think", "memory_search", "channel_send"],
            temperature=0.7,
        )

        # Extract tweet from channel_send call, or fall back to response text
        # (the model sometimes writes the tweet in its response instead of
        # calling channel_send)
        tweet = ""
        for tc in tool_log:
            if tc["tool"] == "channel_send":
                a = (
                    tc["args"]
                    if isinstance(tc["args"], dict)
                    else (json.loads(tc["args"]) if tc["args"] else {})
                )
                tweet = a.get("content", "")
                break

        if not tweet:
            # Fallback: extract from response text
            raw = r.get("content", "").strip()
            # Strip quotes if the model wrapped it
            if raw.startswith('"') and raw.endswith('"'):
                raw = raw[1:-1]
            # Only use it if it looks like a tweet (short, not an explanation)
            if 0 < len(raw) <= 300 and "here's" not in raw.lower():
                tweet = raw[:280]

        ts = time.strftime("%H:%M")
        if tweet:
            tweet_count += 1
            slack_send(f"{tweet_count}. {tweet}", thread_ts=parent_ts)
            recent.append(tweet)
            # Keep last 10 for context
            if len(recent) > 10:
                recent.pop(0)
            print(f"[{ts}] #{tweet_count}: {tweet[:80]}...")
        else:
            print(f"[{ts}] cycle {cycle}: empty, skipped")

        # Wait with jitter
        jitter = random.uniform(0.8, 1.2)
        wait = INTERVAL_MINUTES * 60 * jitter
        print(f"  next tweet in {wait/60:.0f} min")
        time.sleep(wait)


if __name__ == "__main__":
    main()
