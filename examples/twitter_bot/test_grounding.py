#!/usr/bin/env python3
"""Verify that dense retrieval grounds the bot's reply in real doc facts.

Question: "can I run the orchestrator agent on a laptop without a gpu?"
Ground truth is scattered across docs/ — mentions of ``llama.cpp`` (pure
C++ inference, "ideal for laptops without a discrete GPU"), CPU-only
mode, 4B-model recommendation on CPU, Metal on Apple Silicon.

Stages:
  1. **Unground**: backend empty → bot hits the deferral prompt path.
  2. **Grounded**: DenseMemory indexed over README + docs/ → bot hits
     the grounded prompt with retrieved context embedded.

Success: stage 2's reply cites one of the concrete doc facts
(``llama.cpp``, ``4B``, ``metal``, ``cpu-only``, etc.) that are not in
the ungrounded baseline.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))
twitter_bot = importlib.import_module("twitter_bot")
sys.path.pop(0)

_resolve_question_prompt = twitter_bot._resolve_question_prompt
_DemoChannel = twitter_bot._DemoChannel
SCORE_THRESHOLD = twitter_bot.SCORE_THRESHOLD


MENTION = {
    "id": "3000000000000000001",
    "author": "indie_hacker",
    "text": "@OpenJarvisAI can I run the orchestrator agent on a laptop without a gpu?",
}


def _ask_once(j, demo_channel, backend):
    prompt, top_score = _resolve_question_prompt(
        backend, MENTION["author"], MENTION["id"], MENTION["text"],
    )
    demo_channel.last_sent = None
    response = j.ask(
        prompt,
        agent="orchestrator",
        tools=["channel_send"],
        temperature=0.4,
        channel=demo_channel,
    )
    return demo_channel.last_sent or response, top_score


def main():
    from openjarvis import Jarvis
    from openjarvis.tools.storage.dense import DenseMemory

    sys.path.insert(0, str(_THIS.parents[1] / "scripts"))
    from index_docs import build_index  # type: ignore
    sys.path.pop(0)

    model = "gemma4:31b"
    j = Jarvis(model=model, engine_key="ollama")
    demo_channel = _DemoChannel()
    repo_root = Path(__file__).resolve().parents[2]

    print(f"Test question: {MENTION['text']}")
    print(f"Score threshold: {SCORE_THRESHOLD}\n")

    # ------------------------------------------------------------------ #
    print("=" * 80)
    print("STAGE 1: No retrieval — forced deferral path")
    print("=" * 80)
    empty_backend = DenseMemory()  # empty index
    reply_1, score_1 = _ask_once(j, demo_channel, empty_backend)
    print(f"top_score={score_1:.3f}  (threshold={SCORE_THRESHOLD})")
    print(f"Reply: {reply_1}\n")

    # ------------------------------------------------------------------ #
    print("=" * 80)
    print("STAGE 2: Full docs indexed — grounded path if score >= threshold")
    print("=" * 80)
    backend = build_index(repo_root)
    print(f"Indexed {backend.count()} chunks from README + docs/")

    # Show what the retriever actually surfaces for the mention text
    print("\nTop 3 hits for the mention text:")
    hits = backend.retrieve(MENTION["text"], top_k=3)
    for i, h in enumerate(hits, 1):
        preview = h.content.replace("\n", " ")[:180]
        print(
            f"  [{i}] score={h.score:.3f}  src={h.source}"
            f"  bc={h.metadata.get('breadcrumb', '')}"
        )
        print(f"      {preview}{'...' if len(h.content) > 180 else ''}")
    print()

    reply_2, score_2 = _ask_once(j, demo_channel, backend)
    print(f"top_score={score_2:.3f}  (threshold={SCORE_THRESHOLD})")
    print(f"Reply: {reply_2}\n")

    # ------------------------------------------------------------------ #
    print("=" * 80)
    print("COMPARISON")
    print("=" * 80)
    print(f"Without docs (score {score_1:.2f}): {reply_1}")
    print(f"With docs    (score {score_2:.2f}): {reply_2}")
    print()

    grounding_terms = [
        "llama.cpp", "llama cpp", "4b", "metal", "apple silicon",
        "cpu-only", "cpu only", "rocm", "quantization", "ollama",
        "vllm", "sglang", "mlx",
    ]
    r2_lower = reply_2.lower()
    mentioned = [t for t in grounding_terms if t in r2_lower]
    print(f"Grounding signals in stage 2 reply: {mentioned or 'none'}")

    j.close()


if __name__ == "__main__":
    main()
