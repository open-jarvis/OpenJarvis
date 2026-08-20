---
title: Skills Workflow
description: End-to-end tutorial — install skills, use them with an agent, discover patterns from traces, and optimize with DSPy
---

# Skills Workflow Tutorial

This tutorial walks through the complete skills lifecycle: installing skills from public sources, using them with a local agent, discovering patterns from trace history, and optimizing skill descriptions with DSPy. By the end you will have a working skills setup that improves over time.

!!! note "Before you begin"
    This tutorial assumes OpenJarvis is installed with Ollama running and a model available (e.g., `qwen3.5:9b`). If you have not completed setup yet, start with the [Quick Start guide](../getting-started/quickstart.md).

## Step 1: Install Skills from Hermes Agent

OpenJarvis can import skills from the [Hermes Agent](https://github.com/NousResearch/hermes-agent) skill library maintained by NousResearch. Let's install a few useful ones.

```bash
# Install individual skills
jarvis skill install hermes:arxiv
jarvis skill install hermes:github-pr-workflow

# Or bulk install an entire category
jarvis skill sync hermes --category research
```

The first install clones the Hermes repo to `~/.openjarvis/skill-cache/hermes/` (one-time, ~5s). Subsequent installs reuse the cache.

Verify what's installed:

```bash
jarvis skill list
```

You should see a table with each skill's name, description, version, and tags.

## Step 2: Inspect an Installed Skill

Let's look at what the `arxiv` skill contains:

```bash
jarvis skill info arxiv
```

This shows the skill's metadata — author, description, tags, capabilities, whether it has structured steps or markdown instructions, and its invocation flags.

You can also inspect the raw SKILL.md:

```bash
cat ~/.openjarvis/skills/hermes/arxiv/SKILL.md | head -40
```

The `.source` file records provenance:

```bash
cat ~/.openjarvis/skills/hermes/arxiv/.source
```

This shows the source (`hermes:arxiv`), the git commit it was imported from, which tool names were translated (e.g., `Edit→file_edit`), and the install timestamp.

## Step 3: Use Skills with an Agent

Now let's ask the agent a question that should trigger skill usage:

```bash
jarvis ask "Use the code-explainer skill to explain this Python code: for i in range(5): print(i*2)" \
  --engine ollama --model qwen3.5:9b
```

The agent will:
1. See the skill catalog in its system prompt
2. Decide to invoke `skill_code-explainer`
3. Receive the markdown instructions from the skill
4. Follow the 5-step pattern to explain the code

Try a pipeline skill too:

```bash
jarvis ask "Use the math-solver skill to compute 17 * 23" \
  --engine ollama --model qwen3.5:9b
```

This time the agent invokes `skill_math-solver`, which executes a deterministic pipeline (calling the `calculator` tool internally) and returns the computed result directly.

## Step 4: Create Your Own Skill

Create a new skill directory:

```bash
mkdir -p ~/.openjarvis/skills/my-reviewer
```

Write a SKILL.md:

```bash
cat > ~/.openjarvis/skills/my-reviewer/SKILL.md << 'EOF'
---
name: my-reviewer
description: Review code changes with a security-first approach
license: MIT
metadata:
  openjarvis:
    version: "0.1.0"
    author: me
    tags: [coding, review, security]
---

When asked to review code, follow this approach:

1. **Security scan first** — check for injection vulnerabilities, hardcoded secrets, unsafe deserialization
2. **Correctness** — verify logic, edge cases, error handling
3. **Style** — naming, structure, consistency with surrounding code
4. **Summary** — one paragraph with the verdict: approve, request changes, or block

Always start with security. If you find a security issue, flag it as BLOCKING regardless of other concerns.
EOF
```

Verify it's discovered:

```bash
jarvis skill list
```

You should see `my-reviewer` in the table. Try it:

```bash
jarvis ask "Use the my-reviewer skill to review this function: def login(user, pwd): return db.query(f'SELECT * FROM users WHERE name={user} AND pass={pwd}')" \
  --engine ollama --model qwen3.5:9b
```

The agent should follow the security-first approach and flag the SQL injection vulnerability.

## Step 5: Generate Traces

For the learning loop to work, we need traces. Run several queries that use skills:

```bash
# Generate a few traces
jarvis ask "Use math-solver to compute 100 / 7"
jarvis ask "Use code-explainer to explain: lambda x: x**2"
jarvis ask "Use my-reviewer to review: def add(a,b): return a+b"
jarvis ask "Use math-solver to compute 2**10"
jarvis ask "Use code-explainer to explain: [x for x in range(10) if x % 2 == 0]"
```

Each query produces a trace in `~/.openjarvis/traces.db` with skill metadata tags (`skill`, `skill_source`, `skill_kind`).

## Step 6: Discover Patterns from Traces

Mine the trace store for recurring tool sequences:

```bash
# Preview without writing
jarvis skill discover --dry-run --min-frequency 2

# Write discovered patterns as skill manifests
jarvis skill discover --min-frequency 2
```

Discovered skills land in `~/.openjarvis/skills/discovered/` and automatically appear in `jarvis skill list` on the next session.

## Step 7: Optimize Skills with DSPy

Once you have enough traces (at least 3-5 per skill), run the optimizer:

```bash
# Preview what would be optimized
jarvis optimize skills --dry-run

# Run DSPy optimization
jarvis optimize skills --policy dspy --min-traces 3
```

This produces overlay files at `~/.openjarvis/learning/skills/<skill-name>/optimized.toml` with improved descriptions and few-shot examples extracted from your best traces.

Inspect what was produced:

```bash
jarvis skill show-overlay math-solver
jarvis skill show-overlay code-explainer
```

The next time you run a query, the agent sees the optimized descriptions and few-shot examples in its system prompt.

## Step 8: Benchmark the Impact

Run a quick benchmark to see if skills + optimization actually help:

```bash
# Smoke test: 4 conditions × 1 seed × 5 tasks
jarvis bench skills --max-samples 5 --seeds 42
```

This runs the PinchBench benchmark in four conditions (no skills, skills on, DSPy-optimized, GEPA-optimized) and produces a markdown report at `docs/superpowers/results/`.

## Step 9: Configure Auto-Import and Auto-Optimization

For a hands-off experience, add this to `~/.openjarvis/config.toml`:

```toml
[skills]
enabled = true
auto_sync = true

[[skills.sources]]
source = "hermes"
filter = { category = ["research", "coding"] }
auto_update = true

[learning.skills]
auto_optimize = true
optimizer = "dspy"
min_traces_per_skill = 20
```

Now skills are automatically synced from Hermes on session start, and the optimizer runs after each learning cycle when enough traces accumulate.

## What You Learned

| Concept | What you did |
|---------|-------------|
| **Installing skills** | `jarvis skill install hermes:arxiv` — imported from public sources |
| **Using skills** | `jarvis ask "Use the code-explainer skill..."` — agent invokes skills as tools |
| **Creating skills** | Wrote a `SKILL.md` with YAML frontmatter and markdown instructions |
| **Generating traces** | Ran skill-using queries to populate the trace store |
| **Discovering patterns** | `jarvis skill discover` — mined traces for recurring tool sequences |
| **Optimizing skills** | `jarvis optimize skills --policy dspy` — improved descriptions + few-shot examples |
| **Benchmarking** | `jarvis bench skills` — measured the impact across 4 conditions |
| **Auto configuration** | Added `[skills]` and `[learning.skills]` config sections |

## Next Steps

- Browse the [full skills user guide](../user-guide/skills.md) for all CLI commands and configuration options
- Read the [skills architecture](../architecture/skills.md) for the technical deep-dive
- Explore the [Hermes Agent skill library](https://github.com/NousResearch/hermes-agent/tree/main/skills) for more skills to install
- Try [OpenClaw skills](https://github.com/openclaw/skills) for community-contributed skills
