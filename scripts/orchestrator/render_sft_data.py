#!/usr/bin/env python
"""Render an orchestrator SFT JSONL into human-viewable companions.

The trainer-facing ``*.jsonl`` packs every trajectory onto one line with all
newlines escaped, which is unreadable by eye. This writes two siblings next to
it so you can actually inspect what the orchestrator did:

* ``<name>.pretty.json`` — the same records as an indented JSON array.
* ``<name>.txt``         — a clean plain-text transcript. The shared system
  prompt + tool catalog (identical across every record) is printed ONCE at the
  top; each trajectory then shows just its turns: the user question, the
  assistant's reasoning/answer, tool calls rendered as ``-> name({args})``, and
  tool results truncated so a single web-search dump doesn't bury the trace.

Usage:
    .venv/bin/python scripts/orchestrator/render_sft_data.py <path.jsonl>
"""

from __future__ import annotations

import html as _htmllib
import json
import re
import sys
from pathlib import Path
from typing import List

# Tool observations (web_search dumps, code stdout, file reads) can be huge; cap
# them in the transcript so the actual orchestration stays legible. The full
# content is always in the .jsonl / .pretty.json.
_OBS_CAP = 1200
_RULE = "-" * 80
_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


def _parse_tool_calls(content: str):
    """Parse the model's ``<tool_call>{json}</tool_call>`` tags into a list of
    parsed ``[(name, arguments_dict), ...]`` calls, de-duplicating the
    double-emit the template produces (each call shows up twice)."""
    seen = []
    for m in _TOOL_CALL_RE.finditer(content):
        try:
            call = json.loads(m.group(1))
            item = (call.get("name"), call.get("arguments", {}))
        except Exception:
            item = (None, {"_raw": m.group(1)})
        key = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        if not seen or seen[-1][0] != key:  # collapse the adjacent duplicate
            seen.append((key, item))
    return [it for _, it in seen]


def _call_label(name, anon_map) -> str:
    """Display a call name; if it's an anonymized expert label, append the real
    model it maps to (from the record's ``metrics.anon_map``)."""
    real = (anon_map or {}).get(name)
    return f"{name}  ->  {real}" if real else f"{name}"


def _fmt_tool_calls(content: str, anon_map=None) -> str:
    """Plain-text tool calls with real (un-escaped) newlines in each arg value."""
    blocks = []
    for name, args in _parse_tool_calls(content):
        lines = [f"-> {_call_label(name, anon_map)}"]
        if isinstance(args, dict):
            for k, v in args.items():
                val = (
                    v
                    if isinstance(v, str)
                    else json.dumps(v, ensure_ascii=False, indent=2)
                )
                indented = "\n".join("       " + ln for ln in val.splitlines())
                lines.append(f"   {k}:\n{indented}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def _clip(text: str, cap: int) -> str:
    text = text or ""
    if len(text) <= cap:
        return text
    return f"{text[:cap]}\n  ... [truncated {len(text) - cap} chars]"


def _render_turn(turn: dict, anon_map=None) -> str:
    role = str(turn.get("role", "?")).lower()
    content = turn.get("content", "") or ""

    if role == "user":
        return f"USER:\n{content.strip()}"

    if role in ("tool", "function"):
        name = turn.get("name", "tool")
        return f"TOOL [{name}]:\n{_clip(content.strip(), _OBS_CAP)}"

    if role == "assistant":
        calls = _fmt_tool_calls(content, anon_map)
        # Strip the raw <tool_call> tags out of the prose so it isn't shown twice.
        prose = _TOOL_CALL_RE.sub("", content).strip()
        parts = []
        if prose:
            parts.append(f"ASSISTANT:\n{prose}")
        if calls:
            parts.append(f"ASSISTANT calls:\n{calls}")
        return "\n".join(parts) if parts else "ASSISTANT: (empty)"

    # system handled separately (printed once); fall through for anything else
    return f"{role.upper()}:\n{content.strip()}"


def _transcript(record: dict, index: int) -> str:
    m = record.get("metrics", {}) or {}
    correct = record.get("correct")
    kept = record.get("kept")
    flags = []
    if correct is not None:
        flags.append("correct" if correct else "WRONG")
    if kept is not None and kept:
        flags.append("kept")
    head = (
        f"### [{index}] task={record.get('task_id')}  domain={record.get('domain')}"
        + (f"  {' '.join(flags)}" if flags else "")
        + f"\n    cost=${m.get('cost_usd')}  tokens={m.get('tokens')}  "
        f"tool_calls={m.get('num_tool_calls')}  turns={m.get('num_turns')}  "
        f"reward={record.get('reward')}"
    )
    anon_map = m.get("anon_map")
    body = [
        _render_turn(t, anon_map)
        for t in record.get("conversations", [])
        if str(t.get("role", "")).lower() != "system"
    ]
    return head + "\n\n" + "\n\n".join(body)


def _system_header(records: List[dict]) -> str:
    """The system message is identical across records — render it once."""
    for r in records:
        for t in r.get("conversations", []):
            if str(t.get("role", "")).lower() == "system":
                return (
                    "=" * 80 + "\nSHARED SYSTEM PROMPT + TOOL CATALOG "
                    "(identical for every record below)\n"
                    + "=" * 80
                    + f"\n{t.get('content', '').strip()}\n"
                )
    return ""


_HTML_CSS = """
body{font:14px/1.5 system-ui,sans-serif;margin:0;background:#f5f5f7;color:#1d1d1f}
header{position:sticky;top:0;background:#1d1d1f;color:#fff;padding:12px 20px;z-index:9}
header b{font-size:16px}
.rec{background:#fff;margin:14px 20px;border-radius:10px;box-shadow:0 1px 3px #0002;overflow:hidden}
.rec>summary{cursor:pointer;padding:10px 16px;font-weight:600;list-style:none;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
.rec>summary::-webkit-details-marker{display:none}
.rec>summary:hover{background:#fafafa}
.body{padding:6px 16px 16px}
.turn{margin:10px 0;padding:10px 14px;border-radius:8px;white-space:pre-wrap;word-break:break-word}
.user{background:#e8f0fe}
.assistant{background:#f1f8e9}
.call{background:#fff3e0}
.call .cname{font-family:ui-monospace,monospace;font-weight:700;color:#b25b00;margin-bottom:6px}
.call .cname .real{background:#b25b00;color:#fff;padding:1px 7px;border-radius:10px;font-size:12px;margin-left:4px}
.call .arg{margin:6px 0 0 14px}
.call .arg b{font-family:ui-monospace,monospace;color:#7a4500}
.call .arg pre{white-space:pre-wrap;word-break:break-word;margin:3px 0 0;padding:8px 10px;background:#fff;border:1px solid #f0d9b8;border-radius:6px;font-size:13px}
.tool details{background:#fafafa;border:1px solid #eee;border-radius:8px;padding:6px 10px;margin:10px 0}
.tool summary{cursor:pointer;color:#555;font-weight:600}
.tool pre{white-space:pre-wrap;word-break:break-word;margin:8px 0 0;font-size:13px}
.role{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:#888;margin-bottom:4px}
.pill{font-size:12px;padding:2px 8px;border-radius:10px;font-weight:600}
.ok{background:#d7f5dd;color:#1a7f37}.wrong{background:#ffe0e0;color:#c0392b}
.kept{background:#fff0c2;color:#9a6700}.dom{background:#eee;color:#444}
.meta{font-weight:400;color:#888;font-size:12px}
#sys details{margin:14px 20px;background:#fff;border-radius:10px;padding:10px 16px}
#sys pre{white-space:pre-wrap;word-break:break-word;font-size:12px;color:#444}
"""


def _esc(s: str) -> str:
    return _htmllib.escape(s or "")


def _html_turns(record: dict) -> str:
    anon_map = (record.get("metrics", {}) or {}).get("anon_map") or {}
    out = []
    for t in record.get("conversations", []):
        role = str(t.get("role", "")).lower()
        content = t.get("content", "") or ""
        if role == "system":
            continue
        if role == "user":
            out.append(
                f'<div class="turn user"><div class="role">user</div>{_esc(content.strip())}</div>'
            )
        elif role in ("tool", "function"):
            name = _esc(t.get("name", "tool"))
            out.append(
                f'<div class="tool"><details><summary>tool result · {name} '
                f"({len(content)} chars)</summary><pre>{_esc(content.strip())}</pre></details></div>"
            )
        elif role == "assistant":
            prose = _TOOL_CALL_RE.sub("", content).strip()
            if prose:
                out.append(
                    f'<div class="turn assistant"><div class="role">assistant</div>{_esc(prose)}</div>'
                )
            for name, args in _parse_tool_calls(content):
                real = anon_map.get(name)
                label = (
                    f'{_esc(str(name))} <span class="real">&rarr; {_esc(str(real))}</span>'
                    if real
                    else _esc(str(name))
                )
                rows = [f'<div class="cname">&rarr; {label}</div>']
                if isinstance(args, dict):
                    for k, v in args.items():
                        val = (
                            v
                            if isinstance(v, str)
                            else json.dumps(v, ensure_ascii=False, indent=2)
                        )
                        rows.append(
                            f'<div class="arg"><b>{_esc(str(k))}</b><pre>{_esc(val)}</pre></div>'
                        )
                out.append(
                    f'<div class="turn call"><div class="role">tool call</div>{"".join(rows)}</div>'
                )
    return "".join(out)


def _html_record(record: dict, index: int) -> str:
    m = record.get("metrics", {}) or {}
    pills = [f'<span class="pill dom">{_esc(str(record.get("domain")))}</span>']
    correct = record.get("correct")
    if correct is not None:
        pills.append(
            '<span class="pill ok">correct</span>'
            if correct
            else '<span class="pill wrong">wrong</span>'
        )
    if record.get("kept"):
        pills.append('<span class="pill kept">kept</span>')
    meta = (
        f'<span class="meta">cost ${m.get("cost_usd")} · {m.get("tokens")} tok · '
        f"{m.get('num_tool_calls')} calls · {m.get('num_turns')} turns</span>"
    )
    summary = (
        f"<span>#{index}</span><span>{_esc(str(record.get('task_id')))}</span>"
        + "".join(pills)
        + meta
    )
    return (
        f'<details class="rec"><summary>{summary}</summary>'
        f'<div class="body">{_html_turns(record)}</div></details>'
    )


def _html_doc(records: List[dict], title: str) -> str:
    sys_txt = ""
    for r in records:
        for t in r.get("conversations", []):
            if str(t.get("role", "")).lower() == "system":
                sys_txt = t.get("content", "")
                break
        if sys_txt:
            break
    recs_html = "".join(_html_record(r, i + 1) for i, r in enumerate(records))
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><title>{_esc(title)}</title>"
        f"<style>{_HTML_CSS}</style></head><body>"
        f"<header><b>{_esc(title)}</b> &nbsp; {len(records)} records "
        f"&middot; click a row to expand</header>"
        f"<div id='sys'><details><summary style='cursor:pointer;font-weight:600;padding:4px'>"
        f"Shared system prompt + tool catalog (same for all)</summary>"
        f"<pre>{_esc(sys_txt.strip())}</pre></details></div>"
        f"{recs_html}</body></html>"
    )


def render(jsonl_path: str) -> dict:
    src = Path(jsonl_path)
    records: List[dict] = []
    with src.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    pretty = src.with_suffix(".pretty.json")
    pretty.write_text(json.dumps(records, indent=2, ensure_ascii=False))

    txt = src.with_suffix(".txt")
    banner = f"ORCHESTRATOR SFT TRANSCRIPT — {src.name}\n{len(records)} records\n\n"
    sep = f"\n\n{_RULE}\n\n"
    parts = [banner + _system_header(records)]
    parts.append(sep.join(_transcript(r, i + 1) for i, r in enumerate(records)))
    txt.write_text("\n\n".join(parts))

    htmlp = src.with_suffix(".html")
    htmlp.write_text(_html_doc(records, src.name))

    return {
        "records": len(records),
        "pretty": str(pretty),
        "txt": str(txt),
        "html": str(htmlp),
    }


def main(argv: List[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    info = render(argv[0])
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
