import { useEffect, useState, useCallback, useRef } from 'react';
import { useAppStore } from '../lib/store';
import {
  fetchManagedAgents,
  fetchAgentTasks,
  fetchAgentChannels,
  fetchAgentMessages,
  fetchTemplates,
  createManagedAgent,
  pauseManagedAgent,
  resumeManagedAgent,
  deleteManagedAgent,
  runManagedAgent,
  recoverManagedAgent,
  sendAgentMessage,
  fetchLearningLog,
  triggerLearning,
  fetchAgentTraces,
} from '../lib/api';
import type { AgentTask, ChannelBinding, AgentTemplate, AgentMessage, ManagedAgent, LearningLogEntry, AgentTrace } from '../lib/api';
import {
  Plus,
  Bot,
  Pause,
  Play,
  Trash2,
  ChevronLeft,
  ListTodo,
  Brain,
  Zap,
  MoreHorizontal,
  AlertTriangle,
  DollarSign,
  Activity,
  MessageSquare,
  Settings,
  FileText,
  X,
  ChevronRight,
  Send,
  RefreshCw,
} from 'lucide-react';

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
  idle: '#22c55e',
  running: '#3b82f6',
  paused: '#6b7280',
  error: '#ef4444',
  archived: '#6b7280',
  needs_attention: '#f59e0b',
  budget_exceeded: '#f97316',
  stalled: '#eab308',
};

function statusColor(s: string): string {
  return STATUS_COLOR[s as AgentStatus] || '#6b7280';
}

function StatusBadge({ status }: { status: string }) {
  const color = statusColor(status);
  return (
    <span
      className="px-2 py-0.5 rounded-full text-xs font-medium"
      style={{ background: color + '20', color }}
    >
      {status.replace('_', ' ')}
    </span>
  );
}

function StatusDot({ status }: { status: string }) {
  const color = statusColor(status);
  return (
    <span
      className="w-2 h-2 rounded-full inline-block flex-shrink-0"
      style={{ background: color }}
      title={status}
    />
  );
}

function formatCost(cost?: number): string {
  if (cost === undefined || cost === null) return '—';
  if (cost < 0.01) return `$${(cost * 100).toFixed(2)}¢`;
  return `$${cost.toFixed(3)}`;
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
  templates,
  onClose,
  onLaunched,
}: {
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
    update({
      templateId: id,
      name: tpl?.name || wizard.name,
    });
  }

  async function handleLaunch() {
    if (!wizard.name.trim()) {
      setError('Agent name is required.');
      return;
    }
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
      await createManagedAgent({
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

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'rgba(0,0,0,0.5)' }}
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        className="w-full max-w-lg mx-4 rounded-xl overflow-hidden flex flex-col"
        style={{
          background: 'var(--color-bg)',
          border: '1px solid var(--color-border)',
          maxHeight: '85vh',
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-6 py-4"
          style={{ borderBottom: '1px solid var(--color-border)' }}
        >
          <div className="flex items-center gap-2">
            <Bot size={18} style={{ color: 'var(--color-accent)' }} />
            <h2 className="font-semibold" style={{ color: 'var(--color-text)' }}>
              Launch Agent
            </h2>
          </div>
          <div className="flex items-center gap-4">
            {/* Step indicator */}
            <div className="flex items-center gap-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
              {([1, 2, 3] as const).map((s) => (
                <span key={s} className="flex items-center gap-1">
                  <span
                    className="w-5 h-5 rounded-full flex items-center justify-center text-xs font-medium"
                    style={{
                      background: wizard.step === s ? 'var(--color-accent)' : wizard.step > s ? 'var(--color-accent)' + '40' : 'var(--color-bg-secondary)',
                      color: wizard.step >= s ? (wizard.step === s ? '#fff' : 'var(--color-accent)') : 'var(--color-text-tertiary)',
                    }}
                  >
                    {s}
                  </span>
                  {s < 3 && <ChevronRight size={10} />}
                </span>
              ))}
            </div>
            <button onClick={onClose} className="cursor-pointer" style={{ color: 'var(--color-text-tertiary)' }}>
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          {/* Step 1: Template Picker */}
          {wizard.step === 1 && (
            <div>
              <p className="text-sm font-medium mb-3" style={{ color: 'var(--color-text-secondary)' }}>
                Choose a template or start from scratch
              </p>
              <div className="space-y-2">
                {/* Custom option */}
                <button
                  onClick={() => update({ templateId: '' })}
                  className="w-full text-left p-3 rounded-lg transition-colors cursor-pointer"
                  style={{
                    background: wizard.templateId === '' ? 'var(--color-accent)' + '15' : 'var(--color-bg-secondary)',
                    border: `1px solid ${wizard.templateId === '' ? 'var(--color-accent)' : 'var(--color-border)'}`,
                  }}
                >
                  <div className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                    Custom Agent
                  </div>
                  <div className="text-xs mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
                    Start from scratch with full control
                  </div>
                </button>
                {templates.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => selectTemplate(t.id)}
                    className="w-full text-left p-3 rounded-lg transition-colors cursor-pointer"
                    style={{
                      background: wizard.templateId === t.id ? 'var(--color-accent)' + '15' : 'var(--color-bg-secondary)',
                      border: `1px solid ${wizard.templateId === t.id ? 'var(--color-accent)' : 'var(--color-border)'}`,
                    }}
                  >
                    <div className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                      {t.name}
                    </div>
                    {t.description && (
                      <div className="text-xs mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
                        {t.description.slice(0, 80)}
                      </div>
                    )}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Step 2: Config Form */}
          {wizard.step === 2 && (
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>
                  Agent Name *
                </label>
                <input
                  type="text"
                  placeholder="e.g. Research Assistant"
                  value={wizard.name}
                  onChange={(e) => update({ name: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg text-sm bg-transparent outline-none"
                  style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>
                    Schedule Type
                  </label>
                  <select
                    value={wizard.scheduleType}
                    onChange={(e) => update({ scheduleType: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg text-sm"
                    style={{
                      background: 'var(--color-bg)',
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-text)',
                    }}
                  >
                    <option value="manual">Manual</option>
                    <option value="cron">Cron</option>
                    <option value="interval">Interval</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>
                    Schedule Value
                  </label>
                  <input
                    type="text"
                    placeholder={wizard.scheduleType === 'cron' ? '0 * * * *' : wizard.scheduleType === 'interval' ? '1h' : '—'}
                    value={wizard.scheduleValue}
                    onChange={(e) => update({ scheduleValue: e.target.value })}
                    disabled={wizard.scheduleType === 'manual'}
                    className="w-full px-3 py-2 rounded-lg text-sm bg-transparent outline-none"
                    style={{
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-text)',
                      opacity: wizard.scheduleType === 'manual' ? 0.4 : 1,
                    }}
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium mb-2" style={{ color: 'var(--color-text-secondary)' }}>
                  Tools
                </label>
                <div className="grid grid-cols-2 gap-2">
                  {AVAILABLE_TOOLS.map((tool) => (
                    <label
                      key={tool.id}
                      className="flex items-center gap-2 p-2 rounded-lg cursor-pointer"
                      style={{
                        background: wizard.selectedTools.includes(tool.id) ? 'var(--color-accent)' + '10' : 'var(--color-bg-secondary)',
                        border: `1px solid ${wizard.selectedTools.includes(tool.id) ? 'var(--color-accent)' + '50' : 'var(--color-border)'}`,
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={wizard.selectedTools.includes(tool.id)}
                        onChange={() => toggleTool(tool.id)}
                        className="accent-current"
                      />
                      <span className="text-xs" style={{ color: 'var(--color-text)' }}>
                        {tool.label}
                      </span>
                    </label>
                  ))}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>
                    Budget ($, optional)
                  </label>
                  <input
                    type="number"
                    placeholder="e.g. 5.00"
                    min="0"
                    step="0.01"
                    value={wizard.budget}
                    onChange={(e) => update({ budget: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg text-sm bg-transparent outline-none"
                    style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                  />
                </div>
                <div className="flex flex-col justify-end">
                  <label className="flex items-center gap-2 cursor-pointer p-2 rounded-lg" style={{ background: 'var(--color-bg-secondary)' }}>
                    <input
                      type="checkbox"
                      checked={wizard.learningEnabled}
                      onChange={(e) => update({ learningEnabled: e.target.checked })}
                    />
                    <span className="text-xs" style={{ color: 'var(--color-text)' }}>
                      Enable Learning
                    </span>
                  </label>
                </div>
              </div>
            </div>
          )}

          {/* Step 3: Review */}
          {wizard.step === 3 && (
            <div className="space-y-4">
              <p className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>
                Review your configuration
              </p>
              <div
                className="rounded-lg p-4 space-y-3 text-sm"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
              >
                <div className="flex justify-between">
                  <span style={{ color: 'var(--color-text-tertiary)' }}>Name</span>
                  <span style={{ color: 'var(--color-text)' }}>{wizard.name || '(unnamed)'}</span>
                </div>
                <div className="flex justify-between">
                  <span style={{ color: 'var(--color-text-tertiary)' }}>Template</span>
                  <span style={{ color: 'var(--color-text)' }}>
                    {wizard.templateId ? (templates.find((t) => t.id === wizard.templateId)?.name ?? wizard.templateId) : 'Custom'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span style={{ color: 'var(--color-text-tertiary)' }}>Schedule</span>
                  <span style={{ color: 'var(--color-text)' }}>
                    {formatSchedule(wizard.scheduleType, wizard.scheduleValue)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span style={{ color: 'var(--color-text-tertiary)' }}>Tools</span>
                  <span style={{ color: 'var(--color-text)' }}>
                    {wizard.selectedTools.length > 0 ? wizard.selectedTools.join(', ') : 'None'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span style={{ color: 'var(--color-text-tertiary)' }}>Budget</span>
                  <span style={{ color: 'var(--color-text)' }}>{wizard.budget ? `$${wizard.budget}` : 'Unlimited'}</span>
                </div>
                <div className="flex justify-between">
                  <span style={{ color: 'var(--color-text-tertiary)' }}>Learning</span>
                  <span style={{ color: 'var(--color-text)' }}>{wizard.learningEnabled ? 'Enabled' : 'Disabled'}</span>
                </div>
              </div>
              {error && (
                <p className="text-sm" style={{ color: '#ef4444' }}>
                  {error}
                </p>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          className="flex justify-between items-center px-6 py-4"
          style={{ borderTop: '1px solid var(--color-border)' }}
        >
          <button
            onClick={() => (wizard.step > 1 ? update({ step: (wizard.step - 1) as 1 | 2 | 3 }) : onClose())}
            className="px-4 py-2 rounded-lg text-sm cursor-pointer"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            {wizard.step === 1 ? 'Cancel' : 'Back'}
          </button>
          {wizard.step < 3 ? (
            <button
              onClick={() => update({ step: (wizard.step + 1) as 2 | 3 })}
              className="px-4 py-2 rounded-lg text-sm font-medium cursor-pointer"
              style={{ background: 'var(--color-accent)', color: '#fff' }}
            >
              Next
            </button>
          ) : (
            <button
              onClick={handleLaunch}
              disabled={launching}
              className="px-4 py-2 rounded-lg text-sm font-medium cursor-pointer flex items-center gap-2"
              style={{ background: 'var(--color-accent)', color: '#fff', opacity: launching ? 0.7 : 1 }}
            >
              {launching && <RefreshCw size={14} className="animate-spin" />}
              Launch
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Overflow menu
// ---------------------------------------------------------------------------

function OverflowMenu({
  agentId,
  onDelete,
}: {
  agentId: string;
  onDelete: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className="p-1 rounded cursor-pointer"
        style={{ color: 'var(--color-text-tertiary)' }}
        title="More actions"
      >
        <MoreHorizontal size={14} />
      </button>
      {open && (
        <div
          className="absolute right-0 top-6 z-20 rounded-lg py-1 min-w-[120px]"
          style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', boxShadow: '0 4px 12px rgba(0,0,0,0.15)' }}
        >
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete(agentId);
              setOpen(false);
            }}
            className="w-full text-left px-3 py-1.5 text-xs cursor-pointer flex items-center gap-2"
            style={{ color: '#ef4444' }}
          >
            <Trash2 size={12} /> Delete
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Agent List Card
// ---------------------------------------------------------------------------

function AgentCard({
  agent,
  onClick,
  onPause,
  onResume,
  onRun,
  onRecover,
  onDelete,
}: {
  agent: ManagedAgent;
  onClick: () => void;
  onPause: (id: string) => void;
  onResume: (id: string) => void;
  onRun: (id: string) => void;
  onRecover: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const canPause = agent.status === 'running' || agent.status === 'idle';
  const canResume = agent.status === 'paused';
  const canRecover = agent.status === 'error' || agent.status === 'stalled' || agent.status === 'needs_attention';

  return (
    <div
      onClick={onClick}
      className="p-4 rounded-lg cursor-pointer transition-colors"
      style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
      onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--color-accent)')}
      onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--color-border)')}
    >
      {/* Row 1: Name + status dot */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <Bot size={16} style={{ color: 'var(--color-accent)', flexShrink: 0 }} />
          <span className="font-medium text-sm truncate" style={{ color: 'var(--color-text)' }}>
            {agent.name}
          </span>
        </div>
        <StatusDot status={agent.status} />
      </div>

      {/* Row 2: Schedule + last run */}
      <div className="text-xs mb-2 flex items-center gap-3" style={{ color: 'var(--color-text-tertiary)' }}>
        <span>{formatSchedule(agent.schedule_type, agent.schedule_value)}</span>
        <span>·</span>
        <span>Last run: {formatRelativeTime(agent.last_run_at)}</span>
      </div>

      {/* Row 3: Stats */}
      <div className="flex items-center gap-4 mb-3 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
        <span className="flex items-center gap-1">
          <Activity size={11} />
          {agent.total_runs ?? 0} runs
        </span>
        <span className="flex items-center gap-1">
          <DollarSign size={11} />
          {formatCost(agent.total_cost)}
        </span>
      </div>

      {/* Budget progress bar */}
      {(agent.config?.max_cost as number) > 0 && (
        <div className="mb-3">
          <div className="flex justify-between text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>
            <span>Budget</span>
            <span>
              {formatCost(agent.total_cost)} / ${(agent.config?.max_cost as number).toFixed(0)}
            </span>
          </div>
          <div className="w-full rounded-full h-1.5" style={{ background: 'var(--color-bg)' }}>
            <div
              className="h-1.5 rounded-full transition-all"
              style={{
                width: `${Math.min(100, ((agent.total_cost ?? 0) / (agent.config?.max_cost as number)) * 100)}%`,
                background:
                  ((agent.total_cost ?? 0) / (agent.config?.max_cost as number)) > 0.9
                    ? '#ef4444'
                    : ((agent.total_cost ?? 0) / (agent.config?.max_cost as number)) > 0.75
                      ? '#f59e0b'
                      : '#22c55e',
              }}
            />
          </div>
        </div>
      )}

      {/* Row 4: Actions */}
      <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
        <button
          onClick={() => onRun(agent.id)}
          className="flex items-center gap-1 px-2 py-1 rounded text-xs cursor-pointer transition-colors"
          style={{ background: 'var(--color-accent)' + '15', color: 'var(--color-accent)' }}
          title="Run now"
        >
          <Zap size={11} /> Run Now
        </button>
        {canPause && (
          <button
            onClick={() => onPause(agent.id)}
            className="p-1 rounded cursor-pointer"
            style={{ color: 'var(--color-text-secondary)' }}
            title="Pause"
          >
            <Pause size={13} />
          </button>
        )}
        {canResume && (
          <button
            onClick={() => onResume(agent.id)}
            className="p-1 rounded cursor-pointer"
            style={{ color: '#22c55e' }}
            title="Resume"
          >
            <Play size={13} />
          </button>
        )}
        {canRecover && (
          <button
            onClick={() => onRecover(agent.id)}
            className="flex items-center gap-1 px-2 py-1 rounded text-xs cursor-pointer"
            style={{ background: '#ef444420', color: '#ef4444' }}
            title="Recover agent"
          >
            <AlertTriangle size={11} /> Recover
          </button>
        )}
        <div className="ml-auto">
          <OverflowMenu agentId={agent.id} onDelete={onDelete} />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detail view — Interact tab
// ---------------------------------------------------------------------------

function InteractTab({ agentId }: { agentId: string }) {
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const loadMessages = useCallback(async () => {
    try {
      const msgs = await fetchAgentMessages(agentId);
      setMessages(msgs);
    } catch {
      // ignore
    }
  }, [agentId]);

  useEffect(() => {
    loadMessages();
  }, [loadMessages]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  async function handleSend(mode: 'immediate' | 'queued') {
    if (!input.trim()) return;
    setSending(true);
    try {
      await sendAgentMessage(agentId, input.trim(), mode);
      setInput('');
      await loadMessages();
    } catch {
      // ignore
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="flex flex-col h-full" style={{ minHeight: 320 }}>
      <div className="flex-1 overflow-y-auto space-y-3 pb-4" style={{ maxHeight: 400 }}>
        {messages.length === 0 && (
          <div className="text-sm text-center py-8" style={{ color: 'var(--color-text-tertiary)' }}>
            No messages yet. Send a message to interact with this agent.
          </div>
        )}
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.direction === 'user_to_agent' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className="max-w-[75%] px-3 py-2 rounded-lg text-sm"
              style={{
                background: msg.direction === 'user_to_agent' ? 'var(--color-accent)' : 'var(--color-bg-secondary)',
                color: msg.direction === 'user_to_agent' ? '#fff' : 'var(--color-text)',
                border: msg.direction === 'agent_to_user' ? '1px solid var(--color-border)' : 'none',
              }}
            >
              <p>{msg.content}</p>
              <p
                className="text-xs mt-1 opacity-70"
              >
                {msg.mode} · {msg.status}
              </p>
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
      {/* Input area */}
      <div
        className="mt-3 pt-3"
        style={{ borderTop: '1px solid var(--color-border)' }}
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              handleSend('queued');
            }
          }}
          placeholder="Send a message to this agent..."
          className="w-full px-3 py-2 rounded-lg text-sm bg-transparent outline-none resize-none"
          style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)', minHeight: 72 }}
        />
        <div className="flex gap-2 mt-2">
          <button
            onClick={() => handleSend('immediate')}
            disabled={sending || !input.trim()}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm cursor-pointer font-medium"
            style={{ background: 'var(--color-accent)', color: '#fff', opacity: sending || !input.trim() ? 0.5 : 1 }}
            title="Send immediately (interrupts agent)"
          >
            <Zap size={13} /> Immediate
          </button>
          <button
            onClick={() => handleSend('queued')}
            disabled={sending || !input.trim()}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm cursor-pointer"
            style={{
              background: 'var(--color-bg-secondary)',
              color: 'var(--color-text)',
              border: '1px solid var(--color-border)',
              opacity: sending || !input.trim() ? 0.5 : 1,
            }}
            title="Queue message for next run"
          >
            <Send size={13} /> Queue
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Learning tab component
// ---------------------------------------------------------------------------

function LearningTab({ agentId, learningEnabled }: { agentId: string; learningEnabled: boolean }) {
  const [logs, setLogs] = useState<LearningLogEntry[]>([]);
  const [triggering, setTriggering] = useState(false);

  useEffect(() => {
    fetchLearningLog(agentId).then(setLogs).catch(() => {});
  }, [agentId]);

  async function handleTrigger() {
    setTriggering(true);
    try {
      await triggerLearning(agentId);
      // Refresh after a short delay
      setTimeout(() => fetchLearningLog(agentId).then(setLogs).catch(() => {}), 1000);
    } catch {
      // ignore
    } finally {
      setTriggering(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>Learning</span>
          <span
            className="text-xs px-2 py-0.5 rounded-full"
            style={{
              background: learningEnabled ? '#22c55e20' : 'var(--color-bg-secondary)',
              color: learningEnabled ? '#22c55e' : 'var(--color-text-tertiary)',
            }}
          >
            {learningEnabled ? 'Enabled' : 'Disabled'}
          </span>
        </div>
        <button
          onClick={handleTrigger}
          disabled={triggering}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs cursor-pointer font-medium"
          style={{
            background: 'var(--color-accent)',
            color: '#fff',
            opacity: triggering ? 0.6 : 1,
          }}
        >
          <RefreshCw size={12} className={triggering ? 'animate-spin' : ''} />
          Run Learning
        </button>
      </div>
      {logs.length === 0 ? (
        <div className="text-sm text-center py-8" style={{ color: 'var(--color-text-tertiary)' }}>
          No learning events yet. Run the agent or trigger learning manually.
        </div>
      ) : (
        <div className="space-y-2">
          {logs.map((entry) => (
            <div
              key={entry.id}
              className="rounded-lg p-3 text-sm"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <div className="flex items-center justify-between mb-1">
                <span
                  className="text-xs px-2 py-0.5 rounded"
                  style={{ background: 'var(--color-accent)' + '20', color: 'var(--color-accent)' }}
                >
                  {entry.event_type}
                </span>
                <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                  {formatRelativeTime(entry.created_at)}
                </span>
              </div>
              {entry.description && (
                <p style={{ color: 'var(--color-text-secondary)' }}>{entry.description}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Logs tab component
// ---------------------------------------------------------------------------

function LogsTab({ agentId }: { agentId: string }) {
  const [traces, setTraces] = useState<AgentTrace[]>([]);

  useEffect(() => {
    fetchAgentTraces(agentId).then(setTraces).catch(() => {});
  }, [agentId]);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
          Execution Traces
        </span>
        <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
          {traces.length} trace{traces.length !== 1 ? 's' : ''}
        </span>
      </div>
      {traces.length === 0 ? (
        <div className="text-sm text-center py-8" style={{ color: 'var(--color-text-tertiary)' }}>
          No execution traces yet. Run the agent to generate traces.
        </div>
      ) : (
        <div className="space-y-2">
          {traces.map((t) => (
            <div
              key={t.id}
              className="rounded-lg p-3 text-sm"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span
                    className="w-2 h-2 rounded-full inline-block"
                    style={{ background: t.outcome === 'success' ? '#22c55e' : '#ef4444' }}
                  />
                  <span style={{ color: 'var(--color-text)' }}>{t.outcome}</span>
                </div>
                <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                  {formatRelativeTime(t.started_at)}
                </span>
              </div>
              <div className="flex items-center gap-3 mt-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                <span>{t.duration.toFixed(1)}s</span>
                <span>{t.steps} step{t.steps !== 1 ? 's' : ''}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------

export function AgentsPage() {
  const managedAgents = useAppStore((s) => s.managedAgents);
  const setManagedAgents = useAppStore((s) => s.setManagedAgents);
  const selectedAgentId = useAppStore((s) => s.selectedAgentId);
  const setSelectedAgentId = useAppStore((s) => s.setSelectedAgentId);
  const [loading, setLoading] = useState(true);
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [channels, setChannels] = useState<ChannelBinding[]>([]);
  const [templates, setTemplates] = useState<AgentTemplate[]>([]);
  const [showWizard, setShowWizard] = useState(false);
  const [detailTab, setDetailTab] = useState<'overview' | 'interact' | 'tasks' | 'memory' | 'learning' | 'logs'>('overview');

  const refresh = useCallback(async () => {
    try {
      const agents = await fetchManagedAgents();
      setManagedAgents(agents);
    } catch {
      // Server may be down
    } finally {
      setLoading(false);
    }
  }, [setManagedAgents]);

  useEffect(() => {
    refresh();
    fetchTemplates().then(setTemplates).catch(() => {});
  }, [refresh]);

  const selectedAgent = managedAgents.find((a) => a.id === selectedAgentId);

  useEffect(() => {
    if (selectedAgentId) {
      fetchAgentTasks(selectedAgentId).then(setTasks).catch(() => setTasks([]));
      fetchAgentChannels(selectedAgentId).then(setChannels).catch(() => setChannels([]));
    }
  }, [selectedAgentId]);

  const handlePause = async (id: string) => {
    await pauseManagedAgent(id).catch(() => {});
    await refresh();
  };

  const handleResume = async (id: string) => {
    await resumeManagedAgent(id).catch(() => {});
    await refresh();
  };

  const handleDelete = async (id: string) => {
    await deleteManagedAgent(id).catch(() => {});
    if (selectedAgentId === id) setSelectedAgentId(null);
    await refresh();
  };

  const handleRun = async (id: string) => {
    await runManagedAgent(id).catch(() => {});
    await refresh();
  };

  const handleRecover = async (id: string) => {
    await recoverManagedAgent(id).catch(() => {});
    await refresh();
  };

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center" style={{ color: 'var(--color-text-tertiary)' }}>
        Loading agents...
      </div>
    );
  }

  // ── Detail View ─────────────────────────────────────────────────────────

  if (selectedAgent) {
    const successRate =
      tasks.length > 0
        ? Math.round((tasks.filter((t) => t.status === 'completed').length / tasks.length) * 100)
        : null;

    const DETAIL_TABS = [
      { id: 'overview', label: 'Overview', icon: Activity },
      { id: 'interact', label: 'Interact', icon: MessageSquare },
      { id: 'tasks', label: 'Tasks', icon: ListTodo },
      { id: 'memory', label: 'Memory', icon: Brain },
      { id: 'learning', label: 'Learning', icon: Settings },
      { id: 'logs', label: 'Logs', icon: FileText },
    ] as const;

    return (
      <div className="flex-1 overflow-y-auto p-6">
        {/* Back button */}
        <button
          onClick={() => setSelectedAgentId(null)}
          className="flex items-center gap-1 mb-4 text-sm cursor-pointer"
          style={{ color: 'var(--color-text-secondary)' }}
        >
          <ChevronLeft size={16} /> Back to agents
        </button>

        {/* Header */}
        <div className="flex items-start justify-between mb-6">
          <div className="flex items-center gap-3">
            <Bot size={24} style={{ color: 'var(--color-accent)' }} />
            <div>
              <h1 className="text-xl font-semibold" style={{ color: 'var(--color-text)' }}>
                {selectedAgent.name}
              </h1>
              <div className="flex items-center gap-2 mt-1">
                <StatusBadge status={selectedAgent.status} />
                <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                  {selectedAgent.agent_type}
                </span>
              </div>
            </div>
          </div>
          {/* Header actions */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => handleRun(selectedAgent.id)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm cursor-pointer font-medium"
              style={{ background: 'var(--color-accent)', color: '#fff' }}
            >
              <Zap size={13} /> Run Now
            </button>
            {(selectedAgent.status === 'running' || selectedAgent.status === 'idle') && (
              <button
                onClick={() => handlePause(selectedAgent.id)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm cursor-pointer"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              >
                <Pause size={13} /> Pause
              </button>
            )}
            {selectedAgent.status === 'paused' && (
              <button
                onClick={() => handleResume(selectedAgent.id)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm cursor-pointer"
                style={{ background: '#22c55e20', color: '#22c55e', border: '1px solid #22c55e40' }}
              >
                <Play size={13} /> Resume
              </button>
            )}
            {(selectedAgent.status === 'error' || selectedAgent.status === 'stalled' || selectedAgent.status === 'needs_attention') && (
              <button
                onClick={() => handleRecover(selectedAgent.id)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm cursor-pointer"
                style={{ background: '#ef444420', color: '#ef4444', border: '1px solid #ef444440' }}
              >
                <AlertTriangle size={13} /> Recover
              </button>
            )}
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 mb-6 p-1 rounded-lg overflow-x-auto" style={{ background: 'var(--color-bg-secondary)' }}>
          {DETAIL_TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setDetailTab(id)}
              className="px-3 py-2 rounded-md text-xs flex items-center gap-1.5 whitespace-nowrap cursor-pointer transition-colors"
              style={{
                background: detailTab === id ? 'var(--color-bg)' : 'transparent',
                color: detailTab === id ? 'var(--color-text)' : 'var(--color-text-secondary)',
                fontWeight: detailTab === id ? 500 : 400,
              }}
            >
              <Icon size={13} />
              {label}
            </button>
          ))}
        </div>

        {/* Tab: Overview */}
        {detailTab === 'overview' && (
          <div className="space-y-4">
            {/* Stat cards */}
            <div className="grid grid-cols-3 gap-3">
              {[
                {
                  label: 'Total Runs',
                  value: String(selectedAgent.total_runs ?? 0),
                  icon: Activity,
                  color: '#3b82f6',
                },
                {
                  label: 'Success Rate',
                  value: successRate !== null ? `${successRate}%` : '—',
                  icon: Zap,
                  color: '#22c55e',
                },
                {
                  label: 'Total Cost',
                  value: formatCost(selectedAgent.total_cost),
                  icon: DollarSign,
                  color: '#f59e0b',
                },
              ].map(({ label, value, icon: Icon, color }) => (
                <div
                  key={label}
                  className="p-4 rounded-lg"
                  style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <Icon size={14} style={{ color }} />
                    <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                      {label}
                    </span>
                  </div>
                  <p className="text-xl font-semibold" style={{ color: 'var(--color-text)' }}>
                    {value}
                  </p>
                </div>
              ))}
            </div>

            {/* Config display */}
            <div
              className="p-4 rounded-lg"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--color-text-secondary)' }}>
                Configuration
              </h3>
              <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
                {[
                  ['Agent Type', selectedAgent.agent_type],
                  ['Schedule', formatSchedule(selectedAgent.schedule_type, selectedAgent.schedule_value)],
                  ['Last Run', formatRelativeTime(selectedAgent.last_run_at)],
                  ['Budget', selectedAgent.budget ? formatCost(selectedAgent.budget) : 'Unlimited'],
                  ['Learning', selectedAgent.learning_enabled ? 'Enabled' : 'Disabled'],
                  ['Total Tokens', String(selectedAgent.total_tokens ?? 0)],
                ].map(([k, v]) => (
                  <div key={k} className="flex gap-2">
                    <span style={{ color: 'var(--color-text-tertiary)', minWidth: 90 }}>{k}</span>
                    <span style={{ color: 'var(--color-text)' }}>{v}</span>
                  </div>
                ))}
              </div>
              <div className="mt-3 pt-3" style={{ borderTop: '1px solid var(--color-border)' }}>
                <span className="text-xs font-mono" style={{ color: 'var(--color-text-tertiary)' }}>
                  ID: {selectedAgent.id}
                </span>
              </div>
            </div>

            {/* Channels summary */}
            {channels.length > 0 && (
              <div
                className="p-4 rounded-lg"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
              >
                <h3 className="text-sm font-medium mb-2" style={{ color: 'var(--color-text-secondary)' }}>
                  Channel Bindings
                </h3>
                {channels.map((b) => (
                  <div key={b.id} className="text-sm py-1" style={{ color: 'var(--color-text)' }}>
                    {b.channel_type}: {b.routing_mode}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Tab: Interact */}
        {detailTab === 'interact' && <InteractTab agentId={selectedAgent.id} />}

        {/* Tab: Tasks */}
        {detailTab === 'tasks' && (
          <div className="space-y-2">
            {tasks.map((t) => (
              <div
                key={t.id}
                className="p-3 rounded-lg"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
              >
                <div className="flex justify-between items-start gap-3">
                  <span className="text-sm" style={{ color: 'var(--color-text)' }}>
                    {t.description}
                  </span>
                  <span
                    className="text-xs px-2 py-0.5 rounded flex-shrink-0"
                    style={{
                      background: statusColor(t.status) + '20',
                      color: statusColor(t.status),
                    }}
                  >
                    {t.status}
                  </span>
                </div>
              </div>
            ))}
            {tasks.length === 0 && (
              <div className="text-sm py-8 text-center" style={{ color: 'var(--color-text-tertiary)' }}>
                No tasks assigned.
              </div>
            )}
          </div>
        )}

        {/* Tab: Memory */}
        {detailTab === 'memory' && (
          <div
            className="p-4 rounded-lg"
            style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
          >
            <h3 className="text-sm font-medium mb-3 flex items-center gap-2" style={{ color: 'var(--color-text-secondary)' }}>
              <Brain size={14} /> Summary Memory
            </h3>
            <p className="whitespace-pre-wrap text-sm" style={{ color: 'var(--color-text)' }}>
              {selectedAgent.summary_memory || 'Agent has no stored memory yet.'}
            </p>
          </div>
        )}

        {/* Tab: Learning */}
        {detailTab === 'learning' && (
          <LearningTab agentId={selectedAgent.id} learningEnabled={!!selectedAgent.learning_enabled} />
        )}

        {/* Tab: Logs */}
        {detailTab === 'logs' && (
          <LogsTab agentId={selectedAgent.id} />
        )}
      </div>
    );
  }

  // ── List View ───────────────────────────────────────────────────────────

  return (
    <div className="flex-1 overflow-y-auto p-6">
      {/* Launch wizard modal */}
      {showWizard && (
        <LaunchWizard
          templates={templates}
          onClose={() => setShowWizard(false)}
          onLaunched={() => {
            setShowWizard(false);
            refresh();
          }}
        />
      )}

      <div className="flex justify-between items-center mb-6">
        <h1 className="text-xl font-semibold" style={{ color: 'var(--color-text)' }}>
          Agents
        </h1>
        <button
          onClick={() => setShowWizard(true)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium cursor-pointer transition-colors"
          style={{ background: 'var(--color-accent)', color: '#fff' }}
        >
          <Plus size={15} /> New Agent
        </button>
      </div>

      {/* Agent cards grid */}
      <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))' }}>
        {managedAgents.map((a) => (
          <AgentCard
            key={a.id}
            agent={a}
            onClick={() => {
              setSelectedAgentId(a.id);
              setDetailTab('overview');
            }}
            onPause={handlePause}
            onResume={handleResume}
            onRun={handleRun}
            onRecover={handleRecover}
            onDelete={handleDelete}
          />
        ))}
      </div>

      {managedAgents.length === 0 && (
        <div className="text-center py-16" style={{ color: 'var(--color-text-tertiary)' }}>
          <Bot size={48} className="mx-auto mb-4 opacity-30" />
          <p className="mb-2 font-medium" style={{ color: 'var(--color-text-secondary)' }}>
            No agents yet
          </p>
          <p className="text-sm mb-6">Create your first agent to get started with autonomous task management.</p>
          <button
            onClick={() => setShowWizard(true)}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium cursor-pointer"
            style={{ background: 'var(--color-accent)', color: '#fff' }}
          >
            <Plus size={15} /> Launch your first agent
          </button>
        </div>
      )}
    </div>
  );
}
