#!/usr/bin/env python3
"""Stress-test the twitter bot on diverse mentions with the dense-retrieval pipeline.

For each mention:
  * captures the actual ``channel_send`` payload (the tweet that would be sent)
  * for QUESTIONs, records whether retrieval scored above threshold
    (grounded path) or below (deferral path)
  * scores the reply against voice rules
"""

from __future__ import annotations

import importlib
import re
import sys
import time
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))
twitter_bot = importlib.import_module("twitter_bot")
sys.path.pop(0)

_classify_mention = twitter_bot._classify_mention
_build_bug_prompt = twitter_bot._build_bug_prompt
_build_feature_prompt = twitter_bot._build_feature_prompt
_build_praise_prompt = twitter_bot._build_praise_prompt
_resolve_question_prompt = twitter_bot._resolve_question_prompt
_DemoChannel = twitter_bot._DemoChannel
SCORE_THRESHOLD = twitter_bot.SCORE_THRESHOLD


REAL_WORLD_MENTIONS = [
    # === QUESTIONs that should ground (docs cover them) ===
    {
        "id": "3000000000000000001",
        "author": "ml_researcher",
        "text": (
            "@OpenJarvisAI does this work with vllm or "
            "do I need ollama specifically?"
        ),
    },
    {
        "id": "3000000000000000002",
        "author": "indie_hacker",
        "text": (
            "@OpenJarvisAI can I run the orchestrator agent "
            "on a laptop without a gpu?"
        ),
    },
    {
        "id": "3000000000000000003",
        "author": "macuser",
        "text": "@OpenJarvisAI how do I install on macos with apple silicon?",
    },
    {
        "id": "3000000000000000004",
        "author": "longwinded_lou",
        "text": (
            "@OpenJarvisAI how does the memory system handle "
            "conflicting facts? overwrite or keep both?"
        ),
    },

    # === QUESTIONs that should defer (off-topic / unknowable) ===
    {
        "id": "3000000000000000005",
        "author": "off_topic_olive",
        "text": "@OpenJarvisAI what's the weather in tokyo today?",
    },
    {
        "id": "3000000000000000006",
        "author": "specific_specs",
        "text": (
            "@OpenJarvisAI what's the exact tokens-per-second "
            "on an M3 Pro with the 70B model?"
        ),
    },

    # === BUG / FEATURE / PRAISE / SPAM ===
    {
        "id": "3000000000000000007",
        "author": "devops_dan",
        "text": (
            "@OpenJarvisAI getting a segfault on startup "
            "with the lemonade backend, 0.18.2"
        ),
    },
    {
        "id": "3000000000000000008",
        "author": "enterprise_eng",
        "text": (
            "@OpenJarvisAI any plans for SSO support? "
            "would love to deploy this internally"
        ),
    },
    {
        "id": "3000000000000000009",
        "author": "convert_carl",
        "text": (
            "@OpenJarvisAI switched from langchain last week, this is incredible"
        ),
    },
    {
        "id": "3000000000000000010",
        "author": "crypto_bro",
        "text": "@OpenJarvisAI BUY $JARVIS COIN guaranteed 10x gains link in bio",
    },
]


_EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001FAFF"
    r"\U00002600-\U000027BF"
    r"\U0001F900-\U0001F9FF]",
)


def _check_voice(reply: str) -> dict:
    has_upper = bool(re.search(r"[A-Z]", reply))
    has_emoji = bool(_EMOJI_RE.search(reply))
    has_hashtag = "#" in reply
    return {
        "len": len(reply),
        "<=280": len(reply) <= 280,
        "lowercase": not has_upper,
        "no_emoji": not has_emoji,
        "no_hashtag": not has_hashtag,
    }


def main():
    from openjarvis import Jarvis

    sys.path.insert(0, str(_THIS.parents[1] / "scripts"))
    from index_docs import build_index  # type: ignore
    sys.path.pop(0)

    model = "gemma4:31b"
    print("Building dense index from README + docs/...", flush=True)
    backend = build_index(Path(__file__).resolve().parents[2])
    print(f"Indexed {backend.count()} chunks.\n", flush=True)

    j = Jarvis(model=model, engine_key="ollama")
    demo_channel = _DemoChannel()

    results = []
    print(f"Testing {len(REAL_WORLD_MENTIONS)} mentions with {model}...\n", flush=True)

    try:
        for idx, tweet in enumerate(REAL_WORLD_MENTIONS, 1):
            mention_type = _classify_mention(tweet["text"])
            print(
                f"[{idx}/{len(REAL_WORLD_MENTIONS)}] [{mention_type}] "
                f"@{tweet['author']}: {tweet['text'][:70]}",
                flush=True,
            )

            entry = {
                "n": idx,
                "author": tweet["author"],
                "text": tweet["text"],
                "type": mention_type,
                "reply": "[ignored]",
                "voice": None,
                "ground_state": "",
                "score": 0.0,
                "secs": 0.0,
            }

            if mention_type == "SPAM":
                results.append(entry)
                print("   -> [ignored]\n", flush=True)
                continue

            if mention_type == "QUESTION":
                prompt, score = _resolve_question_prompt(
                    backend, tweet["author"], tweet["id"], tweet["text"],
                )
                tools = ["channel_send"]
                entry["score"] = score
                entry["ground_state"] = (
                    "grounded" if score >= SCORE_THRESHOLD else "deferred"
                )
                print(
                    f"   retrieval top-1: {score:.3f}  ->  {entry['ground_state']}",
                    flush=True,
                )
            elif mention_type == "BUG_REPORT":
                prompt = _build_bug_prompt(
                    tweet["author"], tweet["id"], tweet["text"],
                )
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
            t0 = time.time()
            try:
                response = j.ask(
                    prompt,
                    agent="orchestrator",
                    tools=tools,
                    temperature=0.4,
                    channel=demo_channel,
                )
            except Exception as exc:
                response = f"<error: {exc}>"
            elapsed = time.time() - t0

            reply = demo_channel.last_sent or response
            entry["reply"] = reply
            entry["voice"] = _check_voice(reply)
            entry["secs"] = elapsed
            results.append(entry)
            print(f"   -> {reply[:140]}", flush=True)
            print(f"   ({elapsed:.1f}s)\n", flush=True)
    finally:
        j.close()

    # Print results table
    print("\n" + "=" * 110)
    print("RESULTS TABLE")
    print("=" * 110 + "\n")

    print("| # | Type | State | Score | Mention | Reply | Len | voice OK |")
    print("|---|------|-------|-------|---------|-------|-----|----------|")
    for r in results:
        if r["voice"] is None:
            print(
                f"| {r['n']} | {r['type']} | - | - | "
                f"@{r['author']}: {r['text'][:50]}... "
                "| _[ignored]_ | - | - |",
            )
        else:
            v = r["voice"]
            ok = all([v["<=280"], v["lowercase"], v["no_emoji"], v["no_hashtag"]])
            score_str = f"{r['score']:.2f}" if r['type'] == 'QUESTION' else "-"
            state = r["ground_state"] or "-"
            short_reply = r["reply"][:80].replace("\n", " ").replace("|", "/")
            short_text = r["text"][:50].replace("|", "/")
            reply_suffix = "..." if len(r["reply"]) > 80 else ""
            print(
                f"| {r['n']} | {r['type'][:8]} | {state} | {score_str} | "
                f"@{r['author']}: {short_text}... "
                f"| {short_reply}{reply_suffix} "
                f"| {v['len']} | {'yes' if ok else 'NO'} |",
            )

    # Voice rules summary
    scored = [r for r in results if r["voice"] is not None]
    if scored:
        n = len(scored)
        n280 = sum(1 for r in scored if r["voice"]["<=280"])
        nlow = sum(1 for r in scored if r["voice"]["lowercase"])
        nemo = sum(1 for r in scored if r["voice"]["no_emoji"])
        nhash = sum(1 for r in scored if r["voice"]["no_hashtag"])
        print(
            f"\nVoice compliance: <=280: {n280}/{n}, "
            f"lowercase: {nlow}/{n}, no emoji: {nemo}/{n}, "
            f"no hashtag: {nhash}/{n}",
        )
        avg_secs = sum(r["secs"] for r in scored) / n
        print(f"Avg latency: {avg_secs:.1f}s")


if __name__ == "__main__":
    main()
