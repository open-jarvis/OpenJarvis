# Desktop UX Improvements Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the OpenJarvis desktop app and web browser UX with 7 changes: new app logo, cleaner system panel with device temps, theme toggle, better streaming labels, model switching feedback, and a logs page.

**Architecture:** All changes are frontend-first (React/TypeScript/Zustand). One backend change extends the existing `/v1/telemetry/energy` endpoint to include temperature fields already collected by `EnergySample`. No new backend endpoints needed — temperatures are already in the data pipeline, just not exposed via the API.

**Tech Stack:** React 19, TypeScript, Zustand, Tailwind CSS, Lucide icons, FastAPI (backend), Python telemetry modules, sips (macOS image conversion)

**Spec:** `docs/superpowers/specs/2026-03-14-desktop-ux-improvements-design.md`

---

## Chunk 0: App Logo

### Task 0: Replace app icons with new arc reactor logo

**Source image:** `/Users/jonsaadfalcon/Documents/OpenJarvis_Logos/OpenJarvis_DesktopAppLogo_DarkBackground_ZoomedIn.png`

**Files:**
- Replace: `desktop/src-tauri/icons/32x32.png`
- Replace: `desktop/src-tauri/icons/128x128.png`
- Replace: `desktop/src-tauri/icons/128x128@2x.png`
- Replace: `desktop/src-tauri/icons/256x256.png`
- Replace: `desktop/src-tauri/icons/icon.png`
- Replace: `desktop/src-tauri/icons/icon.icns`
- Replace: `desktop/src-tauri/icons/icon.ico`
- Replace: `frontend/public/favicon.ico`
- Replace: `frontend/public/apple-touch-icon.png`
- Replace: `frontend/public/pwa-192x192.png`
- Replace: `frontend/public/pwa-512x512.png`

- [ ] **Step 1: Generate all PNG sizes from source image**

```bash
SRC="/Users/jonsaadfalcon/Documents/OpenJarvis_Logos/OpenJarvis_DesktopAppLogo_DarkBackground_ZoomedIn.png"
ICONS="desktop/src-tauri/icons"
PUBLIC="frontend/public"

# Desktop icons
sips -z 32 32 "$SRC" --out "$ICONS/32x32.png"
sips -z 128 128 "$SRC" --out "$ICONS/128x128.png"
sips -z 256 256 "$SRC" --out "$ICONS/128x128@2x.png"
sips -z 256 256 "$SRC" --out "$ICONS/256x256.png"
sips -z 1024 1024 "$SRC" --out "$ICONS/icon.png"

# Frontend icons
sips -z 180 180 "$SRC" --out "$PUBLIC/apple-touch-icon.png"
sips -z 192 192 "$SRC" --out "$PUBLIC/pwa-192x192.png"
sips -z 512 512 "$SRC" --out "$PUBLIC/pwa-512x512.png"
```

- [ ] **Step 2: Generate .icns for macOS**

```bash
mkdir -p /tmp/openjarvis-icon.iconset
sips -z 16 16 "$SRC" --out /tmp/openjarvis-icon.iconset/icon_16x16.png
sips -z 32 32 "$SRC" --out /tmp/openjarvis-icon.iconset/icon_16x16@2x.png
sips -z 32 32 "$SRC" --out /tmp/openjarvis-icon.iconset/icon_32x32.png
sips -z 64 64 "$SRC" --out /tmp/openjarvis-icon.iconset/icon_32x32@2x.png
sips -z 128 128 "$SRC" --out /tmp/openjarvis-icon.iconset/icon_128x128.png
sips -z 256 256 "$SRC" --out /tmp/openjarvis-icon.iconset/icon_128x128@2x.png
sips -z 256 256 "$SRC" --out /tmp/openjarvis-icon.iconset/icon_256x256.png
sips -z 512 512 "$SRC" --out /tmp/openjarvis-icon.iconset/icon_256x256@2x.png
sips -z 512 512 "$SRC" --out /tmp/openjarvis-icon.iconset/icon_512x512.png
sips -z 1024 1024 "$SRC" --out /tmp/openjarvis-icon.iconset/icon_512x512@2x.png
iconutil -c icns /tmp/openjarvis-icon.iconset -o "$ICONS/icon.icns"
rm -rf /tmp/openjarvis-icon.iconset
```

- [ ] **Step 3: Generate .ico for Windows**

```bash
# Use sips to create the sizes, then ImageMagick convert (or pip install Pillow)
python3 -c "
from PIL import Image
img = Image.open('$ICONS/icon.png')
img.save('$ICONS/icon.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
"
```

If Pillow is not available, install with `pip3 install Pillow` first.

- [ ] **Step 4: Generate favicon.ico for web**

```bash
python3 -c "
from PIL import Image
img = Image.open('$PUBLIC/pwa-512x512.png')
img.save('$PUBLIC/favicon.ico', sizes=[(16,16),(32,32),(48,48)])
"
```

- [ ] **Step 5: Verify icons exist and are correct sizes**

```bash
file desktop/src-tauri/icons/*.png desktop/src-tauri/icons/icon.icns desktop/src-tauri/icons/icon.ico
file frontend/public/favicon.ico frontend/public/apple-touch-icon.png frontend/public/pwa-*.png
```

- [ ] **Step 6: Commit**

```bash
git add desktop/src-tauri/icons/ frontend/public/favicon.ico frontend/public/apple-touch-icon.png frontend/public/pwa-192x192.png frontend/public/pwa-512x512.png
git commit -m "feat: replace app icons with arc reactor logo"
```

---

## Chunk 1: Foundation — Types, Store, and Backend

### Task 1: Add LogEntry type and extend store

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/lib/store.ts`

- [ ] **Step 1: Add LogEntry interface to types**

In `frontend/src/types/index.ts`, add after the `ServerInfo` interface (line 120):

```typescript
// --- Log Types ---

export interface LogEntry {
  timestamp: number;
  level: 'info' | 'warn' | 'error';
  category: 'server' | 'model' | 'chat' | 'tool';
  message: string;
}
```

- [ ] **Step 2: Add log and model-loading state to store**

In `frontend/src/lib/store.ts`, add to the `AppState` interface (after line 183, the `setSelectedAgentId` line):

```typescript
  // Logs
  logEntries: LogEntry[];
  addLogEntry: (entry: LogEntry) => void;
  clearLogs: () => void;

  // Model loading
  modelLoading: boolean;
  setModelLoading: (loading: boolean) => void;
```

Add the import at the top of `store.ts`:

```typescript
import type { LogEntry } from '../types';
```

(Add `LogEntry` to the existing import from `'../types'`.)

Add the implementations in the store body (after the agent events section, ~line 388):

```typescript
    // ── Logs ────────────────────────────────────────────────────────
    logEntries: [],
    addLogEntry: (entry) => set((s) => ({
      logEntries: [...s.logEntries.slice(-499), entry],
    })),
    clearLogs: () => set({ logEntries: [] }),

    // ── Model loading ───────────────────────────────────────────────
    modelLoading: false,
    setModelLoading: (loading) => set({ modelLoading: loading }),
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/lib/store.ts
git commit -m "feat: add LogEntry type, log store, and modelLoading state"
```

---

### Task 2: Expose temperature in /v1/telemetry/energy endpoint

**Files:**
- Modify: `src/openjarvis/server/api_routes.py:240-271`

The `EnergySample` dataclass already has `mean_temperature_c` and `peak_temperature_c` fields (populated by NVIDIA monitors, zero for others). We just need to include them in the API response.

- [ ] **Step 1: Add temp fields to the energy endpoint response**

In `src/openjarvis/server/api_routes.py`, in the `telemetry_energy` function, update the return dict (lines 259-267) to:

```python
            return {
                "total_energy_j": total_energy,
                "energy_per_token_j": (
                    total_energy / total_tokens if total_tokens > 0 else 0
                ),
                "avg_power_w": (
                    total_energy / total_latency if total_latency > 0 else 0
                ),
                "cpu_temp_c": None,  # populated per-platform below
                "gpu_temp_c": None,
            }
```

Note: The current aggregator `summary()` doesn't directly expose per-sample temperature. For v1, return `None` (the frontend handles graceful degradation). A follow-up task can wire the live energy monitor's last sample temperature through.

Also update the empty fallback response (line 250) to include the new fields:

```python
            return {"total_energy_j": 0, "energy_per_token_j": 0, "avg_power_w": 0, "cpu_temp_c": None, "gpu_temp_c": None}
```

- [ ] **Step 2: Run lint and tests**

Run: `uv run ruff check src/openjarvis/server/api_routes.py`
Run: `uv run pytest tests/server/ -v --tb=short`
Expected: all pass

- [ ] **Step 3: Commit**

```bash
git add src/openjarvis/server/api_routes.py
git commit -m "feat: include cpu/gpu temp fields in telemetry energy endpoint"
```

---

### Task 3: Add preloadModel to api.ts

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add preloadModel function**

Add after the `deleteModel` function in `api.ts`:

```typescript
export async function preloadModel(modelName: string): Promise<void> {
  // Trigger Ollama to load the model into memory (empty prompt, no generation).
  // In Tauri, use the Rust backend; in browser, call Ollama directly via the server.
  const ollamaUrl = 'http://127.0.0.1:11434';
  try {
    const res = await fetch(`${ollamaUrl}/api/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: modelName, prompt: '', keep_alive: '5m' }),
      signal: AbortSignal.timeout(120_000),
    });
    if (!res.ok) throw new Error(`Preload failed: ${res.status}`);
  } catch (e: any) {
    if (e.name === 'TimeoutError') throw new Error('Model load timed out (120s)');
    throw e;
  }
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add preloadModel API function for model warm-up"
```

---

## Chunk 2: UI Changes — SystemPanel, Sidebar, Streaming Labels

### Task 4: Clean up SystemPanel (remove redundancy, rename ENERGY to DEVICE)

**Files:**
- Modify: `frontend/src/components/Chat/SystemPanel.tsx`

- [ ] **Step 1: Update fetch to use getBase()**

Replace the `fetchData` callback (lines 42-58) to use `getBase()` from api.ts:

```typescript
import { getBase } from '../../lib/api';
```

Then change line 44 from:
```typescript
      const base = import.meta.env.VITE_API_URL || '';
```
to:
```typescript
      const base = getBase();
```

- [ ] **Step 2: Add temp fields to EnergyData interface**

Update the `EnergyData` interface (lines 17-21):

```typescript
interface EnergyData {
  total_energy_j?: number;
  energy_per_token_j?: number;
  avg_power_w?: number;
  cpu_temp_c?: number | null;
  gpu_temp_c?: number | null;
}
```

- [ ] **Step 3: Remove thermalStatus logic and "Cool" label**

Delete lines 71-76 (the `thermalStatus` const).

Replace the Energy section (lines 121-155) with:

```tsx
        {/* Device */}
        <section>
          <h4 className="text-[11px] font-medium uppercase tracking-wide mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
            Device
          </h4>
          <div className="grid grid-cols-2 gap-2">
            {energy?.cpu_temp_c != null && (
              <MiniStat icon={Thermometer} label="CPU Temp" value={String(Math.round(energy.cpu_temp_c))} unit="°C" />
            )}
            {energy?.gpu_temp_c != null && (
              <MiniStat icon={Thermometer} label="GPU Temp" value={String(Math.round(energy.gpu_temp_c))} unit="°C" />
            )}
            <MiniStat
              icon={Zap}
              label="Power"
              value={(energy?.avg_power_w ?? 0).toFixed(1)}
              unit="W"
            />
            <MiniStat
              icon={Activity}
              label="Energy"
              value={((energy?.total_energy_j ?? 0) / 1000).toFixed(1)}
              unit="kJ"
            />
          </div>
        </section>
```

- [ ] **Step 4: Remove Server-reported section**

Delete lines 220-233 (the "Server-reported savings" block).

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Chat/SystemPanel.tsx
git commit -m "feat: replace Energy section with Device (temps, power, energy), remove server-reported"
```

---

### Task 5: Add theme toggle to sidebar header

**Files:**
- Modify: `frontend/src/components/Sidebar/Sidebar.tsx`

- [ ] **Step 1: Add imports and store access**

Add `Sun`, `Moon`, `Monitor` to the lucide-react import (line 3):

```typescript
import {
  MessageSquare,
  Plus,
  BarChart3,
  Settings,
  Search,
  PanelLeftClose,
  PanelLeft,
  Cpu,
  Rocket,
  Bot,
  Sun,
  Moon,
  Monitor,
} from 'lucide-react';
```

Inside the `Sidebar` component, add after `setCommandPaletteOpen` (line 28):

```typescript
  const settings = useAppStore((s) => s.settings);
  const updateSettings = useAppStore((s) => s.updateSettings);

  const ThemeIcon = settings.theme === 'light' ? Sun : settings.theme === 'dark' ? Moon : Monitor;
  const nextTheme = settings.theme === 'light' ? 'dark' : settings.theme === 'dark' ? 'system' : 'light';
```

- [ ] **Step 2: Add the icon button in the header**

In the header `div` (line 68), insert the theme toggle button between the collapse button and the new-chat button. Replace the header div:

```tsx
          <div className="flex items-center justify-between px-3 pt-3 pb-2">
            <button
              onClick={toggleSidebar}
              className="p-2 rounded-lg transition-colors cursor-pointer"
              style={{ color: 'var(--color-text-secondary)' }}
              onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
            >
              <PanelLeftClose size={18} />
            </button>
            <div className="flex items-center gap-1">
              <button
                onClick={() => updateSettings({ theme: nextTheme })}
                className="p-2 rounded-lg transition-colors cursor-pointer"
                style={{ color: 'var(--color-text-secondary)' }}
                onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
                onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                title={`Theme: ${settings.theme} (click for ${nextTheme})`}
              >
                <ThemeIcon size={16} />
              </button>
              <button
                onClick={handleNewChat}
                className="p-2 rounded-lg transition-colors cursor-pointer"
                style={{ color: 'var(--color-text-secondary)' }}
                onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
                onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                title="New chat"
              >
                <Plus size={18} />
              </button>
            </div>
          </div>
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Sidebar/Sidebar.tsx
git commit -m "feat: add theme toggle icon in sidebar header"
```

---

### Task 6: Update streaming status labels

**Files:**
- Modify: `frontend/src/components/Chat/InputArea.tsx`

- [ ] **Step 1: Change "Sending..." to "Connecting..."**

Find the `setStreamState` call at ~line 132:

```typescript
    setStreamState({
      isStreaming: true,
      phase: 'Sending...',
```

Change to:

```typescript
    setStreamState({
      isStreaming: true,
      phase: 'Connecting...',
```

- [ ] **Step 2: Change "Running {tool}..." to "Calling {tool}..."**

Find the string `Running ${data.tool}...` (in the `tool_call_start` handler):

```typescript
              phase: `Running ${data.tool}...`,
```

Change to:

```typescript
              phase: `Calling ${data.tool}...`,
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Chat/InputArea.tsx
git commit -m "fix: update streaming labels to Connecting/Calling"
```

---

## Chunk 3: Model Loading Indicator

### Task 7: Wire model preloading through CommandPalette and show loading in sidebar

**Files:**
- Modify: `frontend/src/components/CommandPalette.tsx`
- Modify: `frontend/src/components/Sidebar/Sidebar.tsx`
- Modify: `frontend/src/components/Chat/InputArea.tsx`

- [ ] **Step 1: Trigger preload on model selection in CommandPalette**

In `CommandPalette.tsx`, add imports:

```typescript
import { pullModel, deleteModel, fetchModels, preloadModel } from '../lib/api';
```

(`preloadModel` added to the existing import.)

Update `handleSelect` (line 68-71) to:

```typescript
  const handleSelect = async (modelId: string) => {
    const previousModel = selectedModel;
    setSelectedModel(modelId);
    setCommandPaletteOpen(false);

    // Preload the model if switching to a different one
    if (modelId !== previousModel) {
      const { setModelLoading, addLogEntry } = useAppStore.getState();
      setModelLoading(true);
      addLogEntry({ timestamp: Date.now(), level: 'info', category: 'model', message: `Switching to ${modelId}...` });
      try {
        await preloadModel(modelId);
        addLogEntry({ timestamp: Date.now(), level: 'info', category: 'model', message: `${modelId} loaded` });
      } catch (e: any) {
        addLogEntry({ timestamp: Date.now(), level: 'error', category: 'model', message: `Failed to load ${modelId}: ${e.message}` });
      } finally {
        setModelLoading(false);
      }
    }
  };
```

- [ ] **Step 2: Show loading state in sidebar model badge**

In `Sidebar.tsx`, add to store access:

```typescript
  const modelLoading = useAppStore((s) => s.modelLoading);
```

Add `Loader2` to the lucide-react imports.

Update the model badge inner content (lines 102-111 inside the button). Replace everything between the opening `>` of the button and the closing `</button>`:

```tsx
            {modelLoading ? (
              <Loader2 size={14} className="animate-spin" style={{ color: 'var(--color-accent)' }} />
            ) : (
              <Cpu size={14} />
            )}
            <div className="flex-1 min-w-0">
              <span className="truncate block text-left" style={{ color: 'var(--color-text)' }}>
                {selectedModel || serverInfo?.model || 'Select model'}
              </span>
              {modelLoading && (
                <span className="text-[10px] block" style={{ color: 'var(--color-accent)' }}>
                  Loading model...
                </span>
              )}
            </div>
            {!modelLoading && (
              <kbd
                className="text-[10px] px-1.5 py-0.5 rounded font-mono"
                style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-tertiary)' }}
              >
                ⌘K
              </kbd>
            )}
```

- [ ] **Step 3: Disable input during model loading**

In `InputArea.tsx`, add:

```typescript
  const modelLoading = useAppStore((s) => s.modelLoading);
```

Find the textarea's `disabled={streamState.isStreaming}` and change to:

```typescript
          disabled={streamState.isStreaming || modelLoading}
```

Find the send button's `disabled={!input.trim()}` and change to:

```typescript
              disabled={!input.trim() || modelLoading}
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/CommandPalette.tsx frontend/src/components/Sidebar/Sidebar.tsx frontend/src/components/Chat/InputArea.tsx
git commit -m "feat: model switching shows loading spinner, disables input until ready"
```

---

## Chunk 4: Logs Page and Log Emission

### Task 8: Create LogsPage component

**Files:**
- Create: `frontend/src/pages/LogsPage.tsx`

- [ ] **Step 1: Create the LogsPage**

```typescript
import { useRef, useEffect } from 'react';
import { ScrollText, Copy, Trash2 } from 'lucide-react';
import { useAppStore } from '../lib/store';

const LEVEL_COLORS: Record<string, string> = {
  info: 'var(--color-text)',
  warn: 'var(--color-warning)',
  error: 'var(--color-error)',
};

function formatTime(ts: number): string {
  const d = new Date(ts);
  return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function LogsPage() {
  const logEntries = useAppStore((s) => s.logEntries);
  const clearLogs = useAppStore((s) => s.clearLogs);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logEntries.length]);

  const handleCopy = async () => {
    const text = logEntries
      .map((e) => `${formatTime(e.timestamp)} [${e.level}] [${e.category}] ${e.message}`)
      .join('\n');
    await navigator.clipboard.writeText(text);
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden p-6">
      <div className="max-w-4xl mx-auto w-full flex flex-col flex-1 overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-3 mb-4 shrink-0">
          <ScrollText size={24} style={{ color: 'var(--color-accent)' }} />
          <h1 className="text-xl font-semibold flex-1" style={{ color: 'var(--color-text)' }}>
            Logs
          </h1>
          <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            {logEntries.length} entries
          </span>
          <button
            onClick={handleCopy}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer"
            style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
          >
            <Copy size={12} /> Copy All
          </button>
          <button
            onClick={clearLogs}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer"
            style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
          >
            <Trash2 size={12} /> Clear
          </button>
        </div>

        {/* Log entries */}
        <div
          className="flex-1 overflow-y-auto rounded-xl p-4 font-mono text-xs leading-relaxed"
          style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
        >
          {logEntries.length === 0 ? (
            <div className="text-center py-12" style={{ color: 'var(--color-text-tertiary)' }}>
              No log entries yet. Logs appear as you chat, switch models, and interact with the app.
            </div>
          ) : (
            logEntries.map((entry, i) => (
              <div key={i} className="py-0.5">
                <span style={{ color: 'var(--color-text-tertiary)' }}>{formatTime(entry.timestamp)}</span>
                {' '}
                <span style={{ color: LEVEL_COLORS[entry.level] || 'var(--color-text)' }}>
                  [{entry.category}]
                </span>
                {' '}
                <span style={{ color: LEVEL_COLORS[entry.level] || 'var(--color-text)' }}>
                  {entry.message}
                </span>
              </div>
            ))
          )}
          <div ref={bottomRef} />
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/LogsPage.tsx
git commit -m "feat: create LogsPage component"
```

---

### Task 9: Add Logs route and nav item

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Sidebar/Sidebar.tsx`

- [ ] **Step 1: Add route in App.tsx**

Add import at top of `App.tsx`:

```typescript
import { LogsPage } from './pages/LogsPage';
```

Add route inside the `<Route element={<Layout />}>` block, after the agents route:

```tsx
          <Route path="logs" element={<LogsPage />} />
```

- [ ] **Step 2: Add Logs nav item in Sidebar.tsx**

Add `ScrollText` to the lucide-react import.

In the `navItems` array (lines 35-41), add between Agents and Settings:

```typescript
    { path: '/logs', icon: ScrollText, label: 'Logs' },
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/Sidebar/Sidebar.tsx
git commit -m "feat: add Logs route and nav item"
```

---

### Task 10: Emit log entries from chat and model operations

**Files:**
- Modify: `frontend/src/components/Chat/InputArea.tsx`
- Modify: `frontend/src/components/CommandPalette.tsx`

- [ ] **Step 1: Add log emission to InputArea streaming**

In `InputArea.tsx`, add at top of the `sendMessage` callback, after the `setStreamState` call (~line 122):

```typescript
    useAppStore.getState().addLogEntry({
      timestamp: Date.now(),
      level: 'info',
      category: 'chat',
      message: `Request: "${content.slice(0, 80)}${content.length > 80 ? '...' : ''}" → ${selectedModel}`,
    });
```

In the `inference_start` event handler (~line 149), add:

```typescript
          setStreamState({ phase: 'Generating...' });
          useAppStore.getState().addLogEntry({
            timestamp: Date.now(), level: 'info', category: 'chat',
            message: `Generating with ${selectedModel}...`,
          });
```

In the `tool_call_start` handler (~line 152), add after the existing `setStreamState`:

```typescript
            useAppStore.getState().addLogEntry({
              timestamp: Date.now(), level: 'info', category: 'tool',
              message: `Calling ${data.tool}(${data.arguments || ''})`,
            });
```

In the error catch (~line 191), add:

```typescript
      if (err.name !== 'AbortError') {
        useAppStore.getState().addLogEntry({
          timestamp: Date.now(), level: 'error', category: 'chat',
          message: `Stream error: ${err?.message || String(err)}`,
        });
      }
```

In the finally block, after `resetStream()`, add:

```typescript
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(), level: 'info', category: 'chat',
        message: `Response: ${accumulatedContent.length} chars`,
      });
```

- [ ] **Step 2: Add log emission to CommandPalette model operations**

In `CommandPalette.tsx`, the model switch logging was already added in Task 7. Add logging for pull and delete operations.

In `handlePull` (~line 80), add after `setPullSuccess`:

```typescript
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(), level: 'info', category: 'model',
        message: `Downloaded ${modelId}`,
      });
```

In `handlePull` catch block:

```typescript
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(), level: 'error', category: 'model',
        message: `Download failed for ${modelId}: ${e.message}`,
      });
```

In `handleDelete`, after the `deleteModel` call:

```typescript
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(), level: 'info', category: 'model',
        message: `Deleted ${modelId}`,
      });
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 4: Run full lint**

Run: `uv run ruff check src/ tests/`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Chat/InputArea.tsx frontend/src/components/CommandPalette.tsx
git commit -m "feat: emit log entries from chat streaming and model operations"
```

---

## Chunk 5: Final Verification

### Task 11: Build and test everything

- [ ] **Step 1: Run TypeScript check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 2: Run frontend build**

Run: `cd frontend && npm run build`
Expected: successful build

- [ ] **Step 3: Run Python lint**

Run: `uv run ruff check src/ tests/`
Expected: all pass

- [ ] **Step 4: Run Python tests**

Run: `uv run pytest tests/server/ -v --tb=short`
Expected: all 100+ tests pass

- [ ] **Step 5: Run Rust cargo check (for desktop)**

Run: `cd desktop/src-tauri && cargo check`
Expected: no errors (our changes are frontend + Python only, but verify no breakage)

- [ ] **Step 6: Final commit with all files verified**

If any files weren't committed in previous tasks:

```bash
git status
# add any remaining files
git commit -m "chore: final verification — all checks pass"
```
