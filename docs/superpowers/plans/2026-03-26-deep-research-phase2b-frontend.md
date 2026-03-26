# Deep Research Phase 2B-ii: Desktop Setup Wizard UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the "Apple-like magic" setup wizard in the Tauri desktop app — a beautiful multi-step onboarding flow that guides users through connecting their data sources, with product logos, progress bars, and a premium feel.

**Architecture:** Extends the existing `SetupScreen.tsx` in `frontend/src/components/` with new wizard steps after the engine boot completes. Uses the `/v1/connectors/*` API endpoints (Phase 2B-i) for backend communication. New components: SourcePicker (grid of connector cards), SourceConnectWizard (per-source auth flow), IngestDashboard (live sync progress), and ReadyScreen (first query suggestions). Follows existing patterns: Tailwind + shadcn/ui components, Zustand for state, React Router for navigation.

**Tech Stack:** TypeScript, React 19, Tailwind CSS 4.2, shadcn/ui, Zustand 5, Vite 6, Tauri 2

**Spec:** `docs/superpowers/specs/2026-03-25-deep-research-setup-design.md` — Section 4 (Setup Wizard)

**Depends on:** Phase 2B-i (connector API endpoints)

---

## File Structure

```
frontend/src/
├── components/
│   ├── setup/
│   │   ├── SetupWizard.tsx          # Main wizard orchestrator (steps 3-6)
│   │   ├── SourcePicker.tsx         # Step 3: grid of source cards
│   │   ├── SourceConnectFlow.tsx    # Step 4: guided per-source auth
│   │   ├── IngestDashboard.tsx      # Step 5: live sync progress
│   │   └── ReadyScreen.tsx          # Step 6: first query suggestions
│   ├── SetupScreen.tsx              # (modify) Add wizard after boot
├── lib/
│   ├── connectors-api.ts            # API client for /v1/connectors/*
│   └── store.ts                     # (modify) Add connector state slice
├── types/
│   └── connectors.ts                # TypeScript interfaces
```

---

### Task 1: TypeScript Types + API Client

**Files:**
- Create: `frontend/src/types/connectors.ts`
- Create: `frontend/src/lib/connectors-api.ts`

- [ ] **Step 1: Create connector types**

Create `frontend/src/types/connectors.ts`:

```typescript
export interface ConnectorInfo {
  connector_id: string;
  display_name: string;
  auth_type: "oauth" | "local" | "bridge" | "filesystem";
  connected: boolean;
  auth_url?: string;
  mcp_tools?: string[];
}

export interface SyncStatus {
  state: "idle" | "syncing" | "paused" | "error";
  items_synced: number;
  items_total: number;
  last_sync: string | null;
  error: string | null;
}

export interface ConnectRequest {
  path?: string;
  token?: string;
  code?: string;
  email?: string;
  password?: string;
}

export type WizardStep = "pick" | "connect" | "ingest" | "ready";

// Source card metadata for the picker UI
export interface SourceCard {
  connector_id: string;
  display_name: string;
  auth_type: string;
  category: "communication" | "documents" | "pim";
  icon: string;  // Lucide icon name
  color: string;  // Tailwind color class
  description: string;
}

export const SOURCE_CATALOG: SourceCard[] = [
  // Communication
  { connector_id: "gmail", display_name: "Gmail", auth_type: "oauth", category: "communication", icon: "Mail", color: "text-red-400", description: "Email messages and threads" },
  { connector_id: "gmail_imap", display_name: "Gmail (IMAP)", auth_type: "oauth", category: "communication", icon: "Mail", color: "text-red-400", description: "Email via app password" },
  { connector_id: "slack", display_name: "Slack", auth_type: "oauth", category: "communication", icon: "Hash", color: "text-purple-400", description: "Channel messages and threads" },
  { connector_id: "imessage", display_name: "iMessage", auth_type: "local", category: "communication", icon: "MessageSquare", color: "text-green-400", description: "macOS Messages history" },
  // Documents
  { connector_id: "gdrive", display_name: "Google Drive", auth_type: "oauth", category: "documents", icon: "FolderOpen", color: "text-blue-400", description: "Docs, Sheets, and files" },
  { connector_id: "notion", display_name: "Notion", auth_type: "oauth", category: "documents", icon: "FileText", color: "text-gray-300", description: "Pages and databases" },
  { connector_id: "obsidian", display_name: "Obsidian", auth_type: "filesystem", category: "documents", icon: "Diamond", color: "text-violet-400", description: "Markdown vault" },
  { connector_id: "granola", display_name: "Granola", auth_type: "oauth", category: "documents", icon: "Mic", color: "text-amber-400", description: "AI meeting notes" },
  // PIM
  { connector_id: "gcalendar", display_name: "Calendar", auth_type: "oauth", category: "pim", icon: "Calendar", color: "text-blue-400", description: "Events and meetings" },
  { connector_id: "gcontacts", display_name: "Contacts", auth_type: "oauth", category: "pim", icon: "Users", color: "text-blue-400", description: "People and contact info" },
];
```

- [ ] **Step 2: Create API client**

Create `frontend/src/lib/connectors-api.ts`:

```typescript
import { getBase } from "./api";
import type { ConnectorInfo, ConnectRequest, SyncStatus } from "../types/connectors";

export async function listConnectors(): Promise<ConnectorInfo[]> {
  const resp = await fetch(`${getBase()}/v1/connectors`);
  if (!resp.ok) throw new Error(`Failed to list connectors: ${resp.status}`);
  return resp.json();
}

export async function getConnector(id: string): Promise<ConnectorInfo> {
  const resp = await fetch(`${getBase()}/v1/connectors/${id}`);
  if (!resp.ok) throw new Error(`Connector not found: ${id}`);
  return resp.json();
}

export async function connectSource(id: string, req: ConnectRequest): Promise<{ connected: boolean }> {
  const resp = await fetch(`${getBase()}/v1/connectors/${id}/connect`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!resp.ok) throw new Error(`Failed to connect: ${resp.status}`);
  return resp.json();
}

export async function disconnectSource(id: string): Promise<void> {
  await fetch(`${getBase()}/v1/connectors/${id}/disconnect`, { method: "POST" });
}

export async function getSyncStatus(id: string): Promise<SyncStatus> {
  const resp = await fetch(`${getBase()}/v1/connectors/${id}/sync`);
  if (!resp.ok) throw new Error(`Failed to get sync status: ${id}`);
  return resp.json();
}
```

- [ ] **Step 3: Commit**

```bash
cd frontend && git add src/types/connectors.ts src/lib/connectors-api.ts
git commit -m "feat: add connector TypeScript types and API client"
```

---

### Task 2: SourcePicker Component (Step 3)

**Files:**
- Create: `frontend/src/components/setup/SourcePicker.tsx`

- [ ] **Step 1: Implement SourcePicker**

Create `frontend/src/components/setup/SourcePicker.tsx`:

```tsx
import { useState } from "react";
import {
  Mail, Hash, MessageSquare, FolderOpen, FileText,
  Diamond, Mic, Calendar, Users, Check,
} from "lucide-react";
import { SOURCE_CATALOG, type SourceCard } from "../../types/connectors";

const ICON_MAP: Record<string, React.ElementType> = {
  Mail, Hash, MessageSquare, FolderOpen, FileText,
  Diamond, Mic, Calendar, Users,
};

const CATEGORIES = [
  { key: "communication", label: "Communication" },
  { key: "documents", label: "Documents" },
  { key: "pim", label: "Personal Info" },
] as const;

interface Props {
  onContinue: (selectedIds: string[]) => void;
}

export function SourcePicker({ onContinue }: Props) {
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="flex flex-col items-center gap-8 px-8 py-12 max-w-4xl mx-auto">
      <div className="text-center">
        <h2 className="text-2xl font-semibold" style={{ color: "var(--color-text)" }}>
          Connect Your Data
        </h2>
        <p className="mt-2 text-sm opacity-60">
          Choose the sources you want to search across. You can always add more later.
        </p>
      </div>

      {CATEGORIES.map(({ key, label }) => (
        <div key={key} className="w-full">
          <h3 className="text-xs uppercase tracking-wider opacity-40 mb-3 px-1">
            {label}
          </h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
            {SOURCE_CATALOG.filter((s) => s.category === key).map((source) => {
              const Icon = ICON_MAP[source.icon] ?? FileText;
              const isSelected = selected.has(source.connector_id);
              return (
                <button
                  key={source.connector_id}
                  onClick={() => toggle(source.connector_id)}
                  className={`
                    relative flex flex-col items-center gap-2 p-4 rounded-xl
                    border transition-all duration-150 cursor-pointer
                    ${isSelected
                      ? "border-blue-500/60 bg-blue-500/10"
                      : "border-white/10 bg-white/5 hover:border-white/20 hover:bg-white/8"
                    }
                  `}
                >
                  {isSelected && (
                    <div className="absolute top-2 right-2">
                      <Check size={14} className="text-blue-400" />
                    </div>
                  )}
                  <Icon size={24} className={source.color} />
                  <span className="text-sm font-medium">{source.display_name}</span>
                  <span className="text-xs opacity-40 text-center">{source.description}</span>
                </button>
              );
            })}
          </div>
        </div>
      ))}

      <button
        onClick={() => onContinue(Array.from(selected))}
        disabled={selected.size === 0}
        className={`
          mt-4 px-8 py-3 rounded-xl font-medium transition-all
          ${selected.size > 0
            ? "bg-blue-500 text-white hover:bg-blue-400"
            : "bg-white/10 text-white/30 cursor-not-allowed"
          }
        `}
      >
        Connect {selected.size > 0 ? `${selected.size} source${selected.size > 1 ? "s" : ""}` : "sources"}
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
cd frontend && git add src/components/setup/SourcePicker.tsx
git commit -m "feat: add SourcePicker component with category grid and toggle selection"
```

---

### Task 3: SourceConnectFlow Component (Step 4)

**Files:**
- Create: `frontend/src/components/setup/SourceConnectFlow.tsx`

- [ ] **Step 1: Implement SourceConnectFlow**

Create `frontend/src/components/setup/SourceConnectFlow.tsx`:

```tsx
import { useState } from "react";
import { Check, ExternalLink, Loader2, X, FolderOpen } from "lucide-react";
import { SOURCE_CATALOG } from "../../types/connectors";
import { connectSource, getConnector } from "../../lib/connectors-api";

interface Props {
  selectedIds: string[];
  onComplete: () => void;
}

type SourceState = "pending" | "connecting" | "connected" | "skipped" | "error";

export function SourceConnectFlow({ selectedIds, onComplete }: Props) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [states, setStates] = useState<Record<string, SourceState>>(
    Object.fromEntries(selectedIds.map((id) => [id, "pending"]))
  );
  const [error, setError] = useState("");
  const [inputValue, setInputValue] = useState("");

  const currentId = selectedIds[currentIndex];
  const source = SOURCE_CATALOG.find((s) => s.connector_id === currentId);
  const isLast = currentIndex >= selectedIds.length - 1;
  const allDone = currentIndex >= selectedIds.length;

  const advance = () => {
    if (isLast) {
      onComplete();
    } else {
      setCurrentIndex((i) => i + 1);
      setInputValue("");
      setError("");
    }
  };

  const skip = () => {
    setStates((s) => ({ ...s, [currentId]: "skipped" }));
    advance();
  };

  const handleConnect = async () => {
    if (!currentId || !source) return;
    setStates((s) => ({ ...s, [currentId]: "connecting" }));
    setError("");

    try {
      if (source.auth_type === "filesystem") {
        const result = await connectSource(currentId, { path: inputValue });
        if (result.connected) {
          setStates((s) => ({ ...s, [currentId]: "connected" }));
          setTimeout(advance, 800);
        } else {
          throw new Error("Could not access that path");
        }
      } else if (source.auth_type === "oauth") {
        // Get auth URL and open in browser
        const info = await getConnector(currentId);
        if (info.auth_url) {
          window.open(info.auth_url, "_blank");
        }
        // For token/code entry
        if (inputValue) {
          const result = await connectSource(currentId, { token: inputValue });
          if (result.connected) {
            setStates((s) => ({ ...s, [currentId]: "connected" }));
            setTimeout(advance, 800);
          }
        }
      } else if (source.auth_type === "local") {
        // Local access (iMessage, Apple Notes) — just check
        const result = await connectSource(currentId, {});
        if (result.connected) {
          setStates((s) => ({ ...s, [currentId]: "connected" }));
          setTimeout(advance, 800);
        } else {
          throw new Error("Permission not granted. Check Full Disk Access in System Preferences.");
        }
      }
    } catch (err: any) {
      setError(err.message || "Connection failed");
      setStates((s) => ({ ...s, [currentId]: "error" }));
    }
  };

  if (allDone) {
    onComplete();
    return null;
  }

  return (
    <div className="flex gap-8 px-8 py-12 max-w-4xl mx-auto">
      {/* Sidebar checklist */}
      <div className="w-48 flex-shrink-0">
        <h3 className="text-xs uppercase tracking-wider opacity-40 mb-4">Progress</h3>
        {selectedIds.map((id, i) => {
          const s = SOURCE_CATALOG.find((x) => x.connector_id === id);
          const state = states[id];
          return (
            <div key={id} className={`flex items-center gap-2 py-2 text-sm ${i === currentIndex ? "opacity-100" : "opacity-40"}`}>
              {state === "connected" && <Check size={14} className="text-green-400" />}
              {state === "skipped" && <X size={14} className="text-gray-500" />}
              {state === "connecting" && <Loader2 size={14} className="animate-spin text-blue-400" />}
              {(state === "pending" || state === "error") && <div className="w-3.5 h-3.5 rounded-full border border-white/20" />}
              <span>{s?.display_name ?? id}</span>
            </div>
          );
        })}
      </div>

      {/* Main content */}
      <div className="flex-1">
        <h2 className="text-xl font-semibold mb-2">
          Connect {source?.display_name}
        </h2>

        {source?.auth_type === "filesystem" && (
          <div className="mt-6">
            <p className="text-sm opacity-60 mb-4">Enter the path to your vault or folder:</p>
            <div className="flex gap-2">
              <input
                type="text"
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                placeholder="/path/to/vault"
                className="flex-1 px-4 py-2 rounded-lg bg-white/5 border border-white/10 text-sm"
              />
              <button onClick={handleConnect} className="px-4 py-2 bg-blue-500 text-white rounded-lg text-sm hover:bg-blue-400">
                Connect
              </button>
            </div>
          </div>
        )}

        {source?.auth_type === "oauth" && (
          <div className="mt-6">
            <p className="text-sm opacity-60 mb-4">
              We'll open {source.display_name} in your browser for authorization. After authorizing, paste the token or code below.
            </p>
            <button
              onClick={handleConnect}
              className="flex items-center gap-2 px-4 py-2 bg-blue-500 text-white rounded-lg text-sm hover:bg-blue-400 mb-4"
            >
              <ExternalLink size={14} />
              Open {source.display_name}
            </button>
            <input
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder="Paste token or code here"
              className="w-full px-4 py-2 rounded-lg bg-white/5 border border-white/10 text-sm"
              onKeyDown={(e) => e.key === "Enter" && handleConnect()}
            />
          </div>
        )}

        {source?.auth_type === "local" && (
          <div className="mt-6">
            <p className="text-sm opacity-60 mb-4">
              This requires Full Disk Access on macOS. Grant access in System Preferences → Privacy & Security → Full Disk Access.
            </p>
            <button onClick={handleConnect} className="px-4 py-2 bg-blue-500 text-white rounded-lg text-sm hover:bg-blue-400">
              Check Access
            </button>
          </div>
        )}

        {error && (
          <p className="mt-4 text-sm text-red-400">{error}</p>
        )}

        <button onClick={skip} className="mt-6 text-sm opacity-40 hover:opacity-60 transition-opacity">
          Skip for now →
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
cd frontend && git add src/components/setup/SourceConnectFlow.tsx
git commit -m "feat: add SourceConnectFlow with per-source guided auth wizard"
```

---

### Task 4: IngestDashboard + ReadyScreen (Steps 5-6)

**Files:**
- Create: `frontend/src/components/setup/IngestDashboard.tsx`
- Create: `frontend/src/components/setup/ReadyScreen.tsx`

- [ ] **Step 1: Implement IngestDashboard**

Create `frontend/src/components/setup/IngestDashboard.tsx`:

```tsx
import { useEffect, useState } from "react";
import { Loader2, Check } from "lucide-react";
import { getSyncStatus } from "../../lib/connectors-api";
import { SOURCE_CATALOG, type SyncStatus } from "../../types/connectors";

interface Props {
  connectedIds: string[];
  onReady: () => void;
}

export function IngestDashboard({ connectedIds, onReady }: Props) {
  const [statuses, setStatuses] = useState<Record<string, SyncStatus>>({});

  useEffect(() => {
    if (connectedIds.length === 0) {
      onReady();
      return;
    }

    const poll = setInterval(async () => {
      const updates: Record<string, SyncStatus> = {};
      for (const id of connectedIds) {
        try {
          updates[id] = await getSyncStatus(id);
        } catch {
          updates[id] = { state: "error", items_synced: 0, items_total: 0, last_sync: null, error: "Failed to fetch status" };
        }
      }
      setStatuses(updates);

      // Check if all done
      const allIdle = Object.values(updates).every((s) => s.state === "idle" && s.items_synced > 0);
      if (allIdle) {
        clearInterval(poll);
      }
    }, 2000);

    return () => clearInterval(poll);
  }, [connectedIds]);

  return (
    <div className="flex flex-col items-center gap-8 px-8 py-12 max-w-3xl mx-auto">
      <div className="text-center">
        <h2 className="text-2xl font-semibold" style={{ color: "var(--color-text)" }}>
          Indexing Your Data
        </h2>
        <p className="mt-2 text-sm opacity-60">
          Your data is being synced and indexed. You can start asking questions now.
        </p>
      </div>

      <div className="w-full space-y-4">
        {connectedIds.map((id) => {
          const source = SOURCE_CATALOG.find((s) => s.connector_id === id);
          const status = statuses[id];
          const synced = status?.items_synced ?? 0;
          const total = status?.items_total ?? 0;
          const pct = total > 0 ? Math.round((synced / total) * 100) : 0;
          const isDone = status?.state === "idle" && synced > 0;

          return (
            <div key={id} className="flex items-center gap-4 p-4 rounded-xl bg-white/5 border border-white/10">
              <div className="w-8">
                {isDone ? (
                  <Check size={18} className="text-green-400" />
                ) : (
                  <Loader2 size={18} className="animate-spin text-blue-400" />
                )}
              </div>
              <div className="flex-1">
                <div className="flex justify-between text-sm mb-1">
                  <span className="font-medium">{source?.display_name ?? id}</span>
                  <span className="opacity-40">
                    {isDone ? `${synced.toLocaleString()} items` : total > 0 ? `${synced.toLocaleString()} / ${total.toLocaleString()}` : "Starting..."}
                  </span>
                </div>
                <div className="h-1.5 rounded-full bg-white/10 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-blue-500 transition-all duration-500"
                    style={{ width: `${isDone ? 100 : pct}%` }}
                  />
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <button
        onClick={onReady}
        className="mt-4 px-8 py-3 bg-blue-500 text-white rounded-xl font-medium hover:bg-blue-400 transition-all"
      >
        Start Researching →
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Implement ReadyScreen**

Create `frontend/src/components/setup/ReadyScreen.tsx`:

```tsx
import { Sparkles } from "lucide-react";

interface Props {
  connectedSources: string[];
  onStart: (query?: string) => void;
}

const SUGGESTIONS = [
  "What were the key decisions from last week's team threads?",
  "Find the proposal doc shared about the roadmap",
  "Summarize my unread emails from today",
  "What meetings do I have this week?",
  "What topics came up in recent meetings?",
];

export function ReadyScreen({ connectedSources, onStart }: Props) {
  return (
    <div className="flex flex-col items-center gap-8 px-8 py-16 max-w-2xl mx-auto text-center">
      <div className="w-16 h-16 rounded-2xl bg-green-500/10 flex items-center justify-center">
        <Sparkles size={32} className="text-green-400" />
      </div>

      <div>
        <h2 className="text-2xl font-semibold" style={{ color: "var(--color-text)" }}>
          You're All Set!
        </h2>
        <p className="mt-2 text-sm opacity-60">
          {connectedSources.length} source{connectedSources.length !== 1 ? "s" : ""} connected and indexed. Ask anything across your data.
        </p>
      </div>

      <div className="w-full space-y-2">
        <p className="text-xs uppercase tracking-wider opacity-40 mb-3">Try asking...</p>
        {SUGGESTIONS.slice(0, 3).map((q) => (
          <button
            key={q}
            onClick={() => onStart(q)}
            className="w-full text-left px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-sm hover:border-blue-500/40 hover:bg-blue-500/5 transition-all"
          >
            {q}
          </button>
        ))}
      </div>

      <button
        onClick={() => onStart()}
        className="px-8 py-3 bg-blue-500 text-white rounded-xl font-medium hover:bg-blue-400 transition-all"
      >
        Open Chat
      </button>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
cd frontend && git add src/components/setup/IngestDashboard.tsx src/components/setup/ReadyScreen.tsx
git commit -m "feat: add IngestDashboard with progress bars and ReadyScreen with suggestions"
```

---

### Task 5: SetupWizard Orchestrator + Integration

**Files:**
- Create: `frontend/src/components/setup/SetupWizard.tsx`
- Modify: `frontend/src/components/SetupScreen.tsx`

- [ ] **Step 1: Create SetupWizard orchestrator**

Create `frontend/src/components/setup/SetupWizard.tsx`:

```tsx
import { useState } from "react";
import type { WizardStep } from "../../types/connectors";
import { SourcePicker } from "./SourcePicker";
import { SourceConnectFlow } from "./SourceConnectFlow";
import { IngestDashboard } from "./IngestDashboard";
import { ReadyScreen } from "./ReadyScreen";

interface Props {
  onComplete: (firstQuery?: string) => void;
}

export function SetupWizard({ onComplete }: Props) {
  const [step, setStep] = useState<WizardStep>("pick");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [connectedIds, setConnectedIds] = useState<string[]>([]);

  switch (step) {
    case "pick":
      return (
        <SourcePicker
          onContinue={(ids) => {
            setSelectedIds(ids);
            if (ids.length > 0) {
              setStep("connect");
            } else {
              onComplete();
            }
          }}
        />
      );

    case "connect":
      return (
        <SourceConnectFlow
          selectedIds={selectedIds}
          onComplete={() => {
            // For now, assume all selected are connected
            setConnectedIds(selectedIds);
            setStep("ingest");
          }}
        />
      );

    case "ingest":
      return (
        <IngestDashboard
          connectedIds={connectedIds}
          onReady={() => setStep("ready")}
        />
      );

    case "ready":
      return (
        <ReadyScreen
          connectedSources={connectedIds}
          onStart={(query) => onComplete(query)}
        />
      );
  }
}
```

- [ ] **Step 2: Integrate into SetupScreen**

Modify `frontend/src/components/SetupScreen.tsx` to show the wizard after the boot sequence completes. Find the section where `status.phase === 'ready'` triggers `onReady()`. Instead of calling `onReady()` immediately, show the `SetupWizard`:

Add to the imports:
```tsx
import { SetupWizard } from "./setup/SetupWizard";
```

Add state to track whether wizard is shown:
```tsx
const [showWizard, setShowWizard] = useState(false);
```

When boot completes (phase === 'ready'), instead of calling `onReady()`, set `showWizard = true`. Then render:
```tsx
if (showWizard) {
  return <SetupWizard onComplete={(query) => {
    // Optionally pass first query to chat
    onReady();
  }} />;
}
```

- [ ] **Step 3: Commit**

```bash
cd frontend && git add src/components/setup/SetupWizard.tsx src/components/SetupScreen.tsx
git commit -m "feat: integrate SetupWizard into boot flow after engine setup"
```

---

## Post-Plan Notes

**What this plan produces:**
- TypeScript types and API client for connector management
- SourcePicker: beautiful grid of 10 source cards with category grouping and toggle selection
- SourceConnectFlow: guided per-source auth wizard with sidebar progress checklist
- IngestDashboard: live progress bars polling sync status
- ReadyScreen: celebration screen with suggested first queries
- SetupWizard: orchestrates all 4 steps
- Integration into existing SetupScreen boot flow

**What this does NOT include (separate effort):**
- Actual OAuth redirect handling in Tauri (needs Tauri deep link plugin)
- File picker dialog for Obsidian (needs Tauri dialog plugin)
- QR code display for WhatsApp
- Product logo images (would need asset files)
- Tauri command wrappers for the API endpoints
- Automated sync triggering after connect
