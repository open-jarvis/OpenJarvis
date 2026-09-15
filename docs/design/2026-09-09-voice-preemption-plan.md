# Voice preemption implementation plan

**Goal:** Interrupted native Orchestrator turns must not monopolize voice admission; their diagnostic traces and already-started tool evidence must survive.

**Architecture:** Retain serialization for unaudited agent types. Permit the audited Orchestrator to release conversational ownership while a cancelled worker settles, with independent collectors and cooperative checkpoints. Keep a conservative runtime-wide tool lease across overlapping generations until shared browser/evidence resources have settled; conflicting tools return a pending result rather than blocking the new conversation.

**Spec:** [Research and acceptance boundaries](2026-09-09-voice-cancellation-research.md).

**Execution:** Inline TDD using code-work and test-driven-development; one integration owner. Existing dirty checkout is explicitly preserved. No commits, restart, real orders, new merchant-specific tools, model/effort changes, or dependency upgrades.

## 1. Durable interrupted traces

Files: `core/events.py`, `traces/collector.py`, `traces/store.py`, `tests/traces/test_collector.py`, `tests/traces/test_store.py`.

- [ ] Change cancellation/abandonment tests to require one interrupted trace and no success-oriented `TRACE_COMPLETE` event.
- [ ] Add concurrency tests requiring independent run IDs and tool/inference steps. Add a journal test proving admission is readable before completion.
- [ ] Run `timeout 60s .venv/bin/python -m pytest tests/traces/test_collector.py -q` and observe the intended failures.
- [ ] Add context-local event run identity, invocation-local collectors, an append-only run-event journal, and short synchronized SQLite writes. Preserve `save()` duplicate-ID behavior. Record terminal traces in cleanup and keep late worker events journaled until settlement.
- [ ] Repeat collector/store tests separately. Completed traces retain existing event contracts; aborted traces never become training-success events.

## 2. Safe conversational preemption

Files: `agents/runtime.py`, `agents/_stubs.py`, `agents/orchestrator.py`, `tools/_stubs.py`, `tests/agents/test_agent_runtime.py`.

- [ ] Update only the audited Orchestrator's old serialization tests: after cancelling an in-flight model request, a second turn must complete before the first worker is released. Unaudited agents stay serialized.
- [ ] Add tests proving no post-cancel model/tool dispatch, no stale answer persistence, bounded abandoned workers, and a pending tool result while an older tool still owns shared resources.
- [ ] Run focused runtime tests red before production changes.
- [ ] Add cancellation checkpoints and a nonblocking shared-tool ownership guard propagated through context variables. Keep running tool calls attached to their original lease; do not pretend they were rolled back.
- [ ] Narrow runtime ownership release only for explicitly audited agent classes; retain bounded abandoned leases until actual settlement. Capture admission/queue timing in the run journal.
- [ ] Run runtime tests green; retain model pinning, capabilities, confirmation, mutation deduplication, and completed persistence behavior.

## 3. Voice and presentation cancellation boundary

Files: `server/voice/llm.py`, `kiosk/presentation.py`, adjacent Voice/presentation tests.

- [ ] Add an iterator-close regression and a late publication regression under a cancelled lease.
- [ ] Ensure one owner settles the pending iterator step and explicitly closes inner streams; no WebRTC teardown or post-cancel display publication.
- [ ] Run each focused test file independently with hard timeouts. If Pipecat import contention prevents execution, report it rather than changing unrelated code.

## 4. Integration acceptance

- [ ] Run touched trace, runtime, executor, and Voice tests sequentially, then affected Orchestrator/HTTP/presentation tests.
- [ ] Run touched-file Ruff and `git diff --check`; inspect the diff against the dirty baseline.
- [ ] Document measured fake-worker handoff and remaining real-browser/checkout acceptance gaps. Do not claim a production `<15s` SLA from unit tests.

## Explicit boundaries

The conservative shared-tool lease does not promise concurrent writes to arbitrary websites or per-resource parallel browser control. A dispatched HTTP operation retains the existing mutation claim and late evidence; no automatic business rollback is introduced. The journal records accepted lifecycle events incrementally, but this slice does not provide remote exactly-once semantics, disk-failure recovery orchestration, or a new UI analytics dashboard. Those require capabilities beyond cancelling a conversational turn.
