# skillorchestra — faithful port of SkillOrchestra (arXiv:2602.19672)

This package replaces the old single-file `skillorchestra.py` (a 2-agent
JSON router that shared none of the original's prompts or structure). It
restructures the agent to **be** the original's eval-orchestrator runtime.

## What's faithful

- **Prompts** — `prompts/` is a verbatim copy of the upstream
  `skillorchestra/prompts/` package (`eval_orchestrator.py`,
  `model_routing.py`, `learning.py`).
- **Handbook + routing** — `stage_router.py` and `types.py` are verbatim
  copies of upstream `adapters/stage_router.py` and `core/types.py`:
  `StageSkillHandbook`, `parse_skill_analysis`, and all 5 routing
  strategies (`router_decides`, `analyze_model_decide`, `weighted_avg`,
  `weakest_skill`, `strongest_skill`).
- **Loop** — `orchestrator.py` ports `eval_frames.py:run_single`: the
  multi-round `search -> reasoning -> answer` ReAct loop, the verbatim
  worker prompts, `<skill_analysis>` parsing, alias-based model routing,
  last-round forced answer.
- **Code tool** — `tools.run_code` runs model-generated Python in a real
  `subprocess` with a timeout, exactly as upstream.

## What can't match without infrastructure

The original runtime needs three things this cluster doesn't have. Each
degrades gracefully and is configurable:

| Original | Here |
|---|---|
| FAISS wiki retriever for `search` | `method_cfg.retriever_url` POSTs the same `/retrieve` payload; absent → Anthropic `web_search` |
| 6+ SGLang-served pool models | alias tiers collapse onto the cell's local/cloud pair; override per alias via `method_cfg.model_pool` |
| Learned `handbook.json` from explore→learn→select | `method_cfg.handbook_path` (a hand-authored `handbook_seed.json` ships here); absent → `routing_strategy="none"`, the original's baseline mode |

The offline explore→learn→select pipeline is **not** ported — it needs
the served model pool + FRAMES/NQ datasets to run. The handbook *schema*
it produces is fully supported by `StageSkillHandbook.load`, so a learned
handbook can be dropped in later with no code change.

SWE-bench is out of scope for the original (a QA orchestrator). SWE cells
run the cloud backbone through the shared `mini_swe_agent` loop.

## method_cfg

`routing_strategy`, `handbook_path`, `max_rounds`, `retriever_url`,
`model_pool`, `orchestrator_model` / `orchestrator_endpoint`,
`code_timeout_s`, `answer_max_tokens`, `context_char_cap`. `router_model`
/ `router_endpoint` are accepted as back-compat aliases.
