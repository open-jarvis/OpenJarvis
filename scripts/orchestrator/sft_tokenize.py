#!/usr/bin/env python
"""Conversation->tokens + assistant-only masking shared by the SFT trainers.

Extracted from the old LoRA trainer so ``run_sft_fsdp.py`` (full-parameter FSDP,
the path we actually use) doesn't depend on it. ``build_example`` tokenizes one
``conversations`` record and returns ``input_ids`` + ``labels`` with everything
but the supervised assistant turns masked to -100.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def normalize_messages(conversations: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Map raw conversation turns to {role, content} with role in
    system/user/assistant. tool turns fold into user (matches the native
    OrchestratorSFTDataset fallback)."""
    msgs: List[Dict[str, str]] = []
    for turn in conversations:
        role = turn.get("role") or turn.get("from", "")
        content = turn.get("content") or turn.get("value", "") or ""
        if role in ("human", "user"):
            role = "user"
        elif role in ("gpt", "assistant"):
            role = "assistant"
        elif role == "tool":
            content = f"[Tool '{turn.get('name', 'tool')}' returned]: {content}"
            role = "user"
        if role in ("system", "user", "assistant"):
            msgs.append({"role": role, "content": str(content)})
    return msgs


def _lcp_len(a: List[int], b: List[int]) -> int:
    """Length of the longest common prefix of two token-id lists."""
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def _chatml_assistant_spans(ids: List[int], tok) -> Optional[List[tuple]]:
    """``(start, end)`` token spans of each assistant turn's content in a
    ChatML-rendered sequence, located by ``<|im_start|>assistant ... <|im_end|>``
    markers (the ``<|im_end|>`` is included so the model learns to stop).

    Operates on the FINAL token stream, so it is correct even when the chat
    template strips prior-turn ``<think>`` reasoning from history (Qwen3.x does),
    which breaks any incremental re-rendering / prefix approach. Returns None for
    non-ChatML templates (e.g. gemma) so the caller can fall back."""
    im_start = tok.convert_tokens_to_ids("<|im_start|>")
    im_end = tok.convert_tokens_to_ids("<|im_end|>")
    asst = tok.convert_tokens_to_ids("assistant")
    unk = tok.unk_token_id
    if im_start is None or im_end is None or im_start == unk or im_end == unk:
        return None
    nl = tok.convert_tokens_to_ids("Ċ")  # the '\n' after the role header
    spans: List[tuple] = []
    i, n = 0, len(ids)
    while i < n:
        if ids[i] == im_start and i + 1 < n and ids[i + 1] == asst:
            j = i + 2
            if j < n and ids[j] == nl:
                j += 1
            k = j
            while k < n and ids[k] != im_end:
                k += 1
            end = min(k + 1, n)
            if end > j:
                spans.append((j, end))
            i = end
        else:
            i += 1
    return spans


def build_example(
    tok,
    conversations,
    max_seq: int,
    supervise_all_turns: bool = True,
) -> Optional[Dict[str, List[int]]]:
    """Tokenize one record -> input_ids + labels.

    ``supervise_all_turns=True`` (default): supervise EVERY assistant turn — the
    intermediate routing ``<tool_call>`` turns AND the final answer; only
    system/user/tool tokens are masked. This teaches the model to actually route,
    not just synthesize the last answer given someone else's tool calls.

    ``supervise_all_turns=False`` (legacy): supervise only the final assistant
    turn; everything before it is masked to -100.

    Assistant spans are found by the ChatML turn markers on the rendered stream
    (robust to Qwen3's prior-turn think-stripping). For non-ChatML templates
    (gemma) we fall back to the proven last-turn longest-common-prefix boundary;
    all-turns supervision there needs per-template markers and is not yet wired,
    so it degrades to last-turn. Records whose last turn isn't assistant, that
    supervise nothing, or whose final turn alone overflows max_seq are skipped."""
    msgs = normalize_messages(conversations)
    if len(msgs) < 2 or msgs[-1]["role"] != "assistant":
        return None
    try:
        full_text = tok.apply_chat_template(
            msgs, tokenize=False, add_generation_prompt=False
        )
        full = tok(full_text, add_special_tokens=False)["input_ids"]
    except Exception:
        return None
    if not full:
        return None

    spans = _chatml_assistant_spans(full, tok)
    if spans:
        selected = spans if supervise_all_turns else spans[-1:]
        labels = [-100] * len(full)
        for s, e in selected:
            for k in range(s, e):
                labels[k] = full[k]
        last_start = selected[-1][0]
    else:
        # Non-ChatML template: proven last-turn boundary via longest-common-prefix
        # (robust to templates whose add_generation_prompt emits extra preamble).
        try:
            prompt_text = tok.apply_chat_template(
                msgs[:-1], tokenize=False, add_generation_prompt=True
            )
            prompt = tok(prompt_text, add_special_tokens=False)["input_ids"]
        except Exception:
            return None
        boundary = _lcp_len(prompt, full)
        if boundary >= len(full):
            return None
        labels = list(full)
        for i in range(min(boundary, len(labels))):
            labels[i] = -100
        last_start = boundary

    if all(v == -100 for v in labels):  # nothing left to supervise
        return None

    # Keep the final assistant turn if too long: left-truncate from the front.
    if len(full) > max_seq:
        if len(full) - last_start >= max_seq:  # final answer alone overflows -> drop
            return None
        cut = len(full) - max_seq
        full = full[cut:]
        labels = labels[cut:]
    return {"input_ids": full, "labels": labels}
