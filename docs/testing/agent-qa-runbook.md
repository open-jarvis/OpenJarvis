# Agent QA Runbook

Manual testing scenarios for persistent agents in the CLI and desktop app.

## Environment Setup

| Prerequisite | Command / Check |
|---|---|
| Ollama running with model | `ollama list` shows `qwen3:8b` |
| OpenJarvis initialized | `uv run jarvis doctor` all green |
| Rust extension built | `uv run maturin develop -m rust/crates/openjarvis-python/Cargo.toml` |
| Desktop app running | `uv run jarvis serve` + `cd frontend && npm run dev` |
| Slack credentials | `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` set, bot invited to test channel |
| Gmail credentials | OAuth credentials.json downloaded, token generated |
| Twitter credentials | All 5 env vars set (bearer + OAuth 1.0a) |
| Discord credentials | Bot token set, bot invited to test server |
| Telegram credentials | Bot token from @BotFather, test chat ID known |
| Email credentials | SMTP/IMAP host + credentials for test account |

## CLI Agent Scenarios

| # | Scenario | Steps | Expected Result | Pass |
|---|----------|-------|-----------------|------|
| 1 | Template launch | `jarvis agents launch`, pick research_monitor | Agent created, config printed with curated tools | [ ] |
| 2 | Manual run | `jarvis agents run <id>` | Output shows reasoning + tool calls, status -> idle | [ ] |
| 3 | Immediate ask | `jarvis agents ask <id> "summarize recent AI news"` | Synchronous response in terminal | [ ] |
| 4 | Queued instruct | `jarvis agents instruct <id> "focus on diffusion"`, then `jarvis agents run <id>` | Queued -> delivered, response in `jarvis agents messages <id>` | [ ] |
| 5 | Status check | `jarvis agents status` after 3+ runs | total_runs, total_cost, last_run_at populated | [ ] |
| 6 | Pause/resume | `jarvis agents pause <id>`, verify skipped, `jarvis agents resume <id>`, verify fires | Status toggles correctly | [ ] |
| 7 | Daemon scheduling | `jarvis agents daemon` with interval agent (60s) | 3+ ticks fire on schedule, memory accumulates | [ ] |
| 8 | Budget exhaustion | Set max_cost=0.001, run until exceeded | Status becomes budget_exceeded | [ ] |
| 9 | Error recovery | Kill Ollama mid-tick, then `jarvis agents recover <id>` | Error -> recover -> idle with checkpoint | [ ] |
| 10 | Channel binding | `jarvis agents bind <id> --slack #test`, run tick | Agent sends to Slack | [ ] |
| 11 | Multi-agent | Launch 3 agents, different intervals, run daemon | All fire independently | [ ] |
| 12 | Template tools | Create from each template, `jarvis agents info <id>` | All curated default tools listed | [ ] |

## Desktop App Scenarios

| # | Scenario | Steps | Expected Result | Pass |
|---|----------|-------|-----------------|------|
| 1 | Template wizard | New Agent -> pick each template -> complete wizard | Agent appears in grid with correct config | [ ] |
| 2 | Custom agent | New Agent -> Custom -> manual schedule, pick tools, set credentials | Tools + creds saved, agent created | [ ] |
| 3 | Run Now | Click Run Now on agent card | Status dot: green -> blue -> green, stats increment | [ ] |
| 4 | Immediate chat | Interact tab -> type message -> send (immediate mode) | Response appears in chat UI | [ ] |
| 5 | Queued chat | Interact tab -> send (queued mode) -> click Run Now | Message delivered on tick, response appears | [ ] |
| 6 | Task management | Tasks tab -> create task -> run agent | Task status updates, findings populated | [ ] |
| 7 | Memory inspection | Run 3+ ticks -> Memory tab | Summary memory reflects agent's accumulated knowledge | [ ] |
| 8 | Trace inspection | Run tick -> Logs tab | Trace steps visible with tool calls and results | [ ] |
| 9 | Learning | Enable trace-driven learning -> Learning tab -> trigger | Learning log entries appear | [ ] |
| 10 | Error + recovery | Stop Ollama -> run agent -> verify error badge -> click Recover | Error state shown, recovery resets to idle | [ ] |

## Channel-Specific QA Matrix

| Channel | Send Test | Receive Test | Thread/Reply Test | Agent Template | Pass |
|---------|-----------|-------------|-------------------|----------------|------|
| Slack | Post to #test-channel | Socket Mode incoming msg | Reply in thread (thread_ts) | inbox_triager | [ ] |
| Gmail | Send email to test recipient | Poll unread -> handler fires | Reply in thread (threadId) | inbox_triager | [ ] |
| Email (SMTP/IMAP) | Send via SMTP | IMAP poll UNSEEN | In-Reply-To header | inbox_triager | [ ] |
| iMessage (BlueBubbles) | Send to phone number | N/A (send-only) | N/A | research_monitor | [ ] |
| Twitter/X | Post tweet + send DM | Poll mentions | Reply (in_reply_to_tweet_id) | research_monitor | [ ] |
| Discord | Post to #test-channel | Gateway message event | N/A | code_reviewer | [ ] |
| Telegram | Send to test chat | Long-poll update | reply_to_message_id | research_monitor | [ ] |
| WhatsApp (Baileys) | Send to test number | Baileys incoming msg | N/A | inbox_triager | [ ] |

## Stress & Edge Cases

| # | Scenario | How to Test | Pass Criteria | Pass |
|---|----------|-------------|---------------|------|
| 1 | Message flood | Queue 50 messages via CLI, run tick | All 50 delivered, response generated | [ ] |
| 2 | Long-running daemon | Run daemon for 1 hour, 60s interval agent | No memory leak, no stall, ~60 ticks | [ ] |
| 3 | Rapid pause/resume | Script: pause -> resume -> pause -> resume during tick | Clean state, no corruption | [ ] |
| 4 | Credential revocation | Revoke Slack token mid-tick | Agent gets tool error, tick completes, status not corrupted | [ ] |
| 5 | Multi-agent load | 10 agents on daemon, mix of intervals | All fire on schedule, no interference | [ ] |
| 6 | Large response handling | Agent produces 10k+ char response | summary_memory truncated to 2000 chars, full response in messages | [ ] |
| 7 | Checkpoint integrity | Kill process mid-tick, restart, recover | Checkpoint restored, agent resumes cleanly | [ ] |
