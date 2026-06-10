# Durable Morning Digest (Temporal)

A drop-in durable replacement for the orchestration in
`src/openjarvis/agents/morning_digest.py`. The agent's tools, persona
prompt, evaluator, and SQLite store are reused as-is — only the
*orchestration* moves into a Temporal workflow.

## What this fixes

| Today (`MorningDigestAgent.run()`) | With this workflow |
| --- | --- |
| One monolithic `run()`. If TTS fails, the previous ~60s of connector calls + LLM generation are wasted and the run reports failure with no audio. | Each step is its own activity. TTS retries on its own retry budget; connectors and LLM aren't re-executed. |
| Evaluator failures are silenced by `try/except: pass`. | Evaluator failure is logged on the activity; the run still completes with the un-evaluated draft. |
| Scheduling lives in `AgentScheduler`, an in-process thread driven by `croniter`. A crash drops scheduled runs and there's no record of missed fires. | Replaced by a Temporal Schedule. Survives worker restarts, visible via `temporal schedule list`, never double-fires. |
| No history of past digest runs beyond what was written to SQLite. | Every run is browsable in the Temporal UI: per-step timing, retries, errors, payloads. |
| Connector flakiness (Gmail OAuth refresh, Slack 429s, Oura 5xx) takes down the whole digest. | Per-step retry policies tuned to each step (`COLLECT_RETRY`, `GENERATE_RETRY`, `TTS_RETRY`, `STORE_RETRY` in `workflow.py`). |

## Layout

```
examples/temporal_morning_digest/
├── activities.py   # 5 activities mirroring the steps in morning_digest.py
├── workflow.py     # MorningDigestWorkflow + per-step RetryPolicy
├── worker.py       # Long-running worker process
├── starter.py      # Trigger one digest run on demand
└── schedule.py     # Register a recurring Temporal Schedule
```

The activities re-use the existing OpenJarvis code:

- `collect_sources` -> `openjarvis.tools.digest_collect.DigestCollectTool`
- `generate_narrative` -> `ToolUsingAgent._generate` + `digest_evaluator.DigestEvaluator`
- `synthesize_audio` -> `openjarvis.tools.text_to_speech.TextToSpeechTool`
- `store_artifact` -> `openjarvis.agents.digest_store.DigestStore`

## Run it

```bash
# 1. Install Temporal CLI + Python SDK
brew install temporal
uv pip install temporalio

# 2. Start a local cluster (separate terminal)
temporal server start-dev

# 3. Start the worker (separate terminal)
uv run python -m examples.temporal_morning_digest.worker

# 4. Trigger one run on demand
uv run python -m examples.temporal_morning_digest.starter

# 5. Or register the daily schedule
uv run python -m examples.temporal_morning_digest.schedule
temporal schedule list
```

Open the Temporal UI at <http://localhost:8233> to inspect runs,
retried activities, and event history.

## Why this is the right fit for OpenJarvis

Morning Digest is the most-used scheduled agent in the project (powers
the `morning-digest-mac`, `morning-digest-linux`, and
`morning-digest-minimal` presets). It is a long-running, multi-step,
fan-out pipeline against ~13 third-party APIs followed by an expensive
LLM call and an external TTS provider. Every one of those steps fails
independently in real usage, which is exactly the problem Temporal is
designed for: durable execution with per-step retry, replay, and
visibility.

The same pattern applies cleanly to `monitor_operative` (continuous
long-horizon monitoring) and `deep_research` (multi-hop research with
citations) — both are good follow-ups once this example is comfortable.
