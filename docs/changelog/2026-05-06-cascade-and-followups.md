# OpenJarvis — 2026-05-06 changelog & operations log

A consolidated record of the work that brought OpenJarvis from a broken
deploy to a fully operational verbal-conversation system with Claude-CLI
elaboration, multi-provider tier cascade, and an env-gated network gate.
Written as a backup so future-you (or any future agent) can pick up cold.

Service URL: `https://openjarvis-production-92cf.up.railway.app`
Inspiring-cat (Claude-CLI worker): `https://inspiring-cat-production.up.railway.app`

---

## Timeline

| PR | Branch | Title | Merged |
|----|--------|------|--------|
| #20 | `railway/code-change-IngmhE` | Disable auth, remove Dockerfile ENV stomping | 19:45 UTC |
| #21 | `feat/expand-cloud-providers` | Add 9 OpenAI-compatible cloud providers (engine layer) | 19:47 UTC |
| #22 | `feat/wire-providers-end-to-end` | Wire 9 providers into cloud_router + frontend | 19:56 UTC |
| #23 | `fix/seed-selected-model` | Frontend: seed selectedModel from server info | 20:38 UTC |
| #24 | `feat/cascade-tiers-elaboration` | Cascading-tier race + Claude-CLI elaboration | 21:58 UTC |
| #25 | `feat/cascade-tiers-elaboration` (follow-up) | Fix groq/ routing + Cerebras model id | 22:06 UTC |
| #26 | `fix/safety-batch` | Gemini URL leak + race loser cancellation + bare prefixes | 22:33 UTC |
| #27 | `feat/cloud-providers-autounlock` | Auto-unlock Cloud Models tab from backend env | 22:39 UTC |
| #28 | `feat/elaborations-postgres` | Dual-mode elaboration store (in-memory + Postgres) | 22:44 UTC |
| #29 | `feat/basic-auth-gate` | Env-gated HTTP Basic Auth network gate | 22:48 UTC |

Final deployment: `cbb279af-2183-4519-9a28-a4c711268c2d` (SUCCESS).

---

## Starting state (before this session)

- Every frontend request returned 401 — `AuthMiddleware` was registered
  whenever `OPENJARVIS_API_KEY` was set, but the frontend's
  `VITE_OPENJARVIS_API_KEY` was empty (the build-arg dance never wired).
- 7 cloud providers (Groq, DeepSeek, Cerebras, SambaNova, Kimi,
  HuggingFace, GLM) were declared as Dockerfile env vars but had no
  detection code anywhere in `src/`. The `*_ENABLED` flags were
  referenced zero times.
- No parallel-race pattern, no Claude-CLI integration, no TTS code on
  the frontend.

## Ending state (now)

- Service is reachable; auth gated behind `OPENJARVIS_AUTH_ENABLED=true`.
- 13 cloud providers wired through both `cloud_router.py` (streaming)
  and `engine/cloud.py` (non-streaming), with bare and path-style model
  id support in both layers.
- New `model: "auto"` triggers a 3-tier cascade:
  - **T1** Groq / Cerebras / SambaNova, 2s deadline
  - **T2** Claude-CLI / DeepSeek / Gemini, 5s deadline
  - **T3** OpenRouter-large / Kimi / Groq-slow, no deadline
- Claude-CLI runs in parallel; on completion, if the answer is
  materially different from the spoken one (length ratio + difflib
  similarity), the frontend gets a proactive "Sir, may I elaborate?"
  banner via SSE.
- Browser TTS speaks streamed answers on sentence boundaries.
- Cloud Models tab tiles auto-unlock when the backend has the key in env
  — no more pasting placeholder strings.
- Race losers properly cancelled on first-token (saves credits/CPU).
- Gemini API key no longer leaks in error responses (header auth).
- Elaboration queue persists to Postgres when `DATABASE_URL` is set.
- Env-gated HTTP Basic Auth ready to flip on whenever you want.

---

## Architecture (production paths)

### Streaming chat (model="auto")

```
POST /v1/chat/completions  (stream=true)
    │
    ├─► tier_cascade.cascade(messages)
    │       T1 race ─► first token wins ─► stream to client
    │       T2 race (if T1 silent) ─► first token wins ─► stream
    │       T3 race (if T2 silent) ─► first token wins ─► stream
    │
    └─► elaboration_worker.spawn_elaboration() (background, parallel)
            │
            inspiring-cat POST /tasks {type:"claude_pro", payload:{prompt}}
            ─► await GET /tasks/{id} until done | timeout(180s)
            ─► compare(spoken_answer, claude_answer)
            ─► if materially different: store.mark_proposed()
                    ─► broadcast SSE event "proposed" on /v1/elaborations/stream
```

### Frontend SSE channel

```
EventSource('/v1/elaborations/stream')   // opened on app boot
    │
    ├── ready                  → reset reconnect backoff
    ├── proposed               → store.addProposedElaboration → render banner
    ├── accepted_full          → store.resolveElaboration → render answer
    ├── dismissed              → store.removeElaboration
    └── heartbeat (every 15s)  → keepalive
```

### Tier cascade race (per tier)

```
┌─ task[groq] ──┐
├─ task[cereb] ─┤      Producer-to-Queue pattern
└─ task[samba] ─┘      Each tagged with name in queue.

queue.get() ──► first("groq", "Hi")  ◄─── winner
                ↓
                cancel task[cereb], task[samba]
                stream further chunks from groq only
                drain queue, ignore items not from winner
```

---

## Files added (relative to repo root)

### Backend
- `src/openjarvis/server/tier_cascade.py` — race orchestrator + tier definitions
- `src/openjarvis/server/claude_cli_client.py` — inspiring-cat task client
- `src/openjarvis/server/elaboration_store.py` — in-memory + Postgres mirror, SSE pub/sub
- `src/openjarvis/server/elaboration_worker.py` — background poll + diff + push
- `src/openjarvis/server/elaboration_routes.py` — `/v1/elaborations/*` endpoints
- `src/openjarvis/server/providers_routes.py` — `GET /v1/cloud/providers` availability
- `src/openjarvis/server/basic_auth_middleware.py` — env-gated network gate

### Frontend
- `frontend/src/lib/tts.ts` — `window.speechSynthesis` wrapper
- `frontend/src/lib/elaborations.ts` — long-lived SSE subscriber
- `frontend/src/components/ElaborationBanner.tsx` — "may I elaborate?" UI

## Files modified
- `src/openjarvis/server/routes.py` — `_handle_stream` cascade + elaboration kickoff
- `src/openjarvis/server/app.py` — register new routers + middleware + hydration
- `src/openjarvis/server/cloud_router.py` — added GLM, HF, GitHub Models; Gemini header auth; groq/ prefix routing
- `src/openjarvis/engine/cloud.py` — 9 OpenAI-compatible providers; bare-prefix routing for non-streaming
- `frontend/src/components/Chat/InputArea.tsx` — TTS hook on streaming deltas
- `frontend/src/components/Chat/ChatArea.tsx` — render `<ElaborationBanner />`
- `frontend/src/components/CommandPalette.tsx` — 13 providers + auto-unlock + auto-cascade tile
- `frontend/src/lib/store.ts` — `proposedElaborations` state + actions
- `frontend/src/lib/api.ts` — `fetchCloudProviders` helper
- `frontend/src/App.tsx` — mount elaboration SSE; seed selectedModel from server info
- `pyproject.toml` — `psycopg[binary]>=3.1` added to `server` extras
- `railway.json` — pinned `dockerfilePath`
- `Dockerfile` — removed dead ENV stomping (PR #20)
- Removed: `dockerfile` (lowercase, case-collision)

---

## Environment variables

### Required (already set in your Railway service)
- `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`
- `GROQ_API_KEY`, `DEEPSEEK_API_KEY`, `CEREBRAS_API_KEY`,
  `SAMBANOVA_API_KEY`, `V0_API_KEY`, `GITHUB_PAT`
- `Bridge_Zbigmodel_api` *(non-standard env name — the GLM/Zhipu key)*
- `*_ENABLED` flags for each (Cerebras/SambaNova/OpenRouter/etc. set to "true")
- `DATABASE_URL` (auto-provided by Railway Postgres add-on)

### Active feature gates
- `ELABORATION_ENABLED` — default `true`. Set to anything non-truthy to
  disable the proactive "may I elaborate?" path.
- `OPENJARVIS_AUTH_ENABLED` — default unset. Set to `true` to re-enable
  the legacy bearer-token AuthMiddleware (separate from basic auth).

### Cascade tunables (all optional)
- `TIER1_PROVIDERS` (default `groq/llama-3.1-8b-instant,cerebras/llama3.1-8b,sambanova/Meta-Llama-3.3-70B-Instruct`)
- `TIER1_DEADLINE_S` (default `2.0`)
- `TIER2_PROVIDERS` (default `claude-cli,deepseek-chat,gemini-2.5-flash`)
- `TIER2_DEADLINE_S` (default `5.0`)
- `TIER3_PROVIDERS` (default `openrouter/anthropic/claude-sonnet-4,kimi/moonshot-v1-32k,groq/llama-3.3-70b-versatile`)
- `ELABORATION_DIFF_LENGTH_RATIO` (default `1.5`) — claude length must
  exceed this ratio over spoken to count as materially different
- `ELABORATION_DIFF_LEVENSHTEIN` (default `0.6`) — similarity must be
  below this (lower = more different)
- `CLAUDE_CLI_TIMEOUT_S` (default `180`)
- `CLI_WORKER_URL` (default `https://inspiring-cat-production.up.railway.app`)

### Optional auth tokens
- `INSPIRING_CAT_WEBHOOK_SECRET` — preferred Authorization header for
  inspiring-cat /tasks calls (works currently without auth, this is
  forward-compat)
- `CLAUDE_SESSION_TOKEN` — fallback after the webhook secret

### Network gate (set both to enable)
- `OPENJARVIS_BASIC_AUTH_USER`
- `OPENJARVIS_BASIC_AUTH_PASSWORD`
  When both are set, basic auth is required on every request except
  `/`, `/health`, `/assets/*`, `/static/*`, `/favicon`, `/manifest`.

### Unused env vars (set in Railway but no code reads them — safe to leave or remove)
- `LEGION_*` (LEGION_API_SHARED_SECRET, LEGION_BASE_URL, LEGION_ENABLED, LEGION_WEBHOOK_SECRET)
- `N8N_API_KEY`, `N8N_BASE_URL`, `N8N_CONCURRENCY_PRODUCTION_LIMIT`,
  `N8N_DEFAULT_BINARY_DATA_MODE`
- `OAUTH_RELAY_SECRET`, `MEMORY_INGEST_SECRET`, `PRIMARY_BEACON_SECRET`
- `DUAL_ACCOUNT_ENABLED`, `CLAUDE_ACCOUNT_B_*`, `GEMINI_API_KEY_B`,
  `GEMINI_B_ENABLED`, `GEMINI_B_SESSION_TOKEN` (ready for a future
  dual-account / failover orchestration layer)
- `gelsonmascarenhas-Gmail-app-password`, `Accountant-Finance-API-assistant`
- `_LAYER2_TEST`, `_TOKEN_WRITE_TEST`

---

## Verified end-to-end on production

- ✅ `model: "auto"` returns a real streamed answer (~1s for "Hello")
- ✅ Anthropic, OpenRouter, GLM (via Bridge_Zbigmodel_api), DeepSeek
  all return real completions
- ✅ Claude-CLI integration: probed `glm-4-test` upstream, got real GLM
  400 (proves auth + dispatch worked)
- ✅ inspiring-cat: submitted test task `5b17399f-...`, received result
  in 5s
- ✅ /v1/cloud/providers returns correct availability per provider
- ✅ /v1/elaborations/{unknown_id} returns 404 (route registered)
- ✅ Frontend bundle contains all 13 providers + cascade entry
- ✅ Race losers properly cancelled (logs show `cancelled N loser(s)`)
- ❌ Gemini still 403s — user-side key issue (rotated once, now working
  on other providers; Tier 2 falls through to DeepSeek in practice)

---

## Known follow-ups (still TODO)

1. **HuggingFace** — provider tile shows in UI but `/v1/cloud/providers`
   reports unavailable. Set `HF_API_KEY` in Railway when you want it
   active.

2. **KIMI_API_KEY** — listed in your Railway env but `/v1/cloud/providers`
   reports it as not set. Either the value is empty or the env var name
   differs. Worth a manual check in the Railway dashboard.

3. **Dual-account / latency-aware fallback** — env vars are present
   (`GEMINI_API_KEY_B`, `CLAUDE_ACCOUNT_B_*`, `DUAL_ACCOUNT_ENABLED`)
   but no code wires them. Tier 3 uses `GEMINI_API_KEY_B` via the
   `gemini-b/` synthetic prefix in the cascade design but the resolver
   for that prefix isn't implemented yet — it currently routes through
   cloud_router which doesn't know about it. Track for a future PR if
   you want quota balancing.

4. **Cerebras `llama-3.3-70b`** original default returned 404. Switched
   default to `llama3.1-8b`. Update if Cerebras renames or you want a
   bigger model.

5. **Elaboration prompt UX** — current trigger is "Sir, regarding your
   earlier question — '[60-char excerpt]' — may I elaborate?" Not
   personalised. Could be tied to user identity / conversation context
   later.

6. **Web Speech API voice quality** — varies wildly by browser/OS. Mac
   Chrome and Edge both have decent local voices; Linux/Windows can be
   robotic. Server-side TTS (Cartesia/Kokoro/OpenAI TTS) is a follow-up
   if you want consistent quality.

---

## How to operate

### Daily verbal use

1. Open https://openjarvis-production-92cf.up.railway.app/
2. Hard reload (Ctrl+Shift+R) once after a deploy to pick up new JS bundle
3. Cmd-K → Cloud Models tab → pick **OpenJarvis (auto-cascade)** → `auto` model
4. Type or speak (mic button) → fast answer streams + speaks
5. Wait — for complex questions, the elaboration banner appears 5–60s
   later. Click "Yes, please" to hear/read Claude's deeper take.

### Enable the basic-auth gate

1. Railway → OpenJarvis service → Variables tab
2. Add `OPENJARVIS_BASIC_AUTH_USER=<your username>`
3. Add `OPENJARVIS_BASIC_AUTH_PASSWORD=<long random>`
4. Redeploy
5. First page load: browser prompts; enter creds; cached for the session
6. To disable: delete either var, redeploy

### Tune the cascade

Set the `TIER{1,2,3}_PROVIDERS` env vars (comma-separated) and
`TIER{1,2}_DEADLINE_S` floats in Railway. No code change needed.
Restart picks up new values.

---

## Memories saved for future sessions

In `~/.claude/projects/C--Users-Gelson/memory/`:
- `openjarvis_streaming_required.md` — voice depends on streaming
- `openjarvis_pending_followups.md` — security gate, HF key,
  auto-unlock, deferred orchestration ideas
- `openjarvis_glm_key_envname.md` — GLM key lives under
  `Bridge_Zbigmodel_api`
- `openjarvis_gemini_key_url_leak.md` — closed by PR #26 but kept for
  reference / "rotate the leaked key" reminder

---

*Generated 2026-05-06.*
