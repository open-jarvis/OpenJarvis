# Voice cancellation, execution ownership, and durable traces

## Executive conclusion

OpenJarvis should separate three lifetimes: **the conversational turn, permission to publish output, and the external operation**. An accepted interruption should revoke the old turn's output immediately and request cancellation of its computation. The next turn must not wait for an unrelated synchronous worker to finish. A dispatched order or payment operation, however, needs independent supervision until its outcome is known.

This is not equivalent to releasing the existing runtime lock earlier. The current runtime shares an agent and a mutable trace collector. Allowing concurrent use without first isolating their state risks crossed tool results, mixed traces, and stale writes. Nor can Python safely terminate an arbitrary running thread, or a voice framework undo an arbitrary website transaction.

The strongest cross-framework agreement is therefore **logical interruption with separately managed execution**, not universal hard cancellation. Pipecat exposes cancellation policy for function calls; LiveKit separates speech handles from tool execution; Retell explicitly permits endpoint requests to continue after speech interruption. OpenAI and Retell provide response identities that help reject stale output. None of these establishes automatic rollback of external effects.[^1][^2][^3][^4][^5]

The recommended refactor retains OpenJarvis as agent/tool/policy authority and uses its existing generic tools. It does not introduce a merchant-specific checkout tool, replace Pipecat, or lower order-validation requirements. It removes avoidable scheduling dependencies; it does **not** by itself prove a universal checkout latency below 15 seconds.

## Evidence scope and local findings

Sources were examined on 2026-09-09. Public GitHub links below reference the inspected `main` sources and are moving references, not release-pinned implementation contracts. OpenJarvis's inspected checkout was `feat/voice-mode-computer`, HEAD `93a9524`, with existing uncommitted changes. Its lockfile specifies `pipecat-ai==1.7.0`; current upstream examples and signatures must be checked against that installed version before implementation. The MCP cancellation source is explicitly versioned `2025-11-25`, not represented as the latest specification.

Evidence labels used here:

- **Confirmed:** directly visible in local source, official protocol documentation, or official implementation/tests.
- **Recommendation:** an architectural synthesis for OpenJarvis, not a claim that every framework implements it.
- **Unresolved:** unavailable backend implementation details or behavior requiring runtime measurements.

### What the current OpenJarvis source establishes

| Location | Confirmed mechanism | Architectural significance |
| --- | --- | --- |
| [agents/runtime.py](../../src/openjarvis/agents/runtime.py), `NativeAgentRuntime.__init__` and `_run_stream` | One runtime instance owns `_agent`, `_trace_collector`, and `_lock`. Acquisition precedes collector entry; release is scheduled with `worker_lease.when_settled(self._lock.release)`. | Later bindings on that runtime wait for old workers. Call this a shared runtime lock; its deployment-wide scope requires checking instance construction. |
| [agents/_stubs.py](../../src/openjarvis/agents/_stubs.py), `AgentWorkerLease.run_sync` | Synchronous work runs in `asyncio.to_thread`; its task is retained and awaited through `asyncio.shield`. Caller cancellation signals callbacks but does not terminate the thread. | Transport cancellation can finish while the execution lease remains occupied. |
| [server/voice/llm.py](../../src/openjarvis/server/voice/llm.py), `process_frame` and `stream_agent` | Interruption invalidates turn state; forwarding checks current-turn ownership. | Output suppression exists, but is not proof of engine/tool termination. Generator shutdown needs one explicit owner. |
| [agents/orchestrator.py](../../src/openjarvis/agents/orchestrator.py) and [engine/cloud.py](../../src/openjarvis/engine/cloud.py) | The semantic streaming branch depends on `supports_semantic_reasoning_stream`; the inspected cloud implementation recognizes DeepSeek models. Luna follows the synchronous compatibility path. | An async-looking outer stream does not necessarily make the underlying Luna run interruptible. Preserve the requested Luna model and `high` reasoning while fixing execution ownership. |
| [traces/collector.py](../../src/openjarvis/traces/collector.py), `run_stream`, `_subscribe`, and event handlers | Steps and timing fields live on the collector instance. It subscribes to bus events without an observed per-run event filter. Completion recording follows the `try/finally`, rather than recording every terminal path inside it. | Concurrent reuse can mix events; cancellation or generator close can bypass completed-trace recording. |
| Same collector | Its start timestamp occurs after runtime lock acquisition; `total_latency_seconds` sums step durations. | Queue wait is invisible there. Summed nested or overlapping steps are not reliable end-to-end wall latency. |

These observations establish a credible blocking mechanism and a trace blind spot. They do **not** independently establish that all reported 60–80 seconds were lock wait, or that POST network time caused the earlier checkout delays. A log reporting lock **hold** duration is not a measurement of lock **acquisition wait**. No new live voice reproduction, merchant transaction, or runtime benchmark is claimed here.

## 1. Cancellation from WebRTC/VAD to Python execution

### Distinguish four cancellation operations

| Operation | What must happen | What it does not prove |
| --- | --- | --- |
| Acoustic interruption | Stop/flush obsolete assistant playback while leaving microphone and call transport active. | The model stopped generating. |
| Output revocation | Reject old-generation text, audio, UI effects, and answer-derived commits. | An old thread stopped running. |
| Execution cancellation | Signal owned tasks and close/cancel provider streams and cancellable tools. | A remote write was rolled back. |
| Business cancellation | Execute an authorized, supported cancellation or compensation operation. | Every effect is reversible or the operation succeeded. |

This distinction is corroborated by Pipecat's selectable tool cancellation, LiveKit's speech interruption handling, and Retell's documented continuation of interrupted endpoint requests.[^1][^2][^3] Treating a VAD event as all four operations would silently change business semantics.

### Cooperative cancellation is the default Python mechanism

`Task.cancel()` requests delivery of `CancelledError` at an async suspension point. Cleanup belongs in `finally`, and cancellation normally propagates after cleanup. `shield` protects the child, not its cancelled caller. `TaskGroup` waits for children at exit; `wait_for` can exceed its nominal timeout while waiting for cancellation to complete. Consequently, putting an uncooperative worker inside a task group or a timeout does not establish a bounded handoff.[^6]

Running `concurrent.futures` work cannot be cancelled through `Future.cancel()`. AnyIO independently documents the same limitation for threads: abandoning the await leaves the thread running, while `from_thread.check_cancelled()` gives cooperating synchronous code explicit checkpoints.[^7][^8] **Why it matters:** changing `to_thread` wrappers alone cannot eliminate a worker-held lease.

Recommended synchronous checkpoints are before another LLM request, tool dispatch, retry, and expensive local loop iteration. Every network operation also needs bounded I/O. Reuse a scoped async HTTP client and close streaming responses; HTTPX distinguishes connect, pool, write, and read timeouts, with read timeout measuring inactivity between chunks rather than the entire turn deadline.[^9][^10] Connection pooling can reduce overhead, but cannot explain away time spent waiting for old work.

### Framework mechanisms and limits

| Framework | Specific verified mechanism and direct implementation link | Why it matters |
| --- | --- | --- |
| Pipecat | [`LLMService`](https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/services/llm_service.py) checks registered `cancel_on_interruption` policy, cancels function-call tasks, emits `FunctionCallCancelFrame`, and guards settled results. The documented default is cancellation enabled.[^1][^11] | Provides a suitable lifecycle hook, but only for calls actually managed through that mechanism—not automatically every OpenJarvis native executor call. |
| LiveKit Agents | [`SpeechHandle`](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/speech_handle.py) signals an interruption future; `wait_if_not_interrupted` races it against shielded work. An interruption watchdog cancels owned tasks and can mark speech done.[^2] | Speech can settle independently of shielded work. Logical completion still does not establish that a Python thread exited. |
| OpenAI Realtime | The official [WebRTC transport](https://github.com/openai/openai-agents-js/blob/main/packages/agents-realtime/src/openaiRealtimeWebRtc.ts) issues guarded `response.cancel`, then `output_audio_buffer.clear`.[^12][^13] | Provider generation cancellation and clearing buffered playback are distinct operations. |
| Retell | The [custom-LLM WebSocket contract](https://docs.retellai.com/api-references/llm-websocket) increments `response_id` and discards response output associated with an older requested response.[^5] | An explicit stale-output fence; application computation still needs its own cancellation. |
| Vapi | [Server events](https://docs.vapi.ai/server-url/events) expose interruption/output correlation through optional `turnId`. The [web SDK](https://github.com/VapiAI/client-sdk-web/blob/main/vapi.ts) emits speech events; `stop()` destroys the Daily call.[^14][^15] | Use turn interruption/correlation, not call teardown, as the barge-in boundary. SDK speech events are not cancellation acknowledgements from workers. |

Pipecat's current `FrameProcessor` also awaits task cancellation; the inspected process-task cancellation path supplies no explicit timeout. Its queue-reset machinery should not be mistaken for universal hard preemption.[^16]

### OpenAI transport and event edge cases

For Realtime WebRTC/SIP, the server manages audio playback/truncation; for WebSocket audio, the application must track played audio and send `conversation.item.truncate` appropriately. Do not apply the WebSocket recipe blindly to WebRTC. OpenAI's function-call flow delegates execution to the application; audio cancellation is not a cancellation protocol for that external operation.[^4]

There is a documentation inconsistency: the conversations guide refers to `response.cancelled`, but the `response.cancel` event schema specifies **`response.done` with `response.status == "cancelled"`**. The official TypeScript WebRTC tests also wait for `response.done`. Implement against the schema and tests, and tolerate documented error/race cases rather than waiting for an unsupported event name.[^4][^12][^17]

This Realtime behavior is a comparative pattern, not a claim that OpenJarvis's selected Luna Responses API engine is itself running through OpenAI Realtime.

### Where preemptive termination is appropriate

AnyIO offers killable process execution through `to_process.run_sync(..., cancellable=True)`. Python 3.14's process-pool termination APIs terminate the pool's workers, not one arbitrary request in a shared pool. Python also warns that terminating a process can leave locks/queues unusable and does not run normal cleanup.[^7][^18][^19]

**Recommendation:** use process isolation only for unavoidable uncooperative work with a clear isolation boundary, preferably pure computation or safe reads. It is not the first step for HTTP operations that can use async clients. Never kill a process that owns a shared SQLite transaction, shared agent state, or an unresolved external write and then assume clean rollback. There is no safe general-purpose Python thread-kill solution in the examined sources.

## 2. Runtime admission, locks, and leases

### Separate ownership instead of removing synchronization

LiveKit's inspected `AgentActivity` has its own locks, current speech, speech tasks, and background speeches; it also owns a tool executor. Its executor distinguishes activity- and session-scoped tool lifetimes, validates cancellability, and drains noncancellable work by waiting for it.[^20][^21] This supports scoped ownership, not a claim that production voice systems avoid locks altogether.

There is also unavoidable protocol serialization in some providers. OpenAI's `responseCreateSequencer` tracks create/cancel state and response completion; its WebRTC tests explicitly defer a follow-up `response.create` until `response.done` after interruption.[^17][^22] Thus **immediate application admission** and **immediate provider generation** are different guarantees.

The following design is a recommendation synthesized from those mechanisms and Python's cancellation constraints. It is not a verbatim vendor architecture.

| Owner | Scope | Behavior at interruption |
| --- | --- | --- |
| Session controller | Brief state transitions for one voice session | Increment epoch, switch current turn, request playback stop; do not await worker cleanup. |
| Run context | One `run_id`, immutable input/context snapshot, private mutable execution state | Mark interrupted; cancel cancellable children; retain lifecycle under supervisor. |
| Output lease | `(session_id, run_id, epoch)` | Revoke immediately; every text/audio/UI/answer-memory boundary checks authority. |
| Operation lease | A specific conflicting resource, such as one cart or order | Remain held until the external operation settles or enters explicit reconciliation. |
| Cleanup supervisor | Backend process/session lifetime, beyond an individual response coroutine | Retain task references, drain exceptions, enforce cleanup budgets, record late settlement. |
| Trace/operation writer | Durable journal independent of response delivery | Persist admission, cancellation, partial steps, and later outcomes. |

### Recommended interruption sequence

1. At an **accepted** VAD interruption, record the event and revoke the old epoch in a short controller transition. Repeated events are idempotent. Detection of noise/backchannels and the decision to accept interruption remain separate from execution cancellation.
2. Stop obsolete playback and reject queued output carrying the old epoch. Keep WebRTC and microphone capture alive.
3. Signal the old run's cancellation token and owned async tasks. Register cleanup with a supervisor that is not cancelled with the turn; do not await settlement on the new-turn admission path.
4. Admit the next finalized transcript with a fresh run context. Reads and unrelated work may proceed. A write conflicting with an unresolved prior operation waits on that **operation**, not a global conversational lock.
5. The supervisor observes provider cancellation, closes streams, and waits a bounded grace period. A still-running thread is explicitly marked abandoned/quarantined, not falsely marked terminated.
6. Late output is discarded; late tool evidence and settlement telemetry are retained. A stale callback cannot clear the current turn, publish its answer, or release a newer owner's lease.

A supervisor can use a bounded observation wait that returns pending tasks, rather than relying on `wait_for` to enforce termination of uncooperative work.[^6] The supervising scope must retain strong references and have its own shutdown behavior. Async-generator closure must have one owner: cancel/settle an active `anext` before attempting `aclose`, rather than racing two consumers.

Before overlapping runs, audit mutable agent context, collector fields, event-bus correlation, executor state, evidence stores, browser/page ownership, and answer persistence. Separate run-local state while sharing only resources explicitly safe for concurrency, such as configured connection pools. A single shared browser page may need its own operation serialization even after the runtime lock is narrowed.

### Bound the cost of abandonment

Quarantine is not an unlimited background-thread strategy. Set maximum orphan count, per-provider concurrency budgets, cleanup age limits, and reserved capacity for foreground voice turns. If resources are exhausted, return an explicit degraded/busy outcome instead of silently queuing behind minutes of orphan work. Use targeted process recycling only where isolation permits it.

Epoch checks protect OpenJarvis output, but cannot fence an already-sent request at a remote website. An expired local lease is not sufficient permission to retry a write: the old owner might still commit. Strong remote fencing or idempotency requires support at the resource boundary. This limitation is corroborated by MCP's best-effort cancellation semantics and Temporal's treatment of retries/idempotency.[^23][^24]

## 3. Partial tools, writes, and rollback

### Production contracts distinguish speech from business effects

Retell explicitly states that interruption cuts/skips a function's associated speech while the endpoint request continues. Vapi distinguishes synchronous API Request tools from asynchronous Function tools that let conversation proceed without waiting. Neither contract implies transactional cancellation.[^3][^25]

MCP `notifications/cancelled` is best effort: a receiver may be unable to cancel, and late responses may be ignored by the caller. Task-augmented operations have a separate cancellation mechanism in that specification. Ignoring a tool result is therefore not evidence that its effect did not happen.[^23]

### Recommended generic tool policy

Classify effects in trusted executor metadata/policy, not through a model's assertion and not solely by HTTP method. A GET can be unsafe on a poorly designed site; a POST can be read-only. Unknown capabilities should conservatively receive mutation handling.

| Observed operation state | Barge-in behavior | What the next turn can safely assume |
| --- | --- | --- |
| Local/pure computation | Cancel cooperatively; isolate if necessary. | No external write was dispatched. |
| Safe read in flight | Cancel/close if supported; discard stale display output. | Retry only under the read policy. |
| Validated write, not yet dispatched | Stop dispatch and record cancellation. | No write occurred, provided the dispatch boundary is atomic with cancellation authorization. |
| Write dispatched, outcome unknown | Supervise and reconcile; retain operation identity and conflict protection. | It may have committed; do not announce failure or issue an unqualified retry. |
| Write confirmed committed | Persist authoritative receipt independently of interrupted speech. | Order exists even if the customer never heard confirmation. |
| Explicit supported business cancellation | Validate authority and execute the provider's cancellation/compensation operation. | Cancellation is confirmed only by authoritative evidence. |

The race between checking a cancellation token and actually dispatching a write needs an explicit linearization point under short operation-level synchronization. Persist dispatch intent before sending. If cancellation wins, do not send; if dispatch wins, classify the result as potentially committed until proven otherwise.

Use a stable `operation_id` and provider idempotency key for retries of the **same intended operation**, where supported. A timeout after send is `outcome_unknown`, not `failed`. Reconcile through a provider receipt/status lookup before another conflicting mutation. Never infer that two identical orders are duplicates merely because their payloads match; a customer may intentionally order twice.

Temporal's Python guidance independently illustrates the underlying failure model: an activity can succeed before its acknowledgement is lost; retries need idempotency. Its Saga guidance registers compensation before the forward action and recognizes compensation failure.[^24] This is a durability pattern to borrow, not a recommendation to introduce Temporal or a fixed merchant workflow.

Automatic compensation on every VAD interruption would be incorrect. “Wait, tell me the price” need not mean “cancel the order.” Compensation needs a supported API and appropriate business authorization; it is a new operation, not a time reversal. For arbitrary websites without idempotency, status lookup, or cancellation capabilities, exactly-once effects and automatic rollback cannot be guaranteed. Preserve the uncertainty and request reconciliation rather than fabricating certainty.

## 4. Aborted-turn observability and persistence

### Framework telemetry is useful but incomplete

Pipecat's `TurnTrackingObserver` exposes turn end with duration and `was_interrupted`. LiveKit's LLM stream watcher emits `LLMMetrics` including cancellation and TTFT, but the inspected implementation skips metrics when no chunk arrived or the attempt errored. An interrupted-before-first-token turn can therefore disappear from a metrics-only view.[^26][^27]

Retell's documented end-to-end metric excludes silent tool-only turns and server-to-frontend network time; its LLM latency uses the first speakable chunk, not simply any token. Those metrics cannot be compared directly with OpenJarvis's customer-visible checkout completion time.[^28] Vapi's optional turn identifiers can aid correlation, but absence must be handled.[^14]

OpenTelemetry also distinguishes spans from durable records. Ending a parent does not end its children, and ended spans should not be mutated. Batch processors can drop spans when queues fill. Intentional HTTP cancellation should not automatically be classified as an HTTP error.[^29][^30][^31] These are three reasons to maintain an application lifecycle journal alongside exported traces.

### Recommended journal and status model

Create a run record **at admission, before any lock or provider wait**. Append step transitions as they happen, rather than constructing the only record from a final answer. Suggested event envelope:

`event_id, session_id, run_id, epoch, sequence, operation_id?, tool_call_id?, provider_request_id?, parent_step_id?, monotonic_time, wall_time, event_type, status, sanitized_attributes`

Use monotonic timestamps for durations inside one process; wall time is for correlation. Browser `performance.now()` and backend monotonic clocks have different origins: correlate identifiers and estimate clock offset/uncertainty, or measure local legs separately. Do not subtract unrelated clocks as though they were synchronized.

Record at least admission, acquire requested/acquired/released, provider request start/first content/end, tool validation/dispatch/result, accepted interruption, cancellation requested/acknowledged, output revoked, playback acknowledgement, run terminal state, and late worker/operation settlement. Store tool argument/result evidence with redaction and explicit size policies; never log credentials or payment secrets.

Keep status axes separate:

- Dialogue: `completed`, `interrupted`, `failed`, `disconnected`.
- Execution: `running`, `cancel_requested`, `cancelled`, `abandoned`, `settled`.
- Operation: `not_dispatched`, `in_flight`, `committed`, `failed`, `outcome_unknown`, `compensated`.

A valid final combination is **interrupted dialogue + settled execution + committed order**. The UI must not label that order “cancelled.” Conversely, retaining an aborted trace must not promote its incomplete answer into successful learning or answer-derived memory. Keep diagnostic persistence separate from the current completion/persistence acceptance path and success-oriented `TRACE_COMPLETE` consumers.

Late settlement should append an event or linked span, not mutate an already-ended span. Record missing TTFT and unknown usage as null/unknown, not zero. Provider usage absent on interruption must not be invented.

### SQLite and failure durability

SQLite WAL permits readers alongside a writer, but still only one writer at a time. Long transactions and checkpoint behavior matter; `synchronous` mode affects power-loss durability.[^32]

**Recommendation:** one dedicated journal writer with short transactions, run/event identifiers, idempotent inserts, bounded buffering, and write-failure metrics. Do not hold a SQLite transaction across network work. The writer must outlive a cancelled response coroutine and preferably own persistence outside any killable tool process.

Persist critical operation intent before irreversible dispatch; retain acknowledgement/receipt independently of speech completion. Flush incrementally rather than only on shutdown. Recover unfinished runs after restart as interrupted/unknown and reconcile unfinished operations. A durable acknowledgement before dispatch adds local I/O latency, but removes an otherwise unobservable mutation window.

“No lost traces” needs a defined failure boundary. An in-memory queue can lose its tail on process crash; WAL does not save events never committed. Disk failure cannot simultaneously guarantee zero wait and zero loss. For critical writes, fail closed when the operation journal cannot accept durable intent. Document any weaker durability policy for noncritical token-level telemetry rather than calling it lossless.

### Proposed measurements

These are OpenJarvis-specific metric definitions, not claims about standardized GenAI metric names.

| Metric/boundary | Definition | Diagnostic use |
| --- | --- | --- |
| Runtime queue wait | `acquired - acquire_requested` | Separates contention from execution. |
| Application admission delay | `run_admitted - finalized_input_received` | Detects obsolete-worker dependency before provider dispatch. |
| LLM TTFT | First meaningful content/tool delta minus provider request start; classify delta kind. | Separates provider latency from speech readiness. |
| First speakable text | First accepted speakable text minus finalized input. | Does not count empty/reasoning/tool-only chunks as audible progress. |
| First audio generated / played | Separate backend first-audio and browser playback observations. | Exposes TTS, buffering, transport, and playout delay. |
| Barge-in stop latency | Last obsolete audible playback minus accepted interruption, with clock uncertainty. | Validates the actual WebRTC seam. |
| Cancellation acknowledgement | Worker/provider acknowledgement minus cancellation request. | Distinguishes logical interruption from compute shutdown. |
| Orphan age/count | Unsettled abandoned workers and time since abandonment. | Reveals capacity leakage behind apparently fast new turns. |
| Tool phase latency | Validation, pool wait, request, reconciliation, presentation acknowledgement separately. | Identifies whether “slow POST” is actually multiple agent turns. |
| Checkout completion | Input boundary to authoritative result plus required UI/QR acknowledgement; report audio separately. | Measures the requested business outcome, not filler speech. |
| Trace durability lag | Durable commit minus event acceptance; include failed/dropped records. | Detects observability failure under pressure. |

Use span boundaries to derive critical-path wall time; do not sum overlapping child spans. Report p50/p95/p99, counts, interrupted-turn denominator, cold/warm state, model, prompt tokens, LLM round count, and tool count. Keep high-cardinality IDs in traces/logs rather than metric labels.

## Refactor sequence and acceptance criteria

The following is a proposed implementation order, not a completed patch:

1. Add admission and abort journaling plus true lock-wait measurement; reproduce the actual browser/WebRTC case with safe fake tools. This establishes an honest baseline.
2. Isolate run-local execution/collector state and correlate every bus event by run and operation. Prove isolation before permitting overlap.
3. Introduce explicit output ownership and an independent cleanup supervisor; preserve operation-specific serialization and existing validation.
4. Make provider/read paths cooperatively async where feasible; bound unavoidable sync work and orphan capacity. Use framework cancellation hooks only where OpenJarvis calls are actually registered through them.
5. Measure real voice and checkout critical paths, then reduce redundant LLM/tool rounds using generic existing capabilities. Prompt/configuration tuning cannot repair worker ownership by itself.

| Acceptance scenario | Required observable result |
| --- | --- |
| Old read-only worker deliberately blocks for 60 seconds; user interrupts | New run is admitted without waiting for old settlement. Old output never reaches TTS/UI; both runs retain separate records. |
| Cancellation before first LLM chunk | Interrupted run exists, with TTFT null and cancellation timestamps. |
| Old callback completes after two newer turns | It cannot clear/release the new owner's state or overwrite its display/history. |
| Async generator interrupted during `anext` | One owner closes it; no concurrent-close error or leaked task. |
| Tool commits, then response/connection is lost | Operation becomes unknown and is reconciled; no duplicate mutation or false failure claim. |
| Barge-in races write dispatch | Exactly one local dispatch decision wins; journal explains whether the operation was sent. |
| Two independent sessions plus one pending order | No cross-session event contamination; only truly conflicting operations serialize. |
| Repeated/noisy VAD events | Accepted interruptions are idempotent; no runaway run creation, duplicate writes, or call teardown. |
| Orphan pool exhausted | Bounded/degraded admission outcome and visible metrics, not unbounded threads or hidden queueing. |
| Writer failure/process restart | Critical dispatch follows the durability policy; unfinished runs and unknown operations remain discoverable. |
| Real browser/TTS run | Timestamped microphone, interruption, last stale playback, new input, first new audio, and UI acknowledgement demonstrate the transport seam. |
| Fully specified checkout | Measure actual authoritative completion and required QR/display acknowledgement below 15 seconds in declared supported conditions, including p95 and failure cases. An acknowledgement sentence is not checkout completion. |

Suggested engineering budgets for initial testing are application admission below 100 ms and obsolete playback stopping within roughly 200 ms of an accepted interruption. These are **proposed targets, not measured guarantees or vendor SLAs**. Provider quotas, STT endpointing, local GPU contention, remote website delays, and same-resource writes can still constrain completion. A strict all-websites/all-conditions sub-15-second guarantee is not supported by this evidence.

## Self-critique and unresolved boundaries

The following challenges were checked against additional primary sources rather than left as implicit assumptions.

| Challenge | Cross-check and conclusion |
| --- | --- |
| Does cancelling the await stop its thread? | CPython futures and AnyIO independently say no. Cooperative checkpoints or isolation are required.[^7][^8] |
| Does a timeout guarantee bounded cleanup? | Python documents cancellation waits exceeding `wait_for`'s timeout; Pipecat's inspected process-task cancellation has no explicit timeout. Separate admission from cleanup.[^6][^16] |
| Can every provider accept another generation immediately? | OpenAI SDK sequencer and tests require `response.done` before some follow-ups. Guarantee application admission, and measure provider sequencing separately.[^17][^22] |
| Do all frameworks cancel tools on barge-in? | Pipecat policy, LiveKit executor ownership, and Retell endpoint continuation differ. There is no universal default.[^1][^3][^21] |
| Are interrupted metrics complete? | LiveKit skips no-chunk/error-attempt metrics; Pipecat's observer reports interrupted turns but does not itself prove durable storage. Journal admission independently.[^26][^27] |
| Is exported tracing a lossless audit log? | OpenTelemetry documents queue drops; SQLite durability only covers committed events. Separate audit intent from best-effort spans.[^30][^32] |
| Which OpenAI cancellation event is authoritative? | Guide wording conflicts with client-event schema; schema and SDK tests agree on `response.done` with cancelled status.[^4][^12][^17] |
| Can Vapi/Retell scheduler internals be verified? | Official docs and client SDKs expose external contracts, not the hosted backend's lock/worker implementation. No internal preemption claim is made.[^3][^14][^15][^33] |
| Does a generic rollback/exactly-once solution exist for all websites? | MCP best-effort cancellation and Temporal's idempotency/compensation guidance establish why remote capabilities matter. Without them, outcome uncertainty remains.[^23][^24] |
| Is the reported 60–80-second incident conclusively lock starvation? | Local source establishes the mechanism, but the duration attribution still requires admission/lock/provider/playout measurements. No fresh incident reproduction is included. |

Independent corroboration is strongest for Python cancellation limits, separation of speech and tool lifetimes, and the need to distinguish logical cancellation from external effects. Exact framework API behavior is necessarily single-project evidence, sometimes corroborated by that project's code and tests rather than an independent implementation. Retell's metric exclusions and Vapi's hosted event contract are vendor-documented facts, not independently verified internal behavior.

Remaining implementation risks are installed-version differences, arbitrary website capability gaps, false-interruption policy, same-page browser contention, provider cancellation acknowledgement delays, and durability under disk/process failure. These are explicit test/design boundaries, not reasons to release shared state unsafely or erase aborted runs from telemetry.

## Sources

All sources below are primary documentation or official project code. Accessed 2026-09-09; unversioned documentation and `main` links may change. Source-specific mechanisms are cited at the findings above.

[^1]: Pipecat, [Function calling](https://docs.pipecat.ai/pipecat/learn/function-calling). Tool cancellation policy and interrupted handler behavior.
[^2]: LiveKit Agents, [`voice/speech_handle.py`](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/speech_handle.py). Interruption futures, shielded waits, and watchdog.
[^3]: Retell AI, [Custom functions](https://docs.retellai.com/build/single-multi-prompt/custom-function). Endpoint continuation despite interrupted function-associated speech.
[^4]: OpenAI, [Realtime conversations: interruption and truncation](https://developers.openai.com/api/docs/guides/realtime-conversations#interruption-and-truncation). Transport-specific playback handling and external function execution.
[^5]: Retell AI, [LLM WebSocket reference](https://docs.retellai.com/api-references/llm-websocket). Response identities, stale-output handling, and tool-call identifiers.
[^6]: Python, [Coroutines and tasks](https://docs.python.org/3/library/asyncio-task.html). Cooperative cancellation, shielding, structured task ownership, and timeout semantics.
[^7]: Python, [`concurrent.futures`](https://docs.python.org/3/library/concurrent.futures.html). Running-future cancellation limits and Python 3.14 process-pool termination APIs.
[^8]: AnyIO, [Working with threads](https://anyio.readthedocs.io/en/stable/threads.html). Abandonment and cooperative cancellation checks.
[^9]: HTTPX, [Async support](https://www.python-httpx.org/async/). Client reuse and streaming response closure.
[^10]: HTTPX, [Timeouts](https://www.python-httpx.org/advanced/timeouts/). Connect, read, write, and pool boundaries.
[^11]: Pipecat, [`services/llm_service.py`](https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/services/llm_service.py). Function cancellation and settled-result protection.
[^12]: OpenAI, [Realtime client event: `response.cancel`](https://developers.openai.com/api/reference/resources/realtime/client-events#response.cancel). Cancellation completion is `response.done` with cancelled status.
[^13]: OpenAI, [`openaiRealtimeWebRtc.ts`](https://github.com/openai/openai-agents-js/blob/main/packages/agents-realtime/src/openaiRealtimeWebRtc.ts), and [client event: `output_audio_buffer.clear`](https://developers.openai.com/api/reference/resources/realtime/client-events#output_audio_buffer.clear). Generation cancellation and WebRTC/SIP playback clearing.
[^14]: Vapi, [Server events](https://docs.vapi.ai/server-url/events). Turn-correlated output/interruption and playback-related events.
[^15]: Vapi, [`client-sdk-web/vapi.ts`](https://github.com/VapiAI/client-sdk-web/blob/main/vapi.ts). Client speech events and call-destroying `stop()` implementation.
[^16]: Pipecat, [`processors/frame_processor.py`](https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/processors/frame_processor.py). Input/process task cancellation and queue lifecycle.
[^17]: OpenAI, [`openaiRealtimeWebRtc.test.ts`](https://github.com/openai/openai-agents-js/blob/main/packages/agents-realtime/test/openaiRealtimeWebRtc.test.ts). Cancel/clear order and follow-up generation waiting for response completion.
[^18]: AnyIO, [API reference: `to_process.run_sync`](https://anyio.readthedocs.io/en/stable/api.html#anyio.to_process.run_sync). Killable isolated process execution.
[^19]: Python, [`multiprocessing.Process.terminate`](https://docs.python.org/3/library/multiprocessing.html#multiprocessing.Process.terminate). Cleanup, queue/lock, and descendant-process hazards.
[^20]: LiveKit Agents, [`voice/agent_activity.py`](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/agent_activity.py). Activity/speech/tool ownership.
[^21]: LiveKit Agents, [`voice/tool_executor.py`](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/voice/tool_executor.py). Scoped execution, cancellability, duplicate handling, and drain policy.
[^22]: OpenAI, [`responseCreateSequencer.ts`](https://github.com/openai/openai-agents-js/blob/main/packages/agents-realtime/src/responseCreateSequencer.ts). Provider response-create/cancel coordination and waiter generations.
[^23]: Model Context Protocol, [Cancellation, specification 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/cancellation). Best-effort request cancellation and late-response semantics.
[^24]: Temporal, [Python error handling and best practices](https://docs.temporal.io/develop/python/best-practices/error-handling). Retry ambiguity, idempotency, and compensation ordering/failure.
[^25]: Vapi, [API Request vs Function tools](https://docs.vapi.ai/tools/api-request-vs-function). Synchronous request waiting versus asynchronous conversation continuation.
[^26]: Pipecat, [Turn tracking observer](https://docs.pipecat.ai/api-reference/server/utilities/observers/turn-tracking-observer). Interrupted-turn duration/event hooks.
[^27]: LiveKit Agents, [`llm/llm.py`](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/llm/llm.py). LLM metrics, cancellation, stream closure, and no-chunk/error exclusions.
[^28]: Retell AI, [Check actual latency](https://docs.retellai.com/reliability/check-actual-latency). Metric boundaries, exclusions, and distributions.
[^29]: OpenTelemetry, [Trace API: End](https://opentelemetry.io/docs/specs/otel/trace/api/#end). Parent/child lifetime and ended-span semantics.
[^30]: OpenTelemetry, [Trace SDK: Batching processor](https://opentelemetry.io/docs/specs/otel/trace/sdk/#batching-processor). Bounded queues, drops, flush, and shutdown.
[^31]: OpenTelemetry, [HTTP span conventions](https://opentelemetry.io/docs/specs/semconv/http/http-spans/). Intentional cancellation versus error classification.
[^32]: SQLite, [Write-ahead logging](https://www.sqlite.org/wal.html). Writer concurrency, checkpointing, and durability tradeoffs.
[^33]: Retell AI, [`retell-client-js-sdk/src/index.ts`](https://github.com/RetellAI/retell-client-js-sdk/blob/main/src/index.ts). Public client SDK scope; not evidence of hosted worker implementation.
