---
title: Skills Architecture
description: Technical deep-dive into the skills system design, components, and integration patterns
---

# Skills Architecture

Skills are a **cross-cutting orchestration layer** that sits across the five existing primitives (Intelligence, Engine, Agents, Memory/Tools, Learning). They connect tools, agents, memory, and learning into reusable workflows without replacing or subsumming any primitive.

## System Design

```
                    ┌──────────────────────┐
                    │   SystemBuilder      │
                    │   .build()           │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │   SkillManager       │
                    │   • discover()       │
                    │   • get_skill_tools()│
                    │   • get_catalog_xml()│
                    └──────────┬───────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
    ┌─────────▼──────┐ ┌──────▼──────┐ ┌───────▼───────┐
    │  SkillTool     │ │  Catalog    │ │  Overlay      │
    │  (BaseTool)    │ │  XML        │ │  Loader       │
    │  → agent tools │ │  → sys.     │ │  → optimized  │
    │    list        │ │    prompt   │ │    desc +     │
    │                │ │             │ │    few-shot   │
    └────────────────┘ └─────────────┘ └───────────────┘
```

## Key Components

### SkillManifest (`skills/types.py`)

The canonical data structure for a loaded skill:

```python
@dataclass(slots=True)
class SkillManifest:
    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    steps: List[SkillStep] = field(default_factory=list)
    required_capabilities: List[str] = field(default_factory=list)
    signature: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    depends: List[str] = field(default_factory=list)
    user_invocable: bool = True
    disable_model_invocation: bool = False
    markdown_content: str = ""
```

### SkillManager (`skills/manager.py`)

The central coordinator. Created by `SystemBuilder.build()` during system composition.

**Lifecycle:**
1. `discover(paths)` — scans skill directories in precedence order, loads manifests, validates the dependency graph, applies optimization overlays
2. `get_skill_tools()` — wraps each discovered skill as a `SkillTool(BaseTool)`, wires sub-skill resolver callbacks
3. `get_catalog_xml()` — generates the lightweight `<available_skills>` XML for system prompt injection
4. `get_few_shot_examples()` — returns formatted few-shot strings from optimization overlays

### SkillTool (`skills/tool_adapter.py`)

Adapter that makes any skill look like a regular `BaseTool` to agents:

- `spec` property derives `ToolSpec` from the manifest — auto-extracts input parameters from step argument templates
- `execute(**params)` runs the pipeline (if steps exist), returns markdown content (if SKILL.md exists), or both
- `_build_result_metadata()` tags every invocation with `skill`, `skill_source`, `skill_kind` for downstream trace analysis

### SkillParser (`skills/parser.py`)

Two-pass parser for agentskills.io-compatible SKILL.md frontmatter:

1. **Strict pass** — validates required fields (`name`, `description`), length limits, kebab-case naming rules
2. **Tolerant pass** — maps non-spec vendor fields to canonical locations via `FIELD_MAPPING` table. Unmapped fields are logged and preserved in `metadata.openjarvis.original_frontmatter`

The mapping table is data, not code paths. Adding support for new vendor fields means adding entries — no logic changes.

### SkillExecutor (`skills/executor.py`)

Sequential pipeline executor:

- Steps with `tool_name` → delegate to `ToolExecutor.execute()`
- Steps with `skill_name` → delegate to a resolver callback (set by SkillManager)
- Template rendering: `{placeholder}` syntax resolved from a shared context dict
- `output_key` stores each step's result for downstream steps
- Publishes `SKILL_EXECUTE_START` / `SKILL_EXECUTE_END` events on the EventBus

### Source Resolvers (`skills/sources/`)

One resolver per import source, all implementing `SourceResolver` ABC:

| Resolver | Repo layout | Special handling |
|----------|-------------|------------------|
| `HermesResolver` | `skills/<category>/<skill>/` | Skips `DESCRIPTION.md`, reads Hermes vendor metadata |
| `OpenClawResolver` | `skills/<owner>/<skill>/` | Reads `_meta.json` sidecars |
| `GitHubResolver` | Recursive walk for `SKILL.md` | Generic — accepts any repo URL |

### SkillImporter (`skills/importer.py`)

Takes a `ResolvedSkill` from a source resolver and installs it on disk:

1. Parse source SKILL.md through `SkillParser`
2. Translate tool references (`Bash` → `shell_exec`, `Read` → `file_read`, etc.)
3. Compatibility check (platform, missing tools)
4. Copy SKILL.md + references/assets/templates (scripts gated by `--with-scripts`)
5. Write `.source` provenance file with commit SHA, translated tools, timestamps

### SkillOverlay (`skills/overlay.py`)

Sidecar storage for optimization output at `~/.openjarvis/learning/skills/<name>/optimized.toml`:

```toml
[optimized]
skill_name = "research-and-summarize"
optimizer = "dspy"
optimized_at = "2026-04-08T14:30:00Z"
trace_count = 47
description = "An optimized description"

[[optimized.few_shot]]
input = "transformer attention mechanisms"
output = "## Recent Advances..."
```

The overlay is the **contract** between the optimizer and the SkillManager. Both sides agree on the schema; either can be swapped independently.

### SkillOptimizer (`learning/agents/skill_optimizer.py`)

Per-skill wrapper around DSPy/GEPA:

1. Buckets traces by `metadata.skill` (from the C1 trace tagging)
2. Skips skills below `min_traces_per_skill` threshold
3. Calls `_run_dspy()` or `_run_gepa()` per qualifying skill
4. Writes overlay TOML files

## Integration Points

### SystemBuilder Wiring

`SystemBuilder.build()` handles skill integration:

```python
# 1. Create SkillManager
skill_manager = SkillManager(bus, capability_policy=...)

# 2. Discover skills from disk
skill_manager.discover(paths=[workspace_skills, user_skills])

# 3. Wrap as tools and merge into tool list
skill_tools = skill_manager.get_skill_tools(tool_executor=...)
tool_list.extend(skill_tools)

# 4. Capture few-shot examples for agents
system._skill_few_shot_examples = skill_manager.get_few_shot_examples()
```

### Trace Metadata Flow

When an agent invokes a `SkillTool`:

```
SkillTool.execute()
  → ToolResult(metadata={"skill": name, "skill_source": src, "skill_kind": kind})
    → ToolExecutor._json_safe_metadata() filters non-serializable values
      → TOOL_CALL_END event with metadata
        → TraceCollector._on_tool_end() → TraceStep(metadata=...)
          → TraceStore saves to SQLite (metadata as JSON)
            → SkillOptimizer._bucket_traces_by_skill() reads metadata.skill
```

### Agent Few-Shot Injection

Optimized few-shot examples flow through:

```
SkillManager.get_few_shot_examples()
  → system._skill_few_shot_examples (stashed on JarvisSystem)
    → _run_agent() → agent_kwargs["skill_few_shot_examples"]
      → ToolUsingAgent._skill_few_shot_examples
        → native_react.run() → REACT_SYSTEM_PROMPT.format(skill_examples=...)
```

## Dependency Graph

Skills can compose other skills. At discovery time, SkillManager validates:

1. **Cycle detection** — Kahn's algorithm for topological sort
2. **Max depth enforcement** — configurable (default 5)
3. **Capability union** — parent must declare all transitive child capabilities

## File Layout

```
src/openjarvis/skills/
├── __init__.py           # Public exports
├── types.py              # SkillManifest, SkillStep
├── manager.py            # SkillManager
├── executor.py           # SkillExecutor + sub-skill delegation
├── loader.py             # TOML + Markdown + directory loading
├── tool_adapter.py       # SkillTool(BaseTool) wrapper
├── parser.py             # Strict + tolerant agentskills.io parser
├── tool_translator.py    # External tool name translation
├── importer.py           # Install from resolved sources
├── overlay.py            # Optimization sidecar storage
├── dependency.py         # Graph validation
├── security.py           # Trust tiers, capability validation
├── index.py              # Git-backed skill index
└── sources/
    ├── base.py            # SourceResolver ABC
    ├── hermes.py          # HermesResolver
    ├── openclaw.py        # OpenClawResolver
    └── github.py          # GitHubResolver
```
