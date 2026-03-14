# Desktop App UX Improvements — Design Spec

**Date:** 2026-03-14
**Scope:** Frontend (React) + minor backend (telemetry)
**Affects:** SystemPanel, Sidebar, InputArea, StreamingDots, new LogsPage, store, api, types

---

## 1. System Panel — Remove Redundancy, Add Device Temps

**Problem:** The right-column system panel has a redundant "Server-reported" section that duplicates Cost Comparison data. The "Cool" thermal label is confusing without context.

**Change:**
- Remove the "Server-reported" / per-provider savings section entirely from SystemPanel.
- Rename the "ENERGY" section to "DEVICE".
- Replace the "Cool/Warm/Hot" label with actual CPU and GPU temperatures (e.g. "CPU: 62°C", "GPU: 71°C").
- Keep Power (W) and Energy (kJ) in the same section.
- Display temp rows only when values are non-null (graceful degradation).

**Data flow — per platform:**
- **NVIDIA GPUs:** Already collected via pynvml in `NvidiaEnergyMonitor` (`mean_temperature_c`, `peak_temperature_c` on `EnergySample`). Just needs to be exposed through the API endpoint.
- **macOS (Apple Silicon):** Read CPU die temperature via IOKit SMC keys through the Rust extension (PyO3 bindings already exist in `rust/crates/openjarvis-python/`). Does not require root. Return `null` if unavailable.
- **Linux (no GPU):** Read from `/sys/class/thermal/thermal_zone*/temp`. Return `null` if path doesn't exist.
- **Windows:** Return `null` for v1 (future: WMI queries).
- Backend: extend the `/v1/telemetry/energy` endpoint in `api_routes.py` to include `cpu_temp_c` and `gpu_temp_c` fields from the energy sample.
- Frontend: `SystemPanel.tsx` already polls every 3s. Refactor to use `getBase()` from `api.ts` (fixing existing inconsistency) and add a `fetchDeviceInfo()` function in `api.ts`.

**Files:**
- `frontend/src/components/Chat/SystemPanel.tsx` — remove server-reported section, rename ENERGY to DEVICE, add temp rows, remove Cool/Warm/Hot logic, use `getBase()`
- `frontend/src/lib/api.ts` — add `fetchDeviceInfo()` function
- `src/openjarvis/telemetry/` — add CPU/GPU temp collection for macOS/Linux
- `src/openjarvis/server/api_routes.py` — expose temp data in `/v1/telemetry/energy` response

---

## 2. Theme Toggle — Sidebar Header

**Problem:** Theme switching is buried in Settings > Appearance. Needs one-click access.

**Change:**
- Add a sun/moon/monitor icon button in the sidebar header, between the collapse button and the new-chat button.
- Three-state cycle matching the Settings page: light → dark → system → light.
- Uses the existing `updateSettings({ theme })` store action.
- Icons: `Sun` when current theme is light (click → dark), `Moon` when dark (click → system), `Monitor` when system (click → light).

**Files:**
- `frontend/src/components/Sidebar/Sidebar.tsx` — add icon button to header

---

## 3. Streaming Status Labels

**Problem:** Status text shows "Sending..." at start of generation. Tool call status says "Running {tool}..." which is vague.

**Change:**
- Initial phase: `"Sending..."` → `"Connecting..."` (accurately describes the period between HTTP request and first SSE event — the model hasn't started generating yet).
- Tool call start: `"Running ${data.tool}..."` → `"Calling ${data.tool}..."`
- All other phases unchanged (`"Agent thinking..."`, `"Generating..."` on `inference_start` are already correct).

**Files:**
- `frontend/src/components/Chat/InputArea.tsx` — update two string literals

---

## 4. Model Switching — Loading Indicator

**Problem:** When switching models via Cmd+K, there's no visual feedback. The model badge updates instantly but Ollama needs time to load the new model into memory. Users may send messages before the model is ready.

**Change:**
- Add `modelLoading` boolean to the Zustand store.
- When `setSelectedModel` is called with a different model:
  1. Set `modelLoading = true`
  2. Update the model badge to show a spinner icon + "Loading model..." subtitle text
  3. Trigger Ollama to preload the model via `POST /api/generate` with `{"model": "...", "prompt": "", "keep_alive": "5m"}` (empty prompt loads the model without generating output). Use the same dual-path pattern as other API calls: Tauri invoke with HTTP fallback.
  4. On success, set `modelLoading = false`
  5. On failure after 120-second timeout, set `modelLoading = false` and show error in logs
- While `modelLoading` is true, disable the chat input (prevent sending before model is ready).
- Note: this preload mechanism is Ollama-specific. For other backends (vLLM, SGLang), skip the preload step (models are always loaded).

**Files:**
- `frontend/src/lib/store.ts` — add `modelLoading` state + `setModelLoading` action
- `frontend/src/lib/api.ts` — add `preloadModel()` function (Tauri invoke + HTTP fallback)
- `frontend/src/components/Sidebar/Sidebar.tsx` — show spinner + subtitle in model badge when loading
- `frontend/src/components/Chat/InputArea.tsx` — disable input when `modelLoading` is true
- `frontend/src/components/CommandPalette.tsx` — trigger model preloading on selection

---

## 5. Logs Page

**Problem:** Error logging is opaque. When generation fails, users see "Error: Failed to get response" with no way to diagnose what happened or share logs.

**Change:**
- Add a new `LogsPage` component at route `/logs`.
- Add "Logs" nav item to sidebar bottom nav (between Agents and Settings), with `ScrollText` icon.
- Log entries are collected in a Zustand array (`logEntries`) during the session.
- Sources of log entries:
  - SSE events during streaming (inference_start, tool_call_start, tool_call_end, errors)
  - Model switches and preload results
  - Server health check results
  - Fetch errors (chat, models, savings)
  - Model pull/delete operations
- Each entry: `{ timestamp: number, level: 'info' | 'warn' | 'error', category: string, message: string }`
- Add `LogEntry` interface to `frontend/src/types/index.ts`.
- Categories: `server`, `model`, `chat`, `tool`
- Color coding by **level only**: info = default text color, warn = yellow, error = red. Category shown as a bracketed prefix (e.g. `[model]`, `[chat]`).
- Actions: "Copy All" (copies log text to clipboard), "Clear" (resets array)
- Max 500 entries (FIFO via `.slice(-499)` before appending, matching the existing `addAgentEvent` pattern). Session-scoped (cleared on page reload).

**Files:**
- `frontend/src/pages/LogsPage.tsx` — new page component
- `frontend/src/types/index.ts` — add `LogEntry` interface
- `frontend/src/lib/store.ts` — add `logEntries` array, `addLogEntry` action, `clearLogs` action
- `frontend/src/components/Sidebar/Sidebar.tsx` — add Logs nav item
- `frontend/src/App.tsx` — add route for `/logs`
- `frontend/src/components/Chat/InputArea.tsx` — emit log entries for chat events
- `frontend/src/components/CommandPalette.tsx` — emit log entries for model operations

---

## Non-Goals

- No log persistence across sessions (localStorage is too small for meaningful logs)
- No log filtering/search (keep it simple for v1)
- No backend log forwarding (frontend-only collection from existing event streams)
- No changes to the backend streaming protocol (already emits the events we need)
- No Ollama-level model load progress bar (Ollama doesn't expose loading progress via API)
- No Windows temperature support in v1

---

## Testing

- Existing `tests/server/test_model_management.py` covers pull/delete/streaming endpoints (no changes needed)
- Frontend: TypeScript compilation (`tsc --noEmit`) validates all type changes
- Manual testing: verify all 6 changes in desktop app and web browser
- Add a pytest test for the extended `/v1/telemetry/energy` response (temp fields present, nullable)

---

## Summary of Changes by File

| File | Changes |
|------|---------|
| `SystemPanel.tsx` | Remove server-reported, rename ENERGY→DEVICE, add temps, remove Cool, use `getBase()` |
| `Sidebar.tsx` | Add theme toggle icon, add Logs nav item, model loading spinner |
| `InputArea.tsx` | Update phase labels ("Connecting...", "Calling ..."), disable during model loading |
| `CommandPalette.tsx` | Trigger model preloading, emit log entries |
| `store.ts` | Add `modelLoading`, `setModelLoading`, `logEntries`, `addLogEntry`, `clearLogs` |
| `types/index.ts` | Add `LogEntry` interface |
| `App.tsx` | Add `/logs` route, import LogsPage |
| `LogsPage.tsx` | New file — timestamped log viewer with Copy All / Clear |
| `api.ts` | Add `fetchDeviceInfo()`, `preloadModel()` functions |
| `api_routes.py` | Extend `/v1/telemetry/energy` to include `cpu_temp_c`, `gpu_temp_c` |
| `telemetry/` | Add CPU/GPU temp collection (macOS IOKit, Linux sysfs, NVIDIA already done) |
