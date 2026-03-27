# Channels + Messaging Tabs Implementation Plan (v2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the existing Channels tab with two tabs — **Channels** (data sources with chunk counts and inline "+ Add" setup) and **Messaging** (clear "Text this number from your iPhone" instructions) — on every agent detail page.

**Architecture:** Refactor the existing `ChannelsTab` component in `AgentsPage.tsx` into two separate components. The Channels tab calls existing connector API endpoints + a new chunk-count endpoint. The Messaging tab reuses the existing channel binding API. The `StepByStepPanel` from `SourceConnectFlow.tsx` is extracted for reuse in the Channels tab inline setup.

**Tech Stack:** React 19, TypeScript, existing FastAPI endpoints

---

### Task 1: Add connector chunk counts to backend API

**Files:**
- Modify: `src/openjarvis/server/connectors_router.py`

The Channels tab needs to show chunk counts per source. Add a `chunks` field to the connector summary by querying the KnowledgeStore.

- [ ] **Step 1: Modify `_connector_summary` to include chunk count**

In `src/openjarvis/server/connectors_router.py`, find the `_connector_summary` function (line ~102). Add a chunk count from the KnowledgeStore:

```python
def _connector_summary(connector_id: str, instance: Any) -> Dict[str, Any]:
    """Build the dict returned by GET /connectors."""
    chunks = 0
    try:
        from openjarvis.connectors.store import KnowledgeStore
        store = KnowledgeStore()
        rows = store._conn.execute(
            "SELECT COUNT(*) FROM knowledge_chunks WHERE source = ?",
            (connector_id,),
        ).fetchone()
        chunks = rows[0] if rows else 0
    except Exception:
        pass

    return {
        "connector_id": connector_id,
        "display_name": getattr(instance, "display_name", connector_id),
        "auth_type": getattr(instance, "auth_type", "unknown"),
        "connected": instance.is_connected(),
        "chunks": chunks,
    }
```

- [ ] **Step 2: Verify endpoint returns chunks**

```bash
uv run python3 -c "
import httpx
r = httpx.get('http://127.0.0.1:8222/connectors', timeout=5)
for c in r.json().get('connectors', [])[:5]:
    print(f'{c[\"connector_id\"]}: connected={c[\"connected\"]}, chunks={c.get(\"chunks\", \"?\")}')
"
```

- [ ] **Step 3: Lint + commit**

```bash
uv run ruff check src/openjarvis/server/connectors_router.py
git add src/openjarvis/server/connectors_router.py
git commit -m "feat: include chunk counts in connector list API response"
```

---

### Task 2: Rewrite Channels tab as data sources view

**Files:**
- Modify: `frontend/src/pages/AgentsPage.tsx`
- Modify: `frontend/src/lib/connectors-api.ts`

Replace the existing `ChannelsTab` (messaging channels) with a new `ChannelsTab` (data sources).

- [ ] **Step 1: Update ConnectorInfo type in connectors-api.ts to include chunks**

In `frontend/src/lib/connectors-api.ts`, find the `ConnectorInfo` type (or wherever it's defined) and add `chunks`:

If there's an interface in `types/connectors.ts`:
```typescript
export interface ConnectorInfo {
  connector_id: string;
  display_name: string;
  auth_type: 'oauth' | 'local' | 'bridge' | 'filesystem';
  connected: boolean;
  auth_url?: string;
  mcp_tools?: string[];
  chunks?: number;  // ADD THIS
}
```

- [ ] **Step 2: Replace the ChannelsTab component**

In `AgentsPage.tsx`, find the existing `AVAILABLE_CHANNELS` array and `ChannelsTab` component (around lines 1000-1170). Replace the entire block with a new `ChannelsTab` that shows data sources:

```typescript
import { SOURCE_CATALOG, ConnectorMeta, ConnectRequest } from '../types/connectors';
import { listConnectors, connectSource } from '../lib/connectors-api';

function ChannelsTab({ agentId }: { agentId: string }) {
  const [connectors, setConnectors] = useState<
    Array<{ connector_id: string; display_name: string; connected: boolean; chunks: number }>
  >([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const loadConnectors = useCallback(() => {
    listConnectors()
      .then((list) =>
        setConnectors(
          list.map((c) => ({
            connector_id: c.connector_id,
            display_name: c.display_name,
            connected: c.connected,
            chunks: (c as any).chunks || 0,
          })),
        ),
      )
      .catch(() => {});
  }, []);

  useEffect(() => { loadConnectors(); }, [loadConnectors]);

  const handleConnect = async (id: string, req: ConnectRequest) => {
    setLoading(true);
    try {
      await connectSource(id, req);
      setExpandedId(null);
      loadConnectors();
    } catch {
      // error handling
    } finally {
      setLoading(false);
    }
  };

  const connected = connectors.filter((c) => c.connected);
  const notConnected = connectors.filter((c) => !c.connected);

  // Merge with SOURCE_CATALOG for icons/descriptions
  const getMeta = (id: string) =>
    SOURCE_CATALOG.find((s) => s.connector_id === id);

  const iconMap: Record<string, string> = {
    gmail: '✉️', gmail_imap: '✉️', slack: '#',
    imessage: '💬', gdrive: '📁', notion: '📄',
    obsidian: '📁', granola: '🎙️', gcalendar: '📅',
    gcontacts: '📇', outlook: '✉️', apple_notes: '🍎',
    dropbox: '📦', whatsapp: '📱',
  };

  return (
    <div style={{ padding: 16 }}>
      <div style={{
        color: 'var(--color-text-secondary)',
        fontSize: 12, marginBottom: 12,
      }}>
        Data sources your agent can search
      </div>

      {/* Connected sources grid */}
      {connected.length > 0 && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 8, marginBottom: 12,
        }}>
          {connected.map((c) => (
            <div
              key={c.connector_id}
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid #2a5a3a',
                borderRadius: 6, padding: '10px 12px',
                display: 'flex', alignItems: 'center', gap: 8,
              }}
            >
              <span>{iconMap[c.connector_id] || '🔗'}</span>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 12, fontWeight: 500 }}>
                  {c.display_name}
                </div>
                <div style={{ fontSize: 10, color: '#4ade80' }}>
                  {c.chunks.toLocaleString()} chunks
                </div>
              </div>
              <span style={{ color: '#4ade80', fontSize: 12 }}>✓</span>
            </div>
          ))}
        </div>
      )}

      {/* Not connected grid */}
      {notConnected.length > 0 && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 8,
        }}>
          {notConnected.map((c) => {
            const meta = getMeta(c.connector_id);
            const isExpanded = expandedId === c.connector_id;

            return (
              <div
                key={c.connector_id}
                style={{
                  background: 'var(--color-bg-secondary)',
                  border: '1px dashed var(--color-border)',
                  borderRadius: 6, overflow: 'hidden',
                  opacity: isExpanded ? 1 : 0.6,
                  gridColumn: isExpanded ? '1 / -1' : undefined,
                }}
              >
                <div
                  style={{
                    padding: '10px 12px', display: 'flex',
                    alignItems: 'center', gap: 8,
                    cursor: 'pointer',
                  }}
                  onClick={() =>
                    setExpandedId(isExpanded ? null : c.connector_id)
                  }
                >
                  <span>{iconMap[c.connector_id] || '🔗'}</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 12, fontWeight: 500,
                      color: 'var(--color-text-secondary)' }}>
                      {c.display_name}
                    </div>
                    <div style={{ fontSize: 10,
                      color: 'var(--color-text-secondary)' }}>
                      Not connected
                    </div>
                  </div>
                  <span style={{
                    color: '#7c3aed', fontSize: 11, fontWeight: 500,
                  }}>
                    {isExpanded ? '✕ Close' : '+ Add'}
                  </span>
                </div>

                {/* Inline setup panel */}
                {isExpanded && meta?.steps && (
                  <div style={{
                    borderTop: '1px solid var(--color-border)',
                    padding: 12,
                  }}>
                    {meta.steps.map((step, i) => (
                      <div
                        key={i}
                        style={{
                          background: 'var(--color-bg)',
                          border: '1px solid var(--color-border)',
                          borderRadius: 6, padding: 10,
                          marginBottom: 8,
                        }}
                      >
                        <div style={{
                          color: '#7c3aed', fontSize: 10,
                          fontWeight: 600, marginBottom: 3,
                        }}>
                          STEP {i + 1}
                        </div>
                        <div style={{
                          fontSize: 12, marginBottom: step.url ? 4 : 0,
                        }}>
                          {step.label}
                        </div>
                        {step.url && (
                          <a
                            href={step.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{
                              color: '#60a5fa', fontSize: 11,
                              textDecoration: 'underline',
                            }}
                          >
                            {step.urlLabel || 'Open'} →
                          </a>
                        )}
                      </div>
                    ))}
                    {meta.inputFields && (
                      <InlineConnectForm
                        fields={meta.inputFields}
                        loading={loading}
                        onSubmit={(req) =>
                          handleConnect(c.connector_id, req)
                        }
                      />
                    )}
                    <div style={{
                      fontSize: 10, color: 'var(--color-text-secondary)',
                      textAlign: 'center', marginTop: 8,
                    }}>
                      🔒 Read-only access · No data leaves your device
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function InlineConnectForm({
  fields,
  loading,
  onSubmit,
}: {
  fields: Array<{ name: string; placeholder: string; type?: string }>;
  loading: boolean;
  onSubmit: (req: ConnectRequest) => void;
}) {
  const [inputs, setInputs] = useState<Record<string, string>>({});

  const update = (name: string, value: string) =>
    setInputs((p) => ({ ...p, [name]: value }));

  const allFilled = fields.every((f) => inputs[f.name]?.trim());

  const submit = () => {
    const req: ConnectRequest = {};
    for (const f of fields) {
      if (f.name === 'email') req.email = inputs.email;
      else if (f.name === 'password') req.password = inputs.password;
      else if (f.name === 'token') req.token = inputs.token;
      else if (f.name === 'path') req.path = inputs.path;
    }
    if (req.email && req.password) {
      req.token = `${req.email}:${req.password}`;
      req.code = req.token;
    }
    if (req.token && !req.code) req.code = req.token;
    onSubmit(req);
  };

  return (
    <div>
      {fields.map((f) => (
        <input
          key={f.name}
          value={inputs[f.name] || ''}
          onChange={(e) => update(f.name, e.target.value)}
          placeholder={f.placeholder}
          type={f.type || 'text'}
          style={{
            width: '100%', padding: '7px 10px',
            background: 'var(--color-bg)',
            border: '1px solid var(--color-border)',
            borderRadius: 4, color: 'var(--color-text)',
            fontSize: 12, marginBottom: 6,
            boxSizing: 'border-box',
          }}
        />
      ))}
      <button
        onClick={submit}
        disabled={loading || !allFilled}
        style={{
          width: '100%', padding: 8,
          background: loading || !allFilled ? '#444' : '#7c3aed',
          color: 'white', border: 'none',
          borderRadius: 6, fontSize: 12, cursor: 'pointer',
        }}
      >
        {loading ? 'Connecting...' : 'Connect'}
      </button>
    </div>
  );
}
```

- [ ] **Step 3: Update DETAIL_TABS to rename and add Messaging**

Find `DETAIL_TABS` (line ~1553). Update to:

```typescript
const DETAIL_TABS = [
  { id: 'overview', label: 'Overview', icon: Activity },
  { id: 'interact', label: 'Interact', icon: MessageSquare },
  { id: 'channels', label: 'Channels', icon: Database },
  { id: 'messaging', label: 'Messaging', icon: Wifi },
  { id: 'tasks', label: 'Tasks', icon: ListTodo },
  { id: 'memory', label: 'Memory', icon: Brain },
  { id: 'learning', label: 'Learning', icon: Settings },
  { id: 'logs', label: 'Logs', icon: FileText },
] as const;
```

Add `Database` to lucide-react imports. Update detailTab type:

```typescript
const [detailTab, setDetailTab] = useState<
  'overview' | 'interact' | 'channels' | 'messaging' | 'tasks' | 'memory' | 'learning' | 'logs'
>('overview');
```

- [ ] **Step 4: Add MessagingTab component and wire both tabs**

Add the `MessagingTab` component (reuses the old `AVAILABLE_CHANNELS` data but with clear UX):

```typescript
const MESSAGING_CHANNELS = [
  {
    type: 'imessage', name: 'iMessage', icon: '💬',
    description: 'Text from your iPhone, iPad, or Mac',
    activeTemplate: (id: string) => `Text ${id} from your iPhone`,
    setupLabel: 'Phone number or email for the agent to use',
    placeholder: '+15551234567',
  },
  {
    type: 'slack', name: 'Slack', icon: '#',
    description: 'Message from any Slack workspace',
    activeTemplate: (id: string) => `DM @jarvis in ${id}`,
    setupLabel: 'Slack bot token (xoxb-...)',
    placeholder: 'xoxb-...',
  },
  {
    type: 'whatsapp', name: 'WhatsApp', icon: '📱',
    description: 'Message via WhatsApp',
    activeTemplate: (id: string) => `Message ${id} on WhatsApp`,
    setupLabel: 'WhatsApp access token',
    placeholder: 'Access token',
  },
  {
    type: 'twilio', name: 'SMS (Twilio)', icon: '📨',
    description: 'Text from any phone via Twilio',
    activeTemplate: (id: string) => `Text ${id} from any phone`,
    setupLabel: 'Twilio phone number',
    placeholder: '+15551234567',
  },
];

function MessagingTab({ agentId }: { agentId: string }) {
  const [bindings, setBindings] = useState<ChannelBinding[]>([]);
  const [setupType, setSetupType] = useState<string | null>(null);
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(false);

  const loadBindings = useCallback(() => {
    fetchAgentChannels(agentId).then(setBindings).catch(() => setBindings([]));
  }, [agentId]);

  useEffect(() => { loadBindings(); }, [loadBindings]);

  const handleSetup = async (channelType: string) => {
    if (!inputValue.trim()) return;
    setLoading(true);
    try {
      await bindAgentChannel(agentId, channelType, {
        identifier: inputValue.trim(),
      });
      setSetupType(null);
      setInputValue('');
      loadBindings();
    } catch { /* */ } finally { setLoading(false); }
  };

  const handleRemove = async (bindingId: string) => {
    try {
      await unbindAgentChannel(agentId, bindingId);
      loadBindings();
    } catch { /* */ }
  };

  return (
    <div style={{ padding: 16 }}>
      <div style={{
        color: 'var(--color-text-secondary)',
        fontSize: 12, marginBottom: 12,
      }}>
        Talk to your agent from your phone or other platforms
      </div>

      {MESSAGING_CHANNELS.map((ch) => {
        const binding = bindings.find((b) => b.channel_type === ch.type);
        const identifier = binding?.config?.identifier as string || binding?.session_id || '';
        const isSetup = setupType === ch.type;

        return (
          <div
            key={ch.type}
            style={{
              background: 'var(--color-bg-secondary)',
              border: binding
                ? '1px solid #2a5a3a'
                : '1px dashed var(--color-border)',
              borderRadius: 8, marginBottom: 8,
              opacity: binding ? 1 : 0.6,
              overflow: 'hidden',
            }}
          >
            <div style={{
              display: 'flex', alignItems: 'center',
              padding: '12px 14px',
            }}>
              <span style={{ fontSize: 16, marginRight: 10 }}>{ch.icon}</span>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{ch.name}</div>
                <div style={{ fontSize: 11,
                  color: binding ? '#4ade80' : 'var(--color-text-secondary)',
                }}>
                  {binding
                    ? ch.activeTemplate(identifier)
                    : 'Not set up'}
                </div>
              </div>
              {binding ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{
                    background: '#2a5a3a', color: '#4ade80',
                    padding: '2px 8px', borderRadius: 10,
                    fontSize: 10,
                  }}>Active</span>
                  <button
                    onClick={() => handleRemove(binding.id)}
                    style={{
                      fontSize: 10, padding: '2px 8px',
                      background: 'transparent',
                      color: 'var(--color-text-secondary)',
                      border: '1px solid var(--color-border)',
                      borderRadius: 4, cursor: 'pointer',
                    }}
                  >Remove</button>
                </div>
              ) : (
                <button
                  onClick={() => {
                    setSetupType(isSetup ? null : ch.type);
                    setInputValue('');
                  }}
                  style={{
                    fontSize: 10, padding: '3px 12px',
                    background: '#7c3aed', color: 'white',
                    border: 'none', borderRadius: 5,
                    cursor: 'pointer',
                  }}
                >
                  {isSetup ? 'Cancel' : 'Set Up'}
                </button>
              )}
            </div>

            {isSetup && (
              <div style={{
                borderTop: '1px solid var(--color-border)',
                padding: '10px 14px',
                background: 'var(--color-bg)',
              }}>
                <div style={{
                  fontSize: 11, marginBottom: 6,
                  color: 'var(--color-text-secondary)',
                }}>{ch.setupLabel}</div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <input
                    value={inputValue}
                    onChange={(e) => setInputValue(e.target.value)}
                    placeholder={ch.placeholder}
                    style={{
                      flex: 1, padding: '6px 10px',
                      background: 'var(--color-bg-secondary)',
                      border: '1px solid var(--color-border)',
                      borderRadius: 4, color: 'var(--color-text)',
                      fontSize: 12,
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleSetup(ch.type);
                    }}
                  />
                  <button
                    onClick={() => handleSetup(ch.type)}
                    disabled={loading || !inputValue.trim()}
                    style={{
                      fontSize: 11, padding: '6px 14px',
                      background: '#7c3aed', color: 'white',
                      border: 'none', borderRadius: 4,
                      cursor: 'pointer',
                      opacity: loading || !inputValue.trim() ? 0.5 : 1,
                    }}
                  >
                    {loading ? '...' : 'Connect'}
                  </button>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
```

Wire both tabs in the content rendering section:

```typescript
{detailTab === 'channels' && (
  <ChannelsTab agentId={selectedAgent.id} />
)}
{detailTab === 'messaging' && (
  <MessagingTab agentId={selectedAgent.id} />
)}
```

- [ ] **Step 5: Add required imports**

At the top of `AgentsPage.tsx`:

```typescript
import { Database } from 'lucide-react';
import { SOURCE_CATALOG } from '../types/connectors';
import type { ConnectRequest } from '../types/connectors';
import { listConnectors, connectSource } from '../lib/connectors-api';
```

- [ ] **Step 6: TypeScript check + build**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
cd frontend && npm run build 2>&1 | tail -10
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/AgentsPage.tsx frontend/src/lib/connectors-api.ts frontend/src/types/connectors.ts
git commit -m "feat: replace Channels tab with data sources + add Messaging tab"
```

---

### Task 3: E2E test both tabs

**Files:** None (manual testing)

- [ ] **Step 1: Restart server to pick up new static files**

```bash
# Kill existing server, rebuild frontend, restart
kill $(pgrep -f "jarvis serve") 2>/dev/null
cd frontend && npm run build
uv run jarvis serve --port 8222 --model qwen3.5:9b &
```

- [ ] **Step 2: Test Channels tab**

1. Open http://127.0.0.1:8222 → Agents → open agent
2. Click "Channels" tab
3. Verify connected sources show with green border + chunk counts
4. Verify unconnected sources show with dashed border + "+ Add"
5. Click "+ Add" on an unconnected source → verify step-by-step instructions appear inline

- [ ] **Step 3: Test Messaging tab**

1. Click "Messaging" tab
2. Verify active channels show with "Text +1... from your iPhone" instructions
3. Verify inactive channels show "Set Up" button
4. Click "Set Up" → verify input field appears with clear label

- [ ] **Step 4: Push**

```bash
git push origin feat/deep-research-setup
```
