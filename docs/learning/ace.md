# ACE optimizer (Agentic Context Engineering)

OpenJarvis supports [ACE](https://github.com/ace-agent/ace) as a third
optimizer alongside DSPy and GEPA. Where DSPy bootstraps few-shot
examples and GEPA evolves prompts via reflective mutation, **ACE
evolves a textual *playbook*** — annotated natural-language strategies
the agent reads at inference time. The playbook is updated by a
Generator / Reflector / Curator triad of LLM calls.

## When to pick ACE

| Task shape | DSPy | GEPA | ACE |
|---|---|---|---|
| Single-turn QA with crisp metric | strong | strong | weaker |
| Long-running agent that should accumulate guidance | weak | medium | strong |
| Open-domain where strategies matter more than templates | weak | medium | strong |
| When you want to *read* what the optimizer learned | medium | medium | strong |

ACE's headline artifact is `final_playbook.txt` — a human-readable
file like:

```
## STRATEGIES & INSIGHTS
[str-00001] helpful=5 harmful=0 :: When the user asks for unit
                                   conversion, prefer the exact
                                   rational form before rounding.
[str-00002] helpful=3 harmful=1 :: Cite a primary source before
                                   stating a date claim.
```

If reading those strategies feels like the form of "what learning
should produce" for your task, ACE is the right choice.

## Setup

ACE is **not on PyPI** as of OpenJarvis v1.0.1, and the upstream
repository is structured as a research codebase (multiple top-level
directories) rather than a Python package. There's no `learning-ace`
extra for that reason. Install ACE manually instead:

```bash
# 1. Clone ACE somewhere outside your OpenJarvis checkout
git clone https://github.com/ace-agent/ace.git ~/code/ace
cd ~/code/ace
curl -LsSf https://astral.sh/uv/install.sh | sh   # if you don't have uv
uv sync

# 2. Make ACE's src/ importable from your OpenJarvis venv
echo "$HOME/code/ace/src" > \
  "$(python -c 'import site; print(site.getsitepackages()[0])')/ace.pth"

# 3. Set the API key for whichever provider ACE will call
cp ~/code/ace/.env.example ~/code/ace/.env
# Edit ~/code/ace/.env to set API_KEY for your chosen provider.

# 4. Verify the import resolves from OpenJarvis's venv
python -c "from openjarvis.learning.agents.ace_optimizer import HAS_ACE; print(HAS_ACE)"
# True
```

If `HAS_ACE` prints `False`, the `.pth` file isn't being picked up —
verify the path matches `site.getsitepackages()[0]` for the same
Python interpreter you're using to run OpenJarvis.

## Configuration

ACE is configured under `[learning.agent.ace]` in your OpenJarvis
config TOML:

```toml
[learning.agent]
policy = "ace"

[learning.agent.ace]
# ACE's three roles. Empty = inherit from the intelligence primitive's
# default cloud model.
generator_model = "claude-opus-4-7"
reflector_model = "claude-opus-4-7"
curator_model = "claude-sonnet-4-6"

api_provider = "openai"     # sambanova | together | openai | commonstack

num_epochs = 1
max_num_rounds = 3
playbook_token_budget = 80000
max_tokens = 4096

task_name = "openjarvis"
save_dir = ""               # default: ~/.openjarvis/learning/ace/<task>/

min_traces = 20
```

## Running

Once configured, the same orchestrator that runs DSPy / GEPA also runs
ACE — pick it via the `policy` field above. To force a one-shot run:

```bash
jarvis optimize agent --policy ace
```

ACE writes intermediate state and the final playbook to `save_dir`.
The OpenJarvis runtime will pick up the playbook on next agent start
(via the same sidecar overlay mechanism the Skills System uses).

## Trace adapter behavior

OpenJarvis traces are adapted into ACE's `train_samples` /
`val_samples` / `test_samples` format via a 70 / 15 / 15 split
(order-preserving for reproducibility). Each trace becomes a
`{question: trace.query, ground_truth_answer: trace.result}` sample.
Traces with empty `query` or `result` are dropped before splitting.

The `DataProcessor` ACE expects is built from `_TraceDataProcessor`
in `src/openjarvis/learning/agents/ace_optimizer.py` — it does a
case-insensitive substring match for `answer_is_correct` and averages
that for aggregate accuracy. If you're optimizing for a domain where
substring matching is the wrong correctness signal (math problems,
code, structured outputs), subclass `_TraceDataProcessor` and pass it
through your own callsite to `ACEAgentOptimizer.optimize()`.

## Limitations in v1.0.1

- **No automatic install.** Document above is the only path.
- **The trace adapter uses substring correctness.** Override for
  domain-specific scoring.
- **Single provider per run.** ACE assigns the same `api_provider` to
  all three roles. To mix providers, run ACE outside OpenJarvis and
  hand-deliver the resulting playbook into `save_dir`.

These will get revisited once ACE publishes a PyPI package or stable
provider interface — track
[ace-agent/ace#issues](https://github.com/ace-agent/ace/issues) for
upstream changes that would let us tighten the wrapper.
