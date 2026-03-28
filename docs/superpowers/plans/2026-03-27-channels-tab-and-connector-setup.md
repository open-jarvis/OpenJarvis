# Channels Tab + Connector Setup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Channels tab to every agent for bidirectional messaging (iMessage, Slack, WhatsApp, SMS), and build per-connector step-by-step setup guides with one-click OAuth in the setup wizard.

**Architecture:** Sub-project 1 adds a React Channels tab component to AgentsPage.tsx that calls existing backend endpoints (POST/DELETE/GET channel bindings). Sub-project 2 replaces the generic OAuth panel in SourceConnectFlow.tsx with per-connector instruction panels and adds a Google OAuth callback server in Python.

**Tech Stack:** React 19, TypeScript, Tailwind CSS, Python 3.10+, FastAPI, Click

---

## Sub-project 1: Channels Tab

### Task 1: Add Channels tab to agent detail view

**Files:**
- Modify: `frontend/src/pages/AgentsPage.tsx`
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add API functions for channel binding CRUD**

In `frontend/src/lib/api.ts`, add after the existing `fetchAgentChannels` function:

```typescript
export async function bindAgentChannel(
  agentId: string,
  channelType: string,
  config?: Record<string, unknown>,
): Promise<ChannelBinding> {
  const res = await fetch(
    `${getBase()}/v1/managed-agents/${agentId}/channels`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        channel_type: channelType,
        config: config || {},
        routing_mode: 'dedicated',
      }),
    },
  );
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function unbindAgentChannel(
  agentId: string,
  bindingId: string,
): Promise<void> {
  const res = await fetch(
    `${getBase()}/v1/managed-agents/${agentId}/channels/${bindingId}`,
    { method: 'DELETE' },
  );
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}
```

- [ ] **Step 2: Add 'channels' to DETAIL_TABS in AgentsPage.tsx**

Find the `DETAIL_TABS` array (line ~1315) and add a channels entry. Also find the `Wifi` icon import from `lucide-react` at the top of the file:

Add to imports:
```typescript
import { Wifi } from 'lucide-react';
```

Update `DETAIL_TABS`:
```typescript
const DETAIL_TABS = [
  { id: 'overview', label: 'Overview', icon: Activity },
  { id: 'interact', label: 'Interact', icon: MessageSquare },
  { id: 'channels', label: 'Channels', icon: Wifi },
  { id: 'tasks', label: 'Tasks', icon: ListTodo },
  { id: 'memory', label: 'Memory', icon: Brain },
  { id: 'learning', label: 'Learning', icon: Settings },
  { id: 'logs', label: 'Logs', icon: FileText },
] as const;
```

Update the `detailTab` state type to include `'channels'`:
```typescript
const [detailTab, setDetailTab] = useState<
  'overview' | 'interact' | 'channels' | 'tasks' | 'memory' | 'learning' | 'logs'
>('overview');
```

- [ ] **Step 3: Add ChannelsTab component**

Add this component inside `AgentsPage.tsx` (before the main `AgentsPage` component). This is a self-contained component that manages its own state:

```typescript
const AVAILABLE_CHANNELS = [
  {
    type: 'imessage',
    name: 'iMessage',
    icon: '💬',
    description: 'Text from your iPhone, iPad, or Mac',
    connectLabel: 'Phone number or contact to monitor',
    placeholder: '+15551234567',
  },
  {
    type: 'slack',
    name: 'Slack',
    icon: '#',
    description: 'Message from any Slack workspace',
    connectLabel: 'Slack bot token (xoxb-...)',
    placeholder: 'xoxb-...',
  },
  {
    type: 'whatsapp',
    name: 'WhatsApp',
    icon: '📱',
    description: 'Message via WhatsApp',
    connectLabel: 'WhatsApp access token',
    placeholder: 'Access token',
  },
  {
    type: 'twilio',
    name: 'SMS (Twilio)',
    icon: '📨',
    description: 'Text from any phone via Twilio',
    connectLabel: 'Twilio phone number',
    placeholder: '+15551234567',
  },
];

function ChannelsTab({ agentId }: { agentId: string }) {
  const [bindings, setBindings] = useState<ChannelBinding[]>([]);
  const [connectingType, setConnectingType] = useState<string | null>(null);
  const [inputValue, setInputValue] = useState('');
  const [loading, setLoading] = useState(false);

  const loadBindings = useCallback(() => {
    fetchAgentChannels(agentId).then(setBindings).catch(() => setBindings([]));
  }, [agentId]);

  useEffect(() => { loadBindings(); }, [loadBindings]);

  const handleConnect = async (channelType: string) => {
    if (!inputValue.trim()) return;
    setLoading(true);
    try {
      await bindAgentChannel(agentId, channelType, {
        identifier: inputValue.trim(),
      });
      setConnectingType(null);
      setInputValue('');
      loadBindings();
    } catch {
      // Could show error toast
    } finally {
      setLoading(false);
    }
  };

  const handleDisconnect = async (bindingId: string) => {
    try {
      await unbindAgentChannel(agentId, bindingId);
      loadBindings();
    } catch {
      // Could show error toast
    }
  };

  const boundTypes = new Set(bindings.map((b) => b.channel_type));

  return (
    <div style={{ padding: 16 }}>
      <div style={{
        display: 'flex', alignItems: 'center',
        justifyContent: 'space-between', marginBottom: 16,
      }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>
          Talk to this agent from
        </h3>
      </div>

      {AVAILABLE_CHANNELS.map((ch) => {
        const binding = bindings.find((b) => b.channel_type === ch.type);
        const isConnecting = connectingType === ch.type;

        return (
          <div
            key={ch.type}
            style={{
              background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)',
              borderRadius: 8,
              marginBottom: 10,
              opacity: binding ? 1 : 0.7,
              overflow: 'hidden',
            }}
          >
            <div style={{
              display: 'flex', alignItems: 'center',
              padding: '14px 16px',
            }}>
              <div style={{
                width: 36, height: 36, borderRadius: 8,
                display: 'flex', alignItems: 'center',
                justifyContent: 'center', marginRight: 12,
                fontSize: 18, background: 'var(--color-bg)',
              }}>
                {ch.icon}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 14 }}>{ch.name}</div>
                <div style={{
                  color: 'var(--color-text-secondary)',
                  fontSize: 12,
                }}>
                  {ch.description}
                </div>
              </div>
              {binding ? (
                <span style={{
                  background: '#2a5a3a', color: '#4ade80',
                  padding: '3px 10px', borderRadius: 12,
                  fontSize: 11, fontWeight: 500,
                }}>
                  Active
                </span>
              ) : (
                <button
                  onClick={() => {
                    setConnectingType(isConnecting ? null : ch.type);
                    setInputValue('');
                  }}
                  style={{
                    fontSize: 11, padding: '4px 14px',
                    background: '#7c3aed', color: 'white',
                    border: 'none', borderRadius: 6,
                    cursor: 'pointer',
                  }}
                >
                  {isConnecting ? 'Cancel' : 'Connect'}
                </button>
              )}
            </div>

            {/* Expanded: connected details */}
            {binding && (
              <div style={{
                borderTop: '1px solid var(--color-border)',
                padding: '12px 16px',
                background: 'var(--color-bg)',
              }}>
                <div style={{
                  fontSize: 12,
                  color: 'var(--color-text-secondary)',
                  marginBottom: 8,
                }}>
                  {binding.config?.identifier
                    ? `Monitoring: ${binding.config.identifier}`
                    : `Session: ${binding.session_id}`}
                </div>
                <button
                  onClick={() => handleDisconnect(binding.id)}
                  style={{
                    fontSize: 11, padding: '4px 12px',
                    background: 'var(--color-bg-secondary)',
                    color: 'var(--color-text-secondary)',
                    border: '1px solid var(--color-border)',
                    borderRadius: 4, cursor: 'pointer',
                  }}
                >
                  Disconnect
                </button>
              </div>
            )}

            {/* Expanded: connect form */}
            {isConnecting && (
              <div style={{
                borderTop: '1px solid var(--color-border)',
                padding: '12px 16px',
                background: 'var(--color-bg)',
              }}>
                <div style={{
                  fontSize: 12,
                  color: 'var(--color-text-secondary)',
                  marginBottom: 8,
                }}>
                  {ch.connectLabel}
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
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
                      if (e.key === 'Enter') handleConnect(ch.type);
                    }}
                  />
                  <button
                    onClick={() => handleConnect(ch.type)}
                    disabled={loading || !inputValue.trim()}
                    style={{
                      fontSize: 11, padding: '6px 14px',
                      background: '#7c3aed', color: 'white',
                      border: 'none', borderRadius: 4,
                      cursor: 'pointer',
                      opacity: loading || !inputValue.trim() ? 0.5 : 1,
                    }}
                  >
                    {loading ? 'Connecting...' : 'Connect'}
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

- [ ] **Step 4: Wire the tab content rendering**

In the tab content rendering section (around line 1410-1525), add between the existing tab conditionals:

```typescript
{detailTab === 'channels' && (
  <ChannelsTab agentId={selectedAgent.id} />
)}
```

- [ ] **Step 5: Add missing imports**

At the top of `AgentsPage.tsx`, ensure these are imported from `api.ts`:

```typescript
import {
  // ... existing imports
  bindAgentChannel,
  unbindAgentChannel,
} from '../lib/api';
```

- [ ] **Step 6: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: No errors.

- [ ] **Step 7: Build frontend**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

Expected: Build succeeds.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/AgentsPage.tsx frontend/src/lib/api.ts
git commit -m "feat: add Channels tab to agent detail view with connect/disconnect UI"
```

---

### Task 2: Start iMessage daemon when binding iMessage channel

**Files:**
- Modify: `src/openjarvis/server/agent_manager_routes.py`

The backend `bind_channel` endpoint currently just creates a DB record. For iMessage, it also needs to start the daemon. For other channels, it just stores the config.

- [ ] **Step 1: Modify the bind_channel endpoint to start iMessage daemon**

Find the `bind_channel` endpoint (around line 956). Replace it with:

```python
@agents_router.post("/{agent_id}/channels")
async def bind_channel(agent_id: str, req: BindChannelRequest):
    if not manager.get_agent(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    binding = manager.bind_channel(
        agent_id,
        channel_type=req.channel_type,
        config=req.config,
        routing_mode=req.routing_mode,
    )

    # Start iMessage daemon if binding iMessage
    if req.channel_type == "imessage":
        identifier = (req.config or {}).get("identifier", "")
        if identifier:
            try:
                from openjarvis.channels.imessage_daemon import (
                    is_running,
                    run_daemon,
                )

                if not is_running():
                    import threading

                    engine = getattr(request.app.state, "engine", None)
                    if engine:
                        from openjarvis.server.agent_manager_routes import (
                            _build_deep_research_tools,
                        )

                        tools = _build_deep_research_tools(
                            engine=engine, model="",
                        )
                        if tools:
                            from openjarvis.agents.deep_research import (
                                DeepResearchAgent,
                            )

                            agent = DeepResearchAgent(
                                engine=engine,
                                model=getattr(engine, "_model", ""),
                                tools=tools,
                            )

                            def handler(text: str) -> str:
                                result = agent.run(text)
                                return result.content or "No results."

                            t = threading.Thread(
                                target=run_daemon,
                                kwargs={
                                    "chat_identifier": identifier,
                                    "handler": handler,
                                },
                                daemon=True,
                            )
                            t.start()
            except Exception as exc:
                logger.warning(
                    "Failed to start iMessage daemon: %s", exc,
                )

    return binding
```

Note: This requires adding `request: Request` to the function signature:

```python
@agents_router.post("/{agent_id}/channels")
async def bind_channel(
    agent_id: str, req: BindChannelRequest, request: Request,
):
```

- [ ] **Step 2: Stop daemon on unbind**

Find the `unbind_channel` endpoint (around line 967). Add daemon stop before deleting:

```python
@agents_router.delete("/{agent_id}/channels/{binding_id}")
async def unbind_channel(agent_id: str, binding_id: str):
    # Stop iMessage daemon if applicable
    binding = manager._get_binding(binding_id)
    if binding and binding.get("channel_type") == "imessage":
        try:
            from openjarvis.channels.imessage_daemon import stop_daemon
            stop_daemon()
        except Exception:
            pass
    manager.unbind_channel(binding_id)
    return {"status": "unbound"}
```

- [ ] **Step 3: Commit**

```bash
git add src/openjarvis/server/agent_manager_routes.py
git commit -m "feat: start/stop iMessage daemon on channel bind/unbind"
```

---

### Task 3: E2E test — Channels tab in browser

**Files:** None (manual testing)

- [ ] **Step 1: Start server and open browser**

```bash
uv run jarvis serve --host 127.0.0.1 --port 8222
```

Open `http://127.0.0.1:8222`.

- [ ] **Step 2: Create a DeepResearch agent and check Channels tab**

1. Go to Agents tab → create from "Personal Deep Research" template
2. Open the agent → click "Channels" tab
3. Verify 4 channels listed: iMessage, Slack, WhatsApp, SMS
4. All should show "Connect" buttons

- [ ] **Step 3: Connect iMessage channel**

1. Click "Connect" on iMessage
2. Enter a phone number
3. Click "Connect"
4. Verify it shows "Active" with the phone number

- [ ] **Step 4: Disconnect**

1. Click "Disconnect" on the iMessage binding
2. Verify it returns to "Connect" state

- [ ] **Step 5: Push**

```bash
git push origin main
```

---

## Sub-project 2: Connector Setup Instructions

### Task 4: Add per-connector instruction data

**Files:**
- Modify: `frontend/src/types/connectors.ts`

- [ ] **Step 1: Extend ConnectorMeta with setup instructions**

In `frontend/src/types/connectors.ts`, add a `steps` field to the SOURCE_CATALOG entries. Each step has a `label`, optional `url` (opens in browser), and optional `inputField`:

```typescript
export interface SetupStep {
  label: string;
  url?: string;
  urlLabel?: string;
}

export interface ConnectorMeta {
  connector_id: string;
  display_name: string;
  auth_type: 'oauth' | 'local' | 'bridge' | 'filesystem';
  category: string;
  icon: string;
  color: string;
  description: string;
  steps?: SetupStep[];
  inputFields?: Array<{
    name: string;
    placeholder: string;
    type?: 'text' | 'password';
  }>;
}
```

- [ ] **Step 2: Add per-connector steps to SOURCE_CATALOG**

Update the existing SOURCE_CATALOG entries with setup instructions:

```typescript
export const SOURCE_CATALOG: ConnectorMeta[] = [
  {
    connector_id: 'gmail_imap',
    display_name: 'Gmail (IMAP)',
    auth_type: 'oauth',
    category: 'communication',
    icon: 'Mail',
    color: 'text-red-400',
    description: 'Email via app password',
    steps: [
      {
        label: 'Enable 2-Factor Authentication on your Google account',
        url: 'https://myaccount.google.com/signinoptions/two-step-verification',
        urlLabel: 'Open Google Security',
      },
      {
        label: 'Generate an App Password for "Mail"',
        url: 'https://myaccount.google.com/apppasswords',
        urlLabel: 'Open App Passwords',
      },
      { label: 'Paste your credentials below' },
    ],
    inputFields: [
      { name: 'email', placeholder: 'Email address', type: 'text' },
      { name: 'password', placeholder: 'App password (xxxx xxxx xxxx xxxx)', type: 'password' },
    ],
  },
  {
    connector_id: 'slack',
    display_name: 'Slack',
    auth_type: 'oauth',
    category: 'communication',
    icon: 'Hash',
    color: 'text-purple-400',
    description: 'Channel messages and threads',
    steps: [
      {
        label: 'Go to your Slack App settings and copy the Bot User OAuth Token',
        url: 'https://api.slack.com/apps',
        urlLabel: 'Open Slack Apps',
      },
      { label: 'Paste the bot token below (starts with xoxb-)' },
    ],
    inputFields: [
      { name: 'token', placeholder: 'xoxb-...', type: 'password' },
    ],
  },
  {
    connector_id: 'notion',
    display_name: 'Notion',
    auth_type: 'oauth',
    category: 'documents',
    icon: 'FileText',
    color: 'text-gray-300',
    description: 'Pages and databases',
    steps: [
      {
        label: 'Create an internal integration and copy the secret',
        url: 'https://www.notion.so/profile/integrations',
        urlLabel: 'Open Notion Integrations',
      },
      { label: 'Paste the integration token below (starts with ntn_)' },
      { label: 'Then share pages with your integration: Page → ... → Connections → Add' },
    ],
    inputFields: [
      { name: 'token', placeholder: 'ntn_...', type: 'password' },
    ],
  },
  {
    connector_id: 'granola',
    display_name: 'Granola',
    auth_type: 'oauth',
    category: 'documents',
    icon: 'Mic',
    color: 'text-amber-400',
    description: 'AI meeting notes',
    steps: [
      { label: 'Open the Granola desktop app → Settings → API' },
      { label: 'Copy your API key and paste below' },
    ],
    inputFields: [
      { name: 'token', placeholder: 'grn_...', type: 'password' },
    ],
  },
  {
    connector_id: 'gmail',
    display_name: 'Gmail',
    auth_type: 'oauth',
    category: 'communication',
    icon: 'Mail',
    color: 'text-red-400',
    description: 'Email messages and threads (OAuth)',
    steps: [
      { label: 'Click "Authorize" to open Google consent screen' },
      { label: 'Grant read-only access to your Gmail' },
    ],
  },
  {
    connector_id: 'imessage',
    display_name: 'iMessage',
    auth_type: 'local',
    category: 'communication',
    icon: 'MessageSquare',
    color: 'text-green-400',
    description: 'macOS Messages history',
    steps: [
      { label: 'Open System Settings → Privacy & Security → Full Disk Access' },
      { label: 'Enable access for your terminal app or OpenJarvis' },
    ],
  },
  {
    connector_id: 'obsidian',
    display_name: 'Obsidian',
    auth_type: 'filesystem',
    category: 'documents',
    icon: 'FolderOpen',
    color: 'text-purple-300',
    description: 'Markdown vault',
    steps: [
      { label: 'Enter the path to your Obsidian vault folder' },
    ],
    inputFields: [
      { name: 'path', placeholder: '/Users/you/Documents/MyVault', type: 'text' },
    ],
  },
  {
    connector_id: 'gdrive',
    display_name: 'Google Drive',
    auth_type: 'oauth',
    category: 'documents',
    icon: 'FolderOpen',
    color: 'text-blue-400',
    description: 'Docs, Sheets, and files',
    steps: [
      { label: 'Click "Authorize" to grant read-only access to Google Drive' },
    ],
  },
  {
    connector_id: 'gcalendar',
    display_name: 'Calendar',
    auth_type: 'oauth',
    category: 'pim',
    icon: 'Calendar',
    color: 'text-blue-400',
    description: 'Events and meetings',
    steps: [
      { label: 'Click "Authorize" to grant read-only access to Google Calendar' },
    ],
  },
  {
    connector_id: 'gcontacts',
    display_name: 'Contacts',
    auth_type: 'oauth',
    category: 'pim',
    icon: 'Users',
    color: 'text-blue-400',
    description: 'People and contact info',
    steps: [
      { label: 'Click "Authorize" to grant read-only access to Google Contacts' },
    ],
  },
];
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types/connectors.ts
git commit -m "feat: add per-connector setup instructions and input fields to SOURCE_CATALOG"
```

---

### Task 5: Build StepByStepPanel component for SourceConnectFlow

**Files:**
- Modify: `frontend/src/components/setup/SourceConnectFlow.tsx`

- [ ] **Step 1: Add the StepByStepPanel component**

Add this component inside `SourceConnectFlow.tsx`, before the main `SourceConnectFlow` component. It replaces the generic OAuth panel for connectors that have `steps` defined:

```typescript
function StepByStepPanel({
  connector,
  onConnect,
  onSkip,
  isConnecting,
}: {
  connector: ConnectorMeta;
  onConnect: (req: ConnectRequest) => void;
  onSkip: () => void;
  isConnecting: boolean;
}) {
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const steps = connector.steps || [];
  const fields = connector.inputFields || [];

  const updateInput = (name: string, value: string) => {
    setInputs((prev) => ({ ...prev, [name]: value }));
  };

  const handleSubmit = () => {
    const req: ConnectRequest = {};
    for (const field of fields) {
      if (field.name === 'email') req.email = inputs.email;
      else if (field.name === 'password') req.password = inputs.password;
      else if (field.name === 'token') req.token = inputs.token;
      else if (field.name === 'path') req.path = inputs.path;
    }
    // For email+password connectors, also set token as email:password
    if (req.email && req.password) {
      req.token = `${req.email}:${req.password}`;
      req.code = req.token;
    }
    if (req.token && !req.code) {
      req.code = req.token;
    }
    onConnect(req);
  };

  const allFilled = fields.every((f) => inputs[f.name]?.trim());

  return (
    <div style={{ padding: '0 4px' }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        marginBottom: 16,
      }}>
        <span style={{ fontSize: 20 }}>
          {connector.icon === 'Mail' ? '✉️' :
           connector.icon === 'Hash' ? '#️⃣' :
           connector.icon === 'FileText' ? '📄' :
           connector.icon === 'Mic' ? '🎙️' :
           connector.icon === 'FolderOpen' ? '📁' : '🔗'}
        </span>
        <span style={{ fontWeight: 600, fontSize: 15 }}>
          {connector.display_name}
        </span>
      </div>

      {steps.map((step, i) => (
        <div
          key={i}
          style={{
            background: 'var(--color-bg)',
            border: '1px solid var(--color-border)',
            borderRadius: 6,
            padding: 12,
            marginBottom: 10,
          }}
        >
          <div style={{
            color: '#7c3aed', fontSize: 11,
            fontWeight: 600, marginBottom: 4,
          }}>
            STEP {i + 1}
          </div>
          <div style={{
            color: 'var(--color-text)',
            fontSize: 13, marginBottom: step.url ? 6 : 0,
          }}>
            {step.label}
          </div>
          {step.url && (
            <a
              href={step.url}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                color: '#60a5fa', fontSize: 12,
                textDecoration: 'underline',
              }}
            >
              {step.urlLabel || 'Open'} →
            </a>
          )}
        </div>
      ))}

      {fields.length > 0 && (
        <div style={{
          background: 'var(--color-bg)',
          border: '1px solid var(--color-border)',
          borderRadius: 6,
          padding: 12,
          marginBottom: 10,
        }}>
          {fields.map((field) => (
            <input
              key={field.name}
              value={inputs[field.name] || ''}
              onChange={(e) => updateInput(field.name, e.target.value)}
              placeholder={field.placeholder}
              type={field.type || 'text'}
              style={{
                width: '100%',
                padding: '8px 10px',
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
                borderRadius: 4,
                color: 'var(--color-text)',
                fontSize: 13,
                marginBottom: 8,
                boxSizing: 'border-box',
              }}
            />
          ))}
        </div>
      )}

      <div style={{
        fontSize: 11, color: 'var(--color-text-secondary)',
        marginBottom: 12, textAlign: 'center',
      }}>
        🔒 Read-only access · No data leaves your device
      </div>

      <div style={{ display: 'flex', gap: 8 }}>
        <button
          onClick={handleSubmit}
          disabled={isConnecting || (fields.length > 0 && !allFilled)}
          style={{
            flex: 1, padding: 10,
            background: isConnecting || (fields.length > 0 && !allFilled)
              ? '#444' : '#7c3aed',
            color: 'white', border: 'none',
            borderRadius: 6, fontSize: 13,
            cursor: 'pointer',
          }}
        >
          {isConnecting ? 'Connecting...' : `Connect ${connector.display_name}`}
        </button>
        <button
          onClick={onSkip}
          style={{
            padding: '10px 16px',
            background: 'transparent',
            color: 'var(--color-text-secondary)',
            border: '1px solid var(--color-border)',
            borderRadius: 6, fontSize: 13,
            cursor: 'pointer',
          }}
        >
          Skip
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Wire StepByStepPanel into the connect flow**

In the `SourceConnectFlow` component, find where it renders the OAuth/Local/Filesystem panels based on `auth_type`. Modify the rendering logic to check if the connector has `steps` defined, and if so, use `StepByStepPanel` instead of the generic panels:

```typescript
// In the panel rendering section, add before the existing auth_type checks:
const connectorMeta = SOURCE_CATALOG.find(
  (c) => c.connector_id === activeSource.connector_id,
);

// If connector has steps, use StepByStepPanel regardless of auth_type
if (connectorMeta?.steps) {
  return (
    <StepByStepPanel
      connector={connectorMeta}
      onConnect={(req) => handleConnect(activeSource.connector_id, req)}
      onSkip={() => handleSkip(activeIndex)}
      isConnecting={activeSource.state === 'connecting'}
    />
  );
}

// Fallback to existing generic panels for connectors without steps
```

- [ ] **Step 3: Import ConnectorMeta and SOURCE_CATALOG**

Ensure these are imported at the top of `SourceConnectFlow.tsx`:

```typescript
import { ConnectorMeta, SOURCE_CATALOG, ConnectRequest } from '../../types/connectors';
```

- [ ] **Step 4: Verify TypeScript compiles and build**

```bash
cd frontend && npx tsc --noEmit && npm run build 2>&1 | tail -5
```

Expected: No errors, build succeeds.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/setup/SourceConnectFlow.tsx
git commit -m "feat: add StepByStepPanel with per-connector setup instructions"
```

---

### Task 6: E2E test — setup wizard with new connector flow

**Files:** None (manual testing)

- [ ] **Step 1: Open the setup wizard**

Navigate to the setup wizard (or trigger it from the agent creation flow).

- [ ] **Step 2: Test Gmail IMAP connection**

1. Select "Gmail (IMAP)" in source picker
2. Verify 3 numbered steps appear with links to Google settings
3. Verify email + password input fields appear
4. Enter credentials and click Connect
5. Verify connection succeeds

- [ ] **Step 3: Test Notion connection**

1. Select "Notion"
2. Verify steps show link to Notion Integrations page
3. Verify token input field
4. Paste token, click Connect

- [ ] **Step 4: Test Slack connection**

1. Select "Slack"
2. Verify steps show link to Slack Apps page
3. Paste bot token, click Connect

- [ ] **Step 5: Verify ingest dashboard works with connected sources**

After connecting sources, verify the IngestDashboard shows sync progress for each.

- [ ] **Step 6: Push**

```bash
git push origin main
```
