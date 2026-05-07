import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  fetchManagedAgents,
  fetchAgentTasks,
  fetchAgentMessages,
  fetchTemplates,
  createManagedAgent,
  pauseManagedAgent,
  resumeManagedAgent,
  runManagedAgent,
  recoverManagedAgent,
  deleteManagedAgent,
  sendAgentMessage,
  fetchLearningLog,
  triggerLearning,
  fetchAgentTraces,
} from '../../lib/api';
import type { ManagedAgent, AgentTask, AgentMessage, AgentTemplate, LearningLogEntry, AgentTrace } from '../../lib/api';

// ---------------------------------------------------------------------------
// Colors — Catppuccin Mocha
// ---------------------------------------------------------------------------

const C = {
  bg: '#1e1e2e',
  mantle: '#181825',
  surface0: '#313244',
  surface1: '#45475a',
  surface2: '#585b70',
  text: '#cdd6f4',
  subtext1: '#bac2de',
  subtext0: '#a6adc8',
  overlay1: '#7f849c',
  overlay0: '#6c7086',
  accent: '#89b4fa',
  green: '#a6e3a1',
  red: '#f38ba8',
  peach: '#fab387',
  yellow: '#f9e2af',
  border: '#45475a',
};

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

type AgentStatus =
  | 'idle'
  | 'running'
  | 'paused'
  | 'error'
  | 'archived'
  | 'needs_attention'
  | 'budget_exceeded'
  | 'stalled';

const STATUS_COLOR: Record<AgentStatus, string> = {
  idle: C.green,
  running: C.accent,
  paused: C.overlay0,
  error: C.red,
  archived: C.overlay0,
  needs_attention: C.peach,
  budget_exceeded: C.peach,
  stalled: C.yellow,
};

function statusDotColor(s: string): string {
  return STATUS_COLOR[s as AgentStatus] || C.overlay0;
}

function formatRelativeTime(ts?: number | null): string {
  if (!ts) return 'Never';
  const diff = Date.now() - ts * 1000;
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'Just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function formatSchedule(type?: string, value?: string): string {
  if (!type || type === 'manual') return 'Manual';
  if (type === 'cron') return value ? `Cron: ${value}` : 'Cron';
  if (type === 'interval') return value ? `Every ${value}` : 'Interval';
  return type;
}

function formatCost(cost?: number): string {
  if (cost === undefined || cost === null) return '—';
  if (cost < 0.01) return `$${(cost * 100).toFixed(2)}¢`;
  return `$${cost.toFixed(3)}`;
}

// ---------------------------------------------------------------------------
// Launch Wizard
// ---------------------------------------------------------------------------

const AVAILABLE_TOOLS = [
  { id: 'web_search', label: 'Web Search' },
  { id: 'code_interpreter', label: 'Code Interpreter' },
  { id: 'file_read', label: 'File Read' },
  { id: 'shell_exec', label: 'Shell Exec' },
  { id: 'browser', label: 'Browser' },
  { id: 'calculator', label: 'Calculator' },
];

interface WizardState {
  step: 1 | 2 | 3;
  templateId: string;
  name: string;
  scheduleType: string;
  scheduleValue: string;
  selectedTools: string[];
  budget: string;
  learningEnabled: boolean;
}

function LaunchWizard({
  apiUrl,
  templates,
  onClose,
  onLaunched,
}: {
  apiUrl: string;
  templates: AgentTemplate[];
  onClose: () => void;
  onLaunched: () => void;
}) {
  const [wizard, setWizard] = useState<WizardState>({
    step: 1,
    templateId: '',
    name: '',
    scheduleType: 'manual',
    scheduleValue: '',
    selectedTools: [],
    budget: '',
    learningEnabled: false,
  });
  const [launching, setLaunching] = useState(false);
  const [error, setError] = useState('');

  function update(partial: Partial<WizardState>) {
    setWizard((prev) => ({ ...prev, ...partial }));
  }

  function toggleTool(id: string) {
    const next = wizard.selectedTools.includes(id)
      ? wizard.selectedTools.filter((t) => t !== id)
      : [...wizard.selectedTools, id];
    update({ selectedTools: next });
  }

  function selectTemplate(id: string) {
    const tpl = templates.find((t) => t.id === id);
    update({ templateId: id, name: tpl?.name || wizard.name });
  }

  async function handleLaunch() {
    if (!wizard.name.trim()) { setError('Agent name is required.'); return; }
    setLaunching(true);
    setError('');
    try {
      const config: Record<string, unknown> = {
        schedule_type: wizard.scheduleType,
        schedule_value: wizard.scheduleValue || undefined,
        tools: wizard.selectedTools,
        learning_enabled: wizard.learningEnabled,
      };
      if (wizard.budget) config.budget = parseFloat(wizard.budget);
      await createManagedAgent(apiUrl, {
        name: wizard.name,
        template_id: wizard.templateId || undefined,
        config,
      });
      onLaunched();
    } catch {
      setError('Failed to create agent. Please try again.');
    } finally {
      setLaunching(false);
    }
  }

  const overlayStyle: React.CSSProperties = {
    position: 'fixed', inset: 0, zIndex: 50,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    background: 'rgba(0,0,0,0.6)',
  };
  const dialogStyle: React.CSSProperties = {
    width: '100%', maxWidth: 520, margin: '0 16px',
    background: C.bg, border: `1px solid ${C.border}`,
    borderRadius: 12, display: 'flex', flexDirection: 'column',
    maxHeight: '85vh', overflow: 'hidden',
  };
  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '8px 12px', borderRadius: 6,
    background: C.mantle, border: `1px solid ${C.border}`,
    color: C.text, fontSize: 13, outline: 'none',
    boxSizing: 'border-box',
  };
  const selectStyle: React.CSSProperties = {
    ...inputStyle, cursor: 'pointer',
  };

  return (
    <div style={overlayStyle} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div style={dialogStyle}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px 20px', borderBottom: `1px solid ${C.border}` }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ color: C.accent, fontSize: 16 }}>◈</span>
            <span style={{ color: C.text, fontWeight: 600, fontSize: 15 }}>Launch Agent</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {/* Step indicator */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: C.overlay0 }}>
              {([1, 2, 3] as const).map((s) => (
                <span key={s} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{
                    width: 20, height: 20, borderRadius: '50%',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 11, fontWeight: 600,
                    background: wizard.step >= s ? C.accent : C.surface0,
                    color: wizard.step >= s ? C.bg : C.overlay0,
                  }}>
                    {s}
                  </span>
                  {s < 3 && <span style={{ color: C.overlay0 }}>›</span>}
                </span>
              ))}
            </div>
            <button onClick={onClose} style={{ background: 'none', border: 'none', color: C.overlay0, cursor: 'pointer', fontSize: 18, lineHeight: 1, padding: 2 }}>
              ✕
            </button>
          </div>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px' }}>
          {/* Step 1: Template picker */}
          {wizard.step === 1 && (
            <div>
              <p style={{ color: C.subtext0, fontSize: 13, marginBottom: 12 }}>
                Choose a template or start from scratch
              </p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <button
                  onClick={() => update({ templateId: '' })}
                  style={{
                    textAlign: 'left', padding: 12, borderRadius: 8,
                    background: wizard.templateId === '' ? C.accent + '20' : C.surface0,
                    border: `1px solid ${wizard.templateId === '' ? C.accent : C.border}`,
                    cursor: 'pointer',
                  }}
                >
                  <div style={{ color: C.text, fontSize: 13, fontWeight: 500 }}>Custom Agent</div>
                  <div style={{ color: C.overlay0, fontSize: 11, marginTop: 2 }}>Start from scratch with full control</div>
                </button>
                {templates.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => selectTemplate(t.id)}
                    style={{
                      textAlign: 'left', padding: 12, borderRadius: 8,
                      background: wizard.templateId === t.id ? C.accent + '20' : C.surface0,
                      border: `1px solid ${wizard.templateId === t.id ? C.accent : C.border}`,
                      cursor: 'pointer',
                    }}
                  >
                    <div style={{ color: C.text, fontSize: 13, fontWeight: 500 }}>{t.name}</div>
                    {t.description && (
                      <div style={{ color: C.overlay0, fontSize: 11, marginTop: 2 }}>{t.description.slice(0, 80)}</div>
                    )}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Step 2: Config */}
          {wizard.step === 2 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div>
                <label style={{ display: 'block', color: C.subtext0, fontSize: 12, marginBottom: 6, fontWeight: 500 }}>
                  Agent Name *
                </label>
                <input
                  style={inputStyle}
                  type="text"
                  placeholder="e.g. Research Assistant"
                  value={wizard.name}
                  onChange={(e) => update({ name: e.target.value })}
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <label style={{ display: 'block', color: C.subtext0, fontSize: 12, marginBottom: 6, fontWeight: 500 }}>
                    Schedule Type
                  </label>
                  <select
                    style={selectStyle}
                    value={wizard.scheduleType}
                    onChange={(e) => update({ scheduleType: e.target.value })}
                  >
                    <option value="manual">Manual</option>
                    <option value="cron">Cron</option>
                    <option value="interval">Interval</option>
                  </select>
                </div>
                <div>
                  <label style={{ display: 'block', color: C.subtext0, fontSize: 12, marginBottom: 6, fontWeight: 500 }}>
                    Schedule Value
                  </label>
                  <input
                    style={{ ...inputStyle, opacity: wizard.scheduleType === 'manual' ? 0.4 : 1 }}
                    type="text"
                    placeholder={wizard.scheduleType === 'cron' ? '0 * * * *' : wizard.scheduleType === 'interval' ? '1h' : '—'}
                    value={wizard.scheduleValue}
                    onChange={(e) => update({ scheduleValue: e.target.value })}
                    disabled={wizard.scheduleType === 'manual'}
                  />
                </div>
              </div>

              <div>
                <label style={{ display: 'block', color: C.subtext0, fontSize: 12, marginBottom: 6, fontWeight: 500 }}>
                  Tools
                </label>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                  {AVAILABLE_TOOLS.map((tool) => (
                    <label
                      key={tool.id}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 8,
                        padding: '8px 10px', borderRadius: 6, cursor: 'pointer',
                        background: wizard.selectedTools.includes(tool.id) ? C.accent + '15' : C.surface0,
                        border: `1px solid ${wizard.selectedTools.includes(tool.id) ? C.accent + '60' : C.border}`,
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={wizard.selectedTools.includes(tool.id)}
                        onChange={() => toggleTool(tool.id)}
                      />
                      <span style={{ color: C.text, fontSize: 12 }}>{tool.label}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <label style={{ display: 'block', color: C.subtext0, fontSize: 12, marginBottom: 6, fontWeight: 500 }}>
                    Budget ($, optional)
                  </label>
                  <input
                    style={inputStyle}
                    type="number"
                    placeholder="e.g. 5.00"
                    min="0"
                    step="0.01"
                    value={wizard.budget}
                    onChange={(e) => update({ budget: e.target.value })}
                  />
                </div>
                <div style={{ display: 'flex', alignItems: 'flex-end' }}>
                  <label style={{
                    display: 'flex', alignItems: 'center', gap: 8,
                    padding: '8px 10px', borderRadius: 6, cursor: 'pointer',
                    background: C.surface0, width: '100%', boxSizing: 'border-box',
                  }}>
                    <input
                      type="checkbox"
                      checked={wizard.learningEnabled}
                      onChange={(e) => update({ learningEnabled: e.target.checked })}
                    />
                    <span style={{ color: C.text, fontSize: 12 }}>Enable Learning</span>
                  </label>
                </div>
              </div>
            </div>
          )}

          {/* Step 3: Review */}
          {wizard.step === 3 && (
            <div>
              <p style={{ color: C.subtext0, fontSize: 13, marginBottom: 12 }}>Review your configuration</p>
              <div style={{ background: C.surface0, borderRadius: 8, padding: 16, border: `1px solid ${C.border}` }}>
                {[
                  ['Name', wizard.name || '(unnamed)'],
                  ['Template', wizard.templateId ? (templates.find((t) => t.id === wizard.templateId)?.name ?? wizard.templateId) : 'Custom'],
                  ['Schedule', formatSchedule(wizard.scheduleType, wizard.scheduleValue)],
                  ['Tools', wizard.selectedTools.length > 0 ? wizard.selectedTools.join(', ') : 'None'],
                  ['Budget', wizard.budget ? `$${wizard.budget}` : 'Unlimited'],
                  ['Learning', wizard.learningEnabled ? 'Enabled' : 'Disabled'],
                ].map(([label, value]) => (
                  <div key={label} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: `1px solid ${C.border}`, fontSize: 13 }}>
                    <span style={{ color: C.overlay0 }}>{label}</span>
                    <span style={{ color: C.text }}>{value}</span>
                  </div>
                ))}
              </div>
              {error && (
                <p style={{ color: C.red, fontSize: 12, marginTop: 10 }}>{error}</p>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 20px', borderTop: `1px solid ${C.border}` }}>
          <button
            onClick={() => wizard.step > 1 ? update({ step: (wizard.step - 1) as 1 | 2 | 3 }) : onClose()}
            style={{ padding: '8px 16px', borderRadius: 6, border: 'none', background: 'none', color: C.subtext0, cursor: 'pointer', fontSize: 13 }}
          >
            {wizard.step === 1 ? 'Cancel' : 'Back'}
          </button>
          {wizard.step < 3 ? (
            <button
              onClick={() => update({ step: (wizard.step + 1) as 2 | 3 })}
              style={{ padding: '8px 16px', borderRadius: 6, border: 'none', background: C.accent, color: C.bg, cursor: 'pointer', fontSize: 13, fontWeight: 600 }}
            >
              Next
            </button>
          ) : (
            <button
              onClick={handleLaunch}
              disabled={launching}
              style={{ padding: '8px 16px', borderRadius: 6, border: 'none', background: C.accent, color: C.bg, cursor: launching ? 'not-allowed' : 'pointer', fontSize: 13, fontWeight: 600, opacity: launching ? 0.7 : 1 }}
            >
              {launching ? 'Launching...' : 'Launch'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Interact Tab (chat interface)
// ---------------------------------------------------------------------------

function InteractTab({ apiUrl, agentId }: { apiUrl: string; agentId: string }) {
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [input, setInput] = useState('');
  const [mode, setMode] = useState<'immediate' | 'queued'>('queued');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);

  const loadMessages = useCallback(async () => {
    try {
      const msgs = await fetchAgentMessages(apiUrl, agentId);
      setMessages(msgs);
    } catch {
      // Non-critical
    }
  }, [apiUrl, agentId]);

  useEffect(() => {
    loadMessages();
    const t = setInterval(loadMessages, 5000);
    return () => clearInterval(t);
  }, [loadMessages]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  async function handleSend() {
    if (!input.trim()) return;
    setSending(true);
    setError('');
    try {
      await sendAgentMessage(apiUrl, agentId, input.trim(), mode);
      setInput('');
      await loadMessages();
    } catch {
      setError('Failed to send message.');
    } finally {
      setSending(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      {/* Message list */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '0 0 8px 0', display: 'flex', flexDirection: 'column', gap: 8 }}>
        {messages.length === 0 && (
          <div style={{ color: C.overlay0, fontSize: 13, textAlign: 'center', marginTop: 32 }}>
            No messages yet. Send a message to the agent below.
          </div>
        )}
        {messages.map((msg) => {
          const isUser = msg.direction === 'user_to_agent';
          return (
            <div
              key={msg.id}
              style={{
                display: 'flex', flexDirection: isUser ? 'row-reverse' : 'row', gap: 8, alignItems: 'flex-start',
              }}
            >
              <div
                style={{
                  maxWidth: '75%', padding: '8px 12px', borderRadius: 8, fontSize: 13,
                  background: isUser ? C.accent + '25' : C.surface0,
                  border: `1px solid ${isUser ? C.accent + '40' : C.border}`,
                  color: C.text,
                }}
              >
                <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{msg.content}</div>
                <div style={{ color: C.overlay0, fontSize: 10, marginTop: 4, textAlign: isUser ? 'right' : 'left' }}>
                  {isUser ? `You · ${msg.mode}` : 'Agent'} · {msg.status}
                </div>
              </div>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      {/* Error */}
      {error && (
        <div style={{ color: C.red, fontSize: 12, padding: '4px 0' }}>{error}</div>
      )}

      {/* Input area */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', paddingTop: 8, borderTop: `1px solid ${C.border}` }}>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Send a message to this agent… (Enter to send)"
            rows={2}
            style={{
              width: '100%', padding: '8px 12px', borderRadius: 6,
              background: C.mantle, border: `1px solid ${C.border}`,
              color: C.text, fontSize: 13, resize: 'none', outline: 'none',
              boxSizing: 'border-box', fontFamily: 'inherit',
            }}
          />
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ color: C.overlay0, fontSize: 11 }}>Mode:</span>
            {(['queued', 'immediate'] as const).map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                style={{
                  padding: '2px 8px', borderRadius: 4, fontSize: 11, cursor: 'pointer',
                  border: `1px solid ${mode === m ? C.accent : C.border}`,
                  background: mode === m ? C.accent + '20' : 'none',
                  color: mode === m ? C.accent : C.overlay0,
                }}
              >
                {m}
              </button>
            ))}
          </div>
        </div>
        <button
          onClick={handleSend}
          disabled={sending || !input.trim()}
          style={{
            padding: '10px 16px', borderRadius: 6, border: 'none',
            background: C.accent, color: C.bg, cursor: sending || !input.trim() ? 'not-allowed' : 'pointer',
            fontSize: 13, fontWeight: 600, opacity: sending || !input.trim() ? 0.5 : 1,
            flexShrink: 0,
          }}
        >
          Send
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tasks Tab
// ---------------------------------------------------------------------------

function TasksTab({ tasks }: { tasks: AgentTask[] }) {
  const taskStatusColor = (s: string) => {
    if (s === 'completed') return C.green;
    if (s === 'failed') return C.red;
    if (s === 'active') return C.accent;
    return C.overlay0;
  };

  if (tasks.length === 0) {
    return <div style={{ color: C.overlay0, fontSize: 13, textAlign: 'center', marginTop: 32 }}>No tasks found.</div>;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {tasks.map((t) => (
        <div key={t.id} style={{ background: C.surface0, borderRadius: 8, padding: '10px 14px', border: `1px solid ${C.border}` }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ color: C.text, fontSize: 13, flex: 1, marginRight: 12 }}>{t.description}</span>
            <span style={{
              display: 'inline-block', padding: '2px 8px', borderRadius: 4,
              fontSize: 11, fontWeight: 600, flexShrink: 0,
              background: taskStatusColor(t.status) + '25',
              color: taskStatusColor(t.status),
            }}>
              {t.status}
            </span>
          </div>
          <div style={{ color: C.overlay0, fontSize: 11, marginTop: 4 }}>
            Created {formatRelativeTime(t.created_at)}
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Memory Tab
// ---------------------------------------------------------------------------

function MemoryTab({ agent }: { agent: ManagedAgent }) {
  return (
    <div>
      <div style={{ color: C.subtext0, fontSize: 12, marginBottom: 8, fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        Summary Memory
      </div>
      <div style={{ background: C.surface0, borderRadius: 8, padding: 14, border: `1px solid ${C.border}` }}>
        <pre style={{
          color: C.text, fontSize: 12, whiteSpace: 'pre-wrap', margin: 0,
          fontFamily: "'JetBrains Mono', 'Fira Code', monospace", lineHeight: 1.6,
        }}>
          {agent.summary_memory || 'No memory stored yet.'}
        </pre>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Overview Tab
// ---------------------------------------------------------------------------

function OverviewTab({ agent, onRun, onPause, onResume, onRecover }: {
  agent: ManagedAgent;
  onRun: () => void;
  onPause: () => void;
  onResume: () => void;
  onRecover: () => void;
}) {
  const canPause = agent.status === 'running' || agent.status === 'idle';
  const canResume = agent.status === 'paused';
  const canRecover = agent.status === 'error' || agent.status === 'stalled' || agent.status === 'needs_attention';

  const rowStyle: React.CSSProperties = {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '6px 0', borderBottom: `1px solid ${C.border}`, fontSize: 13,
  };
  const labelStyle: React.CSSProperties = { color: C.overlay0 };
  const valueStyle: React.CSSProperties = { color: C.text, fontWeight: 500 };

  const statusColor = statusDotColor(agent.status);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Stats */}
      <div style={{ background: C.surface0, borderRadius: 8, padding: '12px 16px', border: `1px solid ${C.border}` }}>
        <div style={rowStyle}>
          <span style={labelStyle}>Status</span>
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '2px 10px', borderRadius: 12, fontSize: 12, fontWeight: 600,
            background: statusColor + '20', color: statusColor,
          }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: statusColor, display: 'inline-block' }} />
            {agent.status.replace('_', ' ')}
          </span>
        </div>
        <div style={rowStyle}>
          <span style={labelStyle}>Agent Type</span>
          <span style={valueStyle}>{agent.agent_type}</span>
        </div>
        <div style={rowStyle}>
          <span style={labelStyle}>Schedule</span>
          <span style={valueStyle}>{formatSchedule(agent.schedule_type, agent.schedule_value)}</span>
        </div>
        <div style={rowStyle}>
          <span style={labelStyle}>Last Run</span>
          <span style={valueStyle}>{formatRelativeTime(agent.last_run_at)}</span>
        </div>
        <div style={rowStyle}>
          <span style={labelStyle}>Total Runs</span>
          <span style={valueStyle}>{agent.total_runs ?? 0}</span>
        </div>
        <div style={rowStyle}>
          <span style={labelStyle}>Total Cost</span>
          <span style={valueStyle}>{formatCost(agent.total_cost)}</span>
        </div>
        <div style={{ ...rowStyle, borderBottom: 'none' }}>
          <span style={labelStyle}>Budget</span>
          <span style={valueStyle}>{agent.budget !== undefined ? `$${agent.budget}` : 'Unlimited'}</span>
        </div>
        {/* Budget progress bar */}
        {agent.budget !== undefined && agent.budget > 0 && (
          <div style={{ padding: '8px 0 0 0' }}>
            <div style={{ width: '100%', background: C.surface0, borderRadius: 4, height: 6, overflow: 'hidden' }}>
              <div
                style={{
                  width: `${Math.min(100, ((agent.total_cost ?? 0) / agent.budget) * 100)}%`,
                  height: '100%',
                  borderRadius: 4,
                  background:
                    ((agent.total_cost ?? 0) / agent.budget) > 0.9
                      ? C.red
                      : ((agent.total_cost ?? 0) / agent.budget) > 0.75
                        ? C.yellow
                        : C.green,
                  transition: 'width 0.3s ease',
                }}
              />
            </div>
          </div>
        )}
      </div>

      {/* Actions */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button
          onClick={onRun}
          style={{
            padding: '8px 14px', borderRadius: 6, border: 'none',
            background: C.green + '25', color: C.green,
            cursor: 'pointer', fontSize: 12, fontWeight: 600,
          }}
        >
          ▶ Run Now
        </button>
        {canPause && (
          <button
            onClick={onPause}
            style={{
              padding: '8px 14px', borderRadius: 6, border: 'none',
              background: C.yellow + '25', color: C.yellow,
              cursor: 'pointer', fontSize: 12, fontWeight: 600,
            }}
          >
            ⏸ Pause
          </button>
        )}
        {canResume && (
          <button
            onClick={onResume}
            style={{
              padding: '8px 14px', borderRadius: 6, border: 'none',
              background: C.accent + '25', color: C.accent,
              cursor: 'pointer', fontSize: 12, fontWeight: 600,
            }}
          >
            ▶ Resume
          </button>
        )}
        {canRecover && (
          <button
            onClick={onRecover}
            style={{
              padding: '8px 14px', borderRadius: 6, border: 'none',
              background: C.peach + '25', color: C.peach,
              cursor: 'pointer', fontSize: 12, fontWeight: 600,
            }}
          >
            ↺ Recover
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Learning Tab
// ---------------------------------------------------------------------------

function LearningTabContent({
  apiUrl,
  agentId,
  learningEnabled,
}: {
  apiUrl: string;
  agentId: string;
  learningEnabled: boolean;
}) {
  const [logs, setLogs] = useState<LearningLogEntry[]>([]);
  const [triggering, setTriggering] = useState(false);

  useEffect(() => {
    fetchLearningLog(apiUrl, agentId).then(setLogs).catch(() => {});
  }, [apiUrl, agentId]);

  async function handleTrigger() {
    setTriggering(true);
    try {
      await triggerLearning(apiUrl, agentId);
      setTimeout(() => fetchLearningLog(apiUrl, agentId).then(setLogs).catch(() => {}), 1000);
    } catch {
      // ignore
    } finally {
      setTriggering(false);
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ color: C.subtext0, fontSize: 12, fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Learning
          </span>
          <span style={{
            fontSize: 11, padding: '1px 8px', borderRadius: 8,
            background: learningEnabled ? C.green + '25' : C.surface0,
            color: learningEnabled ? C.green : C.overlay0,
          }}>
            {learningEnabled ? 'Enabled' : 'Disabled'}
          </span>
        </div>
        <button
          onClick={handleTrigger}
          disabled={triggering}
          style={{
            padding: '6px 12px', borderRadius: 6, border: 'none',
            background: C.accent, color: C.bg, cursor: triggering ? 'not-allowed' : 'pointer',
            fontSize: 12, fontWeight: 600, opacity: triggering ? 0.6 : 1,
          }}
        >
          {triggering ? 'Running...' : 'Run Learning'}
        </button>
      </div>
      {logs.length === 0 ? (
        <div style={{ color: C.overlay0, fontSize: 13, textAlign: 'center', marginTop: 32 }}>
          No learning events yet. Run the agent or trigger learning manually.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {logs.map((entry) => (
            <div key={entry.id} style={{
              background: C.surface0, borderRadius: 8, padding: '10px 14px',
              border: `1px solid ${C.border}`,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                <span style={{
                  fontSize: 11, padding: '1px 8px', borderRadius: 4,
                  background: C.accent + '20', color: C.accent,
                }}>
                  {entry.event_type}
                </span>
                <span style={{ color: C.overlay0, fontSize: 11 }}>
                  {formatRelativeTime(entry.created_at)}
                </span>
              </div>
              {entry.description && (
                <div style={{ color: C.subtext0, fontSize: 12, marginTop: 4 }}>
                  {entry.description}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Logs Tab (execution traces)
// ---------------------------------------------------------------------------

function LogsTabContent({ apiUrl, agentId }: { apiUrl: string; agentId: string }) {
  const [traces, setTraces] = useState<AgentTrace[]>([]);

  useEffect(() => {
    fetchAgentTraces(apiUrl, agentId).then(setTraces).catch(() => {});
  }, [apiUrl, agentId]);

  if (traces.length === 0) {
    return (
      <div style={{ color: C.overlay0, fontSize: 13, textAlign: 'center', marginTop: 32 }}>
        No execution traces yet. Run the agent to generate traces.
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ color: C.subtext0, fontSize: 12, fontWeight: 500, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Execution Traces
        </span>
        <span style={{ color: C.overlay0, fontSize: 11 }}>
          {traces.length} trace{traces.length !== 1 ? 's' : ''}
        </span>
      </div>
      {traces.map((t) => (
        <div key={t.id} style={{
          background: C.surface0, borderRadius: 8, padding: '10px 14px',
          border: `1px solid ${C.border}`,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{
                width: 8, height: 8, borderRadius: '50%', display: 'inline-block',
                background: t.outcome === 'success' ? C.green : C.red,
              }} />
              <span style={{ color: C.text, fontSize: 13 }}>{t.outcome}</span>
            </div>
            <span style={{ color: C.overlay0, fontSize: 11 }}>
              {formatRelativeTime(t.started_at)}
            </span>
          </div>
          <div style={{ display: 'flex', gap: 12, marginTop: 4, fontSize: 11, color: C.overlay0 }}>
            <span>{t.duration.toFixed(1)}s</span>
            <span>{t.steps} step{t.steps !== 1 ? 's' : ''}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detail Panel (tabbed)
// ---------------------------------------------------------------------------

type DetailTab = 'overview' | 'interact' | 'tasks' | 'memory' | 'learning' | 'logs';

const DETAIL_TABS: { id: DetailTab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'interact', label: 'Interact' },
  { id: 'tasks', label: 'Tasks' },
  { id: 'memory', label: 'Memory' },
  { id: 'learning', label: 'Learning' },
  { id: 'logs', label: 'Logs' },
];

function DetailPanel({
  apiUrl,
  agent,
  tasks,
  onRun,
  onPause,
  onResume,
  onRecover,
}: {
  apiUrl: string;
  agent: ManagedAgent;
  tasks: AgentTask[];
  onRun: (id: string) => void;
  onPause: (id: string) => void;
  onResume: (id: string) => void;
  onRecover: (id: string) => void;
}) {
  const [activeTab, setActiveTab] = useState<DetailTab>('overview');
  const dotColor = statusDotColor(agent.status);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Agent header */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <span style={{ width: 10, height: 10, borderRadius: '50%', background: dotColor, display: 'inline-block', flexShrink: 0 }} />
          <h2 style={{ color: C.text, fontSize: 18, fontWeight: 700, margin: 0 }}>{agent.name}</h2>
        </div>
        <div style={{ color: C.overlay0, fontSize: 12 }}>
          {agent.agent_type} · Schedule: {formatSchedule(agent.schedule_type, agent.schedule_value)} · Last run: {formatRelativeTime(agent.last_run_at)}
        </div>
      </div>

      {/* Tab bar */}
      <div style={{ display: 'flex', gap: 2, marginBottom: 16, borderBottom: `1px solid ${C.border}`, paddingBottom: 0 }}>
        {DETAIL_TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              padding: '6px 14px', border: 'none', borderRadius: '6px 6px 0 0',
              background: activeTab === tab.id ? C.surface0 : 'none',
              color: activeTab === tab.id ? C.text : C.overlay0,
              cursor: 'pointer', fontSize: 13, fontWeight: activeTab === tab.id ? 600 : 400,
              borderBottom: activeTab === tab.id ? `2px solid ${C.accent}` : '2px solid transparent',
              marginBottom: -1,
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
        {activeTab === 'overview' && (
          <OverviewTab
            agent={agent}
            onRun={() => onRun(agent.id)}
            onPause={() => onPause(agent.id)}
            onResume={() => onResume(agent.id)}
            onRecover={() => onRecover(agent.id)}
          />
        )}
        {activeTab === 'interact' && <InteractTab apiUrl={apiUrl} agentId={agent.id} />}
        {activeTab === 'tasks' && <TasksTab tasks={tasks} />}
        {activeTab === 'memory' && <MemoryTab agent={agent} />}
        {activeTab === 'learning' && (
          <LearningTabContent apiUrl={apiUrl} agentId={agent.id} learningEnabled={!!agent.learning_enabled} />
        )}
        {activeTab === 'logs' && (
          <LogsTabContent apiUrl={apiUrl} agentId={agent.id} />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main AgentsPanel
// ---------------------------------------------------------------------------

interface Props {
  apiUrl: string;
}

export function AgentsPanel({ apiUrl }: Props) {
  const [agents, setAgents] = useState<ManagedAgent[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [templates, setTemplates] = useState<AgentTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [showWizard, setShowWizard] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const fetched = await fetchManagedAgents(apiUrl);
      setAgents(fetched);
    } catch {
      // Non-critical
    } finally {
      setLoading(false);
    }
  }, [apiUrl]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 10_000);
    return () => clearInterval(t);
  }, [refresh]);

  useEffect(() => {
    fetchTemplates(apiUrl).then(setTemplates).catch(() => {});
  }, [apiUrl]);

  useEffect(() => {
    if (selectedId) {
      fetchAgentTasks(apiUrl, selectedId).then(setTasks).catch(() => setTasks([]));
    }
  }, [apiUrl, selectedId]);

  const handlePause = useCallback(async (id: string) => {
    await pauseManagedAgent(apiUrl, id).catch(() => {});
    refresh();
  }, [apiUrl, refresh]);

  const handleResume = useCallback(async (id: string) => {
    await resumeManagedAgent(apiUrl, id).catch(() => {});
    refresh();
  }, [apiUrl, refresh]);

  const handleRun = useCallback(async (id: string) => {
    await runManagedAgent(apiUrl, id).catch(() => {});
    refresh();
  }, [apiUrl, refresh]);

  const handleRecover = useCallback(async (id: string) => {
    await recoverManagedAgent(apiUrl, id).catch(() => {});
    refresh();
  }, [apiUrl, refresh]);

  const handleDelete = useCallback(async (id: string) => {
    if (!confirm('Delete this agent? This cannot be undone.')) return;
    await deleteManagedAgent(apiUrl, id).catch(() => {});
    if (selectedId === id) setSelectedId(null);
    refresh();
  }, [apiUrl, selectedId, refresh]);

  const selected = agents.find((a) => a.id === selectedId) ?? null;

  if (loading) {
    return (
      <div style={{ padding: 40, color: C.overlay0, textAlign: 'center' }}>
        Loading agents...
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', height: '100%', minHeight: 0 }}>
      {/* Left panel — agent list */}
      <div style={{ width: 300, flexShrink: 0, borderRight: `1px solid ${C.border}`, display: 'flex', flexDirection: 'column' }}>
        {/* Header */}
        <div style={{ padding: '12px 14px', borderBottom: `1px solid ${C.border}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ color: C.text, fontSize: 14, fontWeight: 600 }}>Agents ({agents.length})</span>
          <button
            onClick={() => setShowWizard(true)}
            style={{
              padding: '5px 12px', borderRadius: 6, border: 'none',
              background: C.accent, color: C.bg,
              cursor: 'pointer', fontSize: 12, fontWeight: 600,
            }}
          >
            + Launch
          </button>
        </div>

        {/* Agent list */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '8px 10px' }}>
          {agents.map((a) => {
            const dot = statusDotColor(a.status);
            const isSelected = selectedId === a.id;
            return (
              <div
                key={a.id}
                onClick={() => setSelectedId(a.id)}
                style={{
                  padding: '10px 12px', borderRadius: 8, marginBottom: 6,
                  cursor: 'pointer', border: `1px solid ${isSelected ? C.accent : C.border}`,
                  background: isSelected ? C.accent + '10' : C.surface0,
                  transition: 'border-color 0.15s',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                    <span style={{ width: 8, height: 8, borderRadius: '50%', background: dot, flexShrink: 0, display: 'inline-block' }} />
                    <span style={{ color: C.text, fontSize: 13, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {a.name}
                    </span>
                  </div>
                  <button
                    onClick={(e) => { e.stopPropagation(); handleDelete(a.id); }}
                    style={{
                      background: 'none', border: 'none', color: C.overlay0,
                      cursor: 'pointer', fontSize: 14, padding: '0 2px', flexShrink: 0, lineHeight: 1,
                    }}
                    title="Delete agent"
                  >
                    ×
                  </button>
                </div>
                <div style={{ color: C.overlay0, fontSize: 11, marginTop: 4 }}>
                  {formatSchedule(a.schedule_type, a.schedule_value)}
                </div>
                <div style={{ color: C.overlay1, fontSize: 11, marginTop: 2 }}>
                  Last run: {formatRelativeTime(a.last_run_at)}
                </div>
              </div>
            );
          })}
          {agents.length === 0 && (
            <div style={{ color: C.overlay0, fontSize: 13, textAlign: 'center', marginTop: 40 }}>
              No agents found.<br />
              <span style={{ fontSize: 12 }}>Click "+ Launch" to create one.</span>
            </div>
          )}
        </div>
      </div>

      {/* Right panel — detail */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 20, minWidth: 0 }}>
        {selected ? (
          <DetailPanel
            apiUrl={apiUrl}
            agent={selected}
            tasks={tasks}
            onRun={handleRun}
            onPause={handlePause}
            onResume={handleResume}
            onRecover={handleRecover}
          />
        ) : (
          <div style={{ color: C.overlay0, textAlign: 'center', marginTop: 80, fontSize: 14 }}>
            Select an agent to view details
          </div>
        )}
      </div>

      {/* Launch wizard */}
      {showWizard && (
        <LaunchWizard
          apiUrl={apiUrl}
          templates={templates}
          onClose={() => setShowWizard(false)}
          onLaunched={() => { setShowWizard(false); refresh(); }}
        />
      )}
    </div>
  );
}
