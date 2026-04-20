---
title: Skills
description: Reusable compositions of tools and agent instructions — discover, import, optimize, and share
search.boost: 2.0
---

# Skills

Skills teach agents **how to better use tools and improve their reasoning**. They are reusable compositions of tools, sub-skills, and agent instructions that can be shared via public registries.

Every skill is a tool. Skills appear in a lightweight catalog in the agent's system prompt, and when the agent invokes one, its content (pipeline results, markdown instructions, or both) gets injected into the conversation context.

## Overview

| Concept | Description |
|---------|-------------|
| **Skill** | A directory containing `skill.toml` (structured pipeline), `SKILL.md` (markdown instructions), or both |
| **SkillManager** | Central coordinator for discovery, resolution, catalog generation, and tool wrapping |
| **SkillTool** | Adapter that wraps any skill as a `BaseTool` so agents can invoke it |
| **Overlay** | Sidecar file at `~/.openjarvis/learning/skills/` storing optimized descriptions and few-shot examples |
| **Source** | A resolver for importing skills from Hermes Agent, OpenClaw, or any GitHub repo |

## Quick Start

```bash
# List installed skills
jarvis skill list

# Install a skill from Hermes Agent
jarvis skill install hermes:apple-notes

# Bulk install a category
jarvis skill sync hermes --category research

# Run a skill directly
jarvis skill run math-solver -a expression="41 + 82"

# See skill details
jarvis skill info research-and-summarize
```

## Skill Definition Format

A skill is a directory containing a `skill.toml`, a `SKILL.md`, or both.

### Directory Structure

```
research-and-summarize/
├── SKILL.md              # Markdown instructions (loaded on invocation)
├── skill.toml            # Structured pipeline steps
├── templates/            # Optional Jinja2 templates
├── scripts/              # Optional executable helpers
├── references/           # Optional detailed docs
├── assets/               # Optional static resources
└── examples/             # Optional usage examples
```

### skill.toml (Structured Pipeline)

Pipeline skills define a sequence of tool calls that execute deterministically:

```toml
[skill]
name = "research-and-summarize"
version = "0.1.0"
description = "Search the web and produce a structured summary"
author = "openjarvis"
tags = ["research", "summarization"]
required_capabilities = ["network:fetch"]
depends = ["summarize"]

[[skill.steps]]
tool_name = "web_search"
arguments_template = '{"query": "{query}"}'
output_key = "search_results"

[[skill.steps]]
skill_name = "summarize"
arguments_template = '{"text": "{search_results}"}'
output_key = "summary"
```

Steps can call tools (`tool_name`) or other skills (`skill_name`). Template placeholders like `{query}` become the skill's input parameters. Output keys chain between steps.

### SKILL.md (Instructional Content)

Instructional skills provide markdown guidance that agents follow using their other tools:

```markdown
---
name: code-explainer
description: Explain code in plain language with examples
license: MIT
metadata:
  openjarvis:
    version: "0.1.0"
    author: openjarvis
    tags: [coding, explanation]
---

When asked to explain code, follow this approach:

1. Identify the programming language
2. Break the code into logical sections
3. Explain each section in plain language
4. Highlight any patterns, idioms, or potential issues
5. Provide a one-sentence summary at the end
```

The YAML frontmatter follows the [agentskills.io](https://agentskills.io/specification) open standard. Required fields: `name`, `description`. Optional: `license`, `compatibility`, `metadata`, `allowed-tools`.

### What Happens on Invocation

| Skill has | On invocation |
|-----------|---------------|
| `skill.toml` steps only | Execute the pipeline, return results |
| `SKILL.md` only | Return the markdown instructions — agent follows them in subsequent turns |
| Both | Execute pipeline steps AND return the markdown guidance alongside results |

## Installing Skills

### From Hermes Agent

```bash
# Single skill
jarvis skill install hermes:apple-notes

# Bulk install by category
jarvis skill sync hermes --category research
jarvis skill sync hermes --category coding
jarvis skill sync hermes  # everything (~150 skills)
```

### From OpenClaw

```bash
# Single skill (owner/slug format)
jarvis skill install openclaw:0xv4l3nt1n3/etherscan

# Bulk install with search filter
jarvis skill sync openclaw --search "web3|crypto"
```

### From Any GitHub Repo

```bash
jarvis skill install github:user/repo/path/to/skill --url https://github.com/user/repo
```

### Config-Driven Auto Import

Add sources to `~/.openjarvis/config.toml` for automatic syncing:

```toml
[skills]
enabled = true
auto_sync = true

[[skills.sources]]
source = "hermes"
filter = { category = ["research", "coding", "productivity"] }
auto_update = true

[[skills.sources]]
source = "openclaw"
filter = { search = "web3|crypto" }
```

When `auto_sync = true`, the SkillManager checks source freshness on each session start and pulls updates in the background.

### Managing Sources

```bash
# List configured sources
jarvis skill sources

# Update all configured sources
jarvis skill update
```

## How Agents Use Skills

### Skill Catalog in the System Prompt

All available skills appear as a lightweight XML catalog in the agent's system prompt:

```xml
<available_skills>
  <skill name="research-and-summarize" description="Search the web and produce a structured summary" />
  <skill name="code-explainer" description="Explain code in plain language with examples" />
  <skill name="math-solver" description="Solve a math problem step by step using the calculator" />
</available_skills>
```

The agent reads this catalog and decides when to invoke a skill based on the user's request.

### Invocation Control

Per-skill flags control visibility:

```toml
[skill]
user_invocable = true              # expose as CLI command (default: true)
disable_model_invocation = false   # hide from agent catalog (default: false)
```

| `user_invocable` | `disable_model_invocation` | CLI command? | Agent discovers? |
|---|---|---|---|
| true (default) | false (default) | Yes | Yes |
| true | true | Yes | No |
| false | false | No | Yes |
| false | true | No | No (dormant) |

### Pipeline vs. Instructional Skills

Agents handle both skill types correctly:

- **Pipeline skills** (with `skill.toml` steps) execute deterministically and return computed results. The agent uses the result directly in its answer.
- **Instructional skills** (with `SKILL.md` only) return markdown text describing HOW to accomplish a task. The agent reads the instructions and follows them using its other tools (web_search, shell_exec, calculator, etc.).

## Skill Discovery from Traces

OpenJarvis can automatically mine your trace history for recurring tool sequences and surface them as candidate skills:

```bash
# Preview discovered patterns without writing
jarvis skill discover --dry-run --min-frequency 3

# Write discovered skills to ~/.openjarvis/skills/discovered/
jarvis skill discover
```

Discovered skills land in `~/.openjarvis/skills/discovered/` and automatically appear in `jarvis skill list` on the next session.

## Skill Optimization

### Optimizing with DSPy or GEPA

The skills learning loop uses your trace history to optimize skill descriptions and extract few-shot examples:

```bash
# Preview what would be optimized
jarvis optimize skills --dry-run

# Run DSPy optimization
jarvis optimize skills --policy dspy --min-traces 3

# Run GEPA evolutionary optimization
jarvis optimize skills --policy gepa --min-traces 3

# Inspect what optimization produced
jarvis skill show-overlay research-and-summarize
```

Optimization results are stored as sidecar overlays at `~/.openjarvis/learning/skills/<skill-name>/optimized.toml`. They override the skill's description and add few-shot examples to the agent's system prompt. The original skill files are never modified.

### Auto-Optimization

Enable automatic optimization in config:

```toml
[learning.skills]
auto_optimize = false       # set to true to enable
optimizer = "dspy"          # "dspy" or "gepa"
min_traces_per_skill = 20
```

When enabled, the `LearningOrchestrator` runs skill optimization after each learning cycle.

## Benchmarking Skills

Measure whether skills improve agent performance:

```bash
# Full sweep: 4 conditions × 3 seeds
jarvis bench skills

# Smoke test: 4 conditions × 1 seed × 5 tasks
jarvis bench skills --max-samples 5 --seeds 42

# Single condition
jarvis bench skills --condition skills_optimized_dspy
```

The four benchmark conditions are:

| Condition | What it tests |
|---|---|
| `no_skills` | Skills disabled (control) |
| `skills_on` | Skills enabled, no optimization |
| `skills_optimized_dspy` | DSPy-optimized overlays |
| `skills_optimized_gepa` | GEPA-optimized overlays |

Results are written to `docs/superpowers/results/pinchbench-skills-eval-{date}.md` with a summary table, per-task breakdown, deltas, and skill invocation counts.

## Security & Trust

### Trust Tiers

| Tier | Source | Verification | Runtime |
|------|--------|-------------|---------|
| **Bundled** | Ships with OpenJarvis | Implicit trust | Full access within declared capabilities |
| **Indexed** | In official skill index, signed | SHA256 + Ed25519 | Capability-gated |
| **Unreviewed** | Arbitrary GitHub URL | SHA256 only | Capability-gated + sandbox warning |
| **Workspace** | Local `./skills/` directory | None (user code) | Trusted |

### Capability Enforcement

Skills declare required capabilities. At runtime, the SkillExecutor checks that each tool call falls within the skill's declared capabilities:

- `network:fetch` — outbound HTTP requests
- `filesystem:read` / `filesystem:write` — file access
- `shell:execute` — run shell commands (dangerous)
- `memory:read` / `memory:write` — memory backend access
- `engine:inference` — LLM calls

Skills declaring dangerous capabilities (`shell:execute`, `network:listen`, `filesystem:write`) trigger install-time warnings and sandbox recommendations.

### Scripts

Imported skills may include `scripts/` directories with executable code. These are **skipped by default** for security. Use `--with-scripts` to opt in:

```bash
jarvis skill install hermes:arxiv --with-scripts
```

## Skill Composition

Skills can invoke other skills as sub-steps:

```toml
[[skill.steps]]
skill_name = "summarize"
arguments_template = '{"text": "{search_results}"}'
output_key = "summary"
```

The SkillManager builds a dependency graph at discovery time and validates:

1. **No cycles** — `A → B → C → A` is rejected with a clear error
2. **Max depth** — default 5 levels (configurable)
3. **Capability unions** — parent must declare all capabilities its children need

## Configuration Reference

### `[skills]` Section

```toml
[skills]
enabled = true                    # enable/disable the skill system
skills_dir = "~/.openjarvis/skills/"  # where skills are installed
active = "*"                      # which skills to activate ("*" = all)
auto_discover = true              # scan skills_dir on startup
auto_sync = false                 # pull from configured sources on startup
max_depth = 5                     # max sub-skill nesting depth
sandbox_dangerous = true          # warn about dangerous capabilities
```

### `[[skills.sources]]` Section

```toml
[[skills.sources]]
source = "hermes"                 # "hermes", "openclaw", or "github"
url = ""                          # required when source = "github"
filter = { category = ["research", "coding"] }
auto_update = true                # pull latest on sync
```

### `[learning.skills]` Section

```toml
[learning.skills]
auto_optimize = false             # opt-in automatic optimization
optimizer = "dspy"                # "dspy" or "gepa"
min_traces_per_skill = 20         # minimum traces before optimizing
optimization_interval_seconds = 86400  # at most once per day
overlay_dir = "~/.openjarvis/learning/skills/"
```

## Name Precedence

When the same skill name exists in multiple locations, closest scope wins:

1. **Workspace** `./skills/` (highest priority)
2. **User** `~/.openjarvis/skills/`
3. **Bundled** (shipped with OpenJarvis)

## CLI Reference

| Command | Description |
|---------|-------------|
| `jarvis skill list` | List installed skills |
| `jarvis skill info <name>` | Show detailed skill information |
| `jarvis skill run <name> [-a key=value]` | Execute a skill directly |
| `jarvis skill install <source>:<name>` | Install from Hermes, OpenClaw, or GitHub |
| `jarvis skill sync [<source>] [--category C]` | Bulk install + update from sources |
| `jarvis skill sources` | List configured skill sources |
| `jarvis skill update` | Pull latest from configured sources |
| `jarvis skill remove <name>` | Remove an installed skill |
| `jarvis skill search <query>` | Search the skill index |
| `jarvis skill discover [--dry-run]` | Mine traces for recurring tool patterns |
| `jarvis skill show-overlay <name>` | Inspect optimization output for a skill |
| `jarvis optimize skills [--policy dspy\|gepa]` | Optimize skill descriptions + few-shot examples |
| `jarvis bench skills [--condition C]` | Run the PinchBench skills benchmark |
