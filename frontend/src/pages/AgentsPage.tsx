import { useEffect, useState, useCallback, useRef } from 'react';
import { toast } from 'sonner';
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
  fetchManagedAgent,
  fetchAvailableTools,
  saveToolCredentials,
  fetchModels,
  updateManagedAgent,
} from '../lib/api';
import type { AgentTask, ChannelBinding, AgentTemplate, AgentMessage, ManagedAgent, LearningLogEntry, AgentTrace, ToolInfo } from '../lib/api';
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
  return `$${cost.toFixed(4)}`;
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
  if (type === 'interval' && value) {
    const total = parseInt(value);
    if (!isNaN(total) && total > 0) {
      const h = Math.floor(total / 3600);
      const m = Math.floor((total % 3600) / 60);
      const s = total % 60;
      const parts: string[] = [];
      if (h > 0) parts.push(`${h}h`);
      if (m > 0) parts.push(`${m}m`);
      if (s > 0) parts.push(`${s}s`);
      return `Every ${parts.join(' ') || '0s'}`;
    }
    return `Every ${value}`;
  }
  return type || 'Manual';
}

// ---------------------------------------------------------------------------
// Launch Wizard
// ---------------------------------------------------------------------------

const CATEGORY_MAP: Record<string, string> = {
  communication: 'Communication',
  channel: 'Communication',
  search: 'Search & Browse',
  browser: 'Search & Browse',
  code: 'Code & Dev',
  system: 'Code & Dev',
  filesystem: 'Files & Data',
  memory: 'Memory & Knowledge',
  knowledge_graph: 'Memory & Knowledge',
  reasoning: 'Reasoning & AI',
  math: 'Reasoning & AI',
  inference: 'Reasoning & AI',
  agents: 'Reasoning & AI',
  media: 'Media',
};

const TOOL_NAME_FALLBACK: Record<string, string> = {
  file_read: 'Files & Data',
  file_write: 'Files & Data',
  pdf_extract: 'Files & Data',
  db_query: 'Files & Data',
  http_request: 'Files & Data',
  apply_patch: 'Code & Dev',
  git_status: 'Code & Dev',
  git_diff: 'Code & Dev',
  git_log: 'Code & Dev',
  git_commit: 'Code & Dev',
  channel_send: 'Communication',
  channel_list: 'Communication',
  channel_status: 'Communication',
};

const CATEGORY_ORDER = [
  'Communication', 'Search & Browse', 'Code & Dev', 'Files & Data',
  'Memory & Knowledge', 'Reasoning & AI', 'Media',
];

const POPULAR_TOOLS = new Set([
  'slack', 'email', 'telegram', 'whatsapp',
  'web_search', 'browser',
  'code_interpreter', 'shell_exec', 'git_status', 'git_diff',
  'file_read', 'file_write', 'pdf_extract',
  'retrieval', 'memory_store',
  'think', 'llm', 'calculator',
  'image_generate',
]);

const BROWSER_SUB_TOOLS = [
  'browser_navigate', 'browser_click', 'browser_type',
  'browser_screenshot', 'browser_extract', 'browser_axtree',
];

function parseIntervalParts(val: string): { hours: number; minutes: number; seconds: number } {
  const total = parseInt(val) || 0;
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return { hours, minutes, seconds };
}

function serializeInterval(hours: number, minutes: number, seconds: number): string {
  return String(hours * 3600 + minutes * 60 + seconds);
}

interface WizardState {
  step: number;
  templateId: string;
  name: string;
  instruction: string;
  model: string;
  scheduleType: string;
  scheduleValue: string;
  selectedTools: string[];
  budget: string;
  routerPolicy: string;
  memoryExtraction: string;
  observationCompression: string;
  retrievalStrategy: string;
  taskDecomposition: string;
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
    instruction: '',
    model: '',
    scheduleType: 'manual',
    scheduleValue: '',
    selectedTools: [],
    budget: '',
    routerPolicy: '',
    memoryExtraction: 'causality_graph',
    observationCompression: 'summarize',
    retrievalStrategy: 'hybrid_with_self_eval',
    taskDecomposition: 'phased',
  });
  const [launching, setLaunching] = useState(false);
  const models = useAppStore((s) => s.models);
  const [availableTools, setAvailableTools] = useState<ToolInfo[]>([]);
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set());
  const [credentialInputs, setCredentialInputs] = useState<Record<string, Record<string, string>>>({});
  const [savingCredentials, setSavingCredentials] = useState<string | null>(null);

  useEffect(() => {
    fetchAvailableTools().then(setAvailableTools).catch(() => {});
  }, []);

  function getToolCategory(tool: ToolInfo): string {
    if (tool.category && CATEGORY_MAP[tool.category]) return CATEGORY_MAP[tool.category];
    if (TOOL_NAME_FALLBACK[tool.name]) return TOOL_NAME_FALLBACK[tool.name];
    return 'Reasoning & AI';
  }

  function toggleCategory(cat: string) {
    setExpandedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  }

  function handleToggleTool(name: string) {
    if (name === 'browser') {
      const has = BROWSER_SUB_TOOLS.every((t) => wizard.selectedTools.includes(t));
      if (has) {
        update({ selectedTools: wizard.selectedTools.filter((t) => !BROWSER_SUB_TOOLS.includes(t)) });
      } else {
        update({ selectedTools: [...new Set([...wizard.selectedTools, ...BROWSER_SUB_TOOLS])] });
      }
    } else {
      toggleTool(name);
    }
  }

  async function handleSaveCredentials(toolName: string) {
    const inputs = credentialInputs[toolName];
    if (!inputs) return;
    setSavingCredentials(toolName);
    try {
      await saveToolCredentials(toolName, inputs);
      toast.success(`Credentials saved for ${toolName}`);
      const updated = await fetchAvailableTools();
      setAvailableTools(updated);
    } catch (err: any) {
      toast.error(err.message || 'Failed to save credentials');
    } finally {
      setSavingCredentials(null);
    }
  }

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
    if ((wizard.scheduleType === 'cron' || wizard.scheduleType === 'interval') && !wizard.instruction.trim()) {
      toast.error('Instruction is required for scheduled agents');
      return;
    }
    if (!wizard.name.trim()) {
      toast.error('Agent name is required');
      return;
    }
    setLaunching(true);
    try {
      const config: Record<string, unknown> = {
        schedule_type: wizard.scheduleType,
        schedule_value: wizard.scheduleValue || undefined,
        tools: wizard.selectedTools,
        learning_enabled: !!wizard.routerPolicy,
      };
      if (wizard.budget) config.budget = parseFloat(wizard.budget);
      if (wizard.instruction.trim()) config.instruction = wizard.instruction.trim();
      if (wizard.model) config.model = wizard.model;
      if (wizard.routerPolicy) config.router_policy = wizard.routerPolicy;
      config.memory_extraction = wizard.memoryExtraction;
      config.observation_compression = wizard.observationCompression;
      config.retrieval_strategy = wizard.retrievalStrategy;
      config.task_decomposition = wizard.taskDecomposition;
      const created = await createManagedAgent({
        name: wizard.name,
        template_id: wizard.templateId || undefined,
        config,
      });
      toast.success(`Agent "${wizard.name}" launched`);
      // Auto-run first tick for interval agents
      if (wizard.scheduleType === 'interval' && created.id) {
        runManagedAgent(created.id).catch(() => {});
      }
      onLaunched();
    } catch (err) {
      toast.error('Could not create agent', {
        description: 'Agent manager endpoint not available. Check that agent_manager.enabled = true in your config.',
      });
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

              {/* Instruction */}
              <div>
                <div className="text-xs mb-1" style={{ color: 'var(--color-text-secondary)' }}>
                  What should this agent do?
                  {(wizard.scheduleType === 'cron' || wizard.scheduleType === 'interval') && (
                    <span style={{ color: 'var(--color-error)' }}> *</span>
                  )}
                </div>
                <textarea
                  value={wizard.instruction}
                  onChange={(e) => update({ instruction: e.target.value })}
                  placeholder="e.g. Monitor my inbox and summarize new emails every hour"
                  rows={3}
                  className="w-full text-sm px-3 py-2 rounded-lg outline-none resize-none"
                  style={{
                    background: 'var(--color-bg-secondary)',
                    color: 'var(--color-text)',
                    border: '1px solid var(--color-border)',
                  }}
                />
                <div className="text-[10px] mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
                  This instruction runs every tick. Tasks are optional one-off goals.
                </div>
              </div>

              {/* Model */}
              <div>
                <div className="text-xs mb-1" style={{ color: 'var(--color-text-secondary)' }}>Intelligence (Model)</div>
                <select
                  value={wizard.model}
                  onChange={(e) => update({ model: e.target.value })}
                  className="w-full text-sm px-3 py-2 rounded-lg outline-none cursor-pointer"
                  style={{
                    background: 'var(--color-bg-secondary)',
                    color: 'var(--color-text)',
                    border: '1px solid var(--color-border)',
                  }}
                >
                  <option value="">Server default</option>
                  {(() => {
                    const local = models.filter((m) => !m.id.includes('/') && !m.id.startsWith('gpt') && !m.id.startsWith('claude') && !m.id.startsWith('gemini'));
                    const cloud = models.filter((m) => m.id.includes('/') || m.id.startsWith('gpt') || m.id.startsWith('claude') || m.id.startsWith('gemini'));
                    const formatModel = (m: { id: string; context_length?: number; params?: string }) => {
                      const parts = [m.id];
                      if ((m as any).params) parts.push(`(${(m as any).params})`);
                      if ((m as any).context_length) parts.push(`${Math.round((m as any).context_length / 1024)}K ctx`);
                      return parts.join(' ');
                    };
                    return (
                      <>
                        {local.length > 0 && (
                          <optgroup label="Local (Running)">
                            {local.map((m) => (
                              <option key={m.id} value={m.id}>{formatModel(m)}</option>
                            ))}
                          </optgroup>
                        )}
                        {cloud.length > 0 && (
                          <optgroup label="Cloud">
                            {cloud.map((m) => (
                              <option key={m.id} value={m.id}>{formatModel(m)}</option>
                            ))}
                          </optgroup>
                        )}
                        {local.length === 0 && cloud.length === 0 && (
                          <option disabled>No models available — start an engine or add API keys</option>
                        )}
                      </>
                    );
                  })()}
                </select>
              </div>

              {/* Schedule */}
              <div>
                <div className="flex items-center gap-1.5 mb-1">
                  <label className="block text-xs font-medium" style={{ color: 'var(--color-text-secondary)' }}>
                    Schedule
                  </label>
                  <div className="relative group">
                    <span
                      className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full text-[9px] font-bold cursor-help"
                      style={{ background: 'var(--color-border)', color: 'var(--color-text-tertiary)' }}
                    >
                      i
                    </span>
                    <div
                      className="absolute left-0 bottom-full mb-1 w-64 p-2 rounded-lg text-xs hidden group-hover:block z-50"
                      style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
                    >
                      <div className="space-y-1.5">
                        <div><strong>Manual</strong> — Run only when you click &quot;Run Now&quot;</div>
                        <div><strong>Cron</strong> — UNIX cron schedule (e.g. <code>0 9 * * *</code> = daily at 9 AM)</div>
                        <div><strong>Interval</strong> — Fixed delay between runs for continuous monitoring</div>
                      </div>
                    </div>
                  </div>
                </div>
                <select
                  value={wizard.scheduleType}
                  onChange={(e) => update({ scheduleType: e.target.value, scheduleValue: '' })}
                  className="w-full px-3 py-2 rounded-lg text-sm"
                  style={{
                    background: 'var(--color-bg)',
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-text)',
                  }}
                >
                  <option value="manual">Manual — Run on demand only</option>
                  <option value="cron">Cron — Recurring fixed-time schedule</option>
                  <option value="interval">Interval — Fixed delay between runs</option>
                </select>
              </div>

              {/* Interval spinners */}
              {wizard.scheduleType === 'interval' && (
                <div>
                  <label className="block text-xs font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>
                    Run Every
                  </label>
                  <div className="grid grid-cols-3 gap-2">
                    {(['hours', 'minutes', 'seconds'] as const).map((unit) => {
                      const max = unit === 'hours' ? 999 : 59;
                      const vals = parseIntervalParts(wizard.scheduleValue);
                      return (
                        <div key={unit} className="flex flex-col">
                          <input
                            type="number"
                            min={0}
                            max={max}
                            value={vals[unit]}
                            onChange={(e) => {
                              const v = { ...vals, [unit]: Math.max(0, Math.min(max, parseInt(e.target.value) || 0)) };
                              update({ scheduleValue: serializeInterval(v.hours, v.minutes, v.seconds) });
                            }}
                            className="w-full px-2 py-2 rounded-lg text-sm text-center bg-transparent outline-none"
                            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                          />
                          <span className="text-[10px] text-center mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>{unit}</span>
                        </div>
                      );
                    })}
                  </div>
                  {wizard.scheduleValue && parseInt(wizard.scheduleValue) > 0 && parseInt(wizard.scheduleValue) < 10 && (
                    <div className="text-[10px] mt-1" style={{ color: 'var(--color-error)' }}>
                      Minimum interval is 10 seconds
                    </div>
                  )}
                </div>
              )}

              {/* Cron input */}
              {wizard.scheduleType === 'cron' && (
                <div>
                  <div className="flex items-center gap-1.5 mb-1">
                    <label className="block text-xs font-medium" style={{ color: 'var(--color-text-secondary)' }}>
                      Cron Expression
                    </label>
                    <div className="relative group">
                      <span
                        className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full text-[9px] font-bold cursor-help"
                        style={{ background: 'var(--color-border)', color: 'var(--color-text-tertiary)' }}
                      >
                        i
                      </span>
                      <div
                        className="absolute left-0 bottom-full mb-1 w-52 p-2 rounded-lg text-xs hidden group-hover:block z-50"
                        style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
                      >
                        <div className="space-y-1">
                          <div><code>0 * * * *</code> — Every hour</div>
                          <div><code>0 9 * * *</code> — Daily at 9 AM</div>
                          <div><code>0 9 * * 1</code> — Mondays at 9 AM</div>
                        </div>
                      </div>
                    </div>
                  </div>
                  <input
                    type="text"
                    placeholder="0 * * * *"
                    value={wizard.scheduleValue}
                    onChange={(e) => update({ scheduleValue: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg text-sm bg-transparent outline-none"
                    style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                  />
                </div>
              )}

              <div>
                <label className="block text-xs font-medium mb-2" style={{ color: 'var(--color-text-secondary)' }}>
                  Tools &amp; Channels
                </label>
                {(() => {
                  const unconfiguredSelected = wizard.selectedTools.filter((t) => {
                    const tool = availableTools.find((at) => at.name === t);
                    return tool && tool.requires_credentials && !tool.configured;
                  });
                  return unconfiguredSelected.length > 0 ? (
                    <div className="text-[10px] mb-2 px-2 py-1 rounded" style={{ background: '#f59e0b20', color: '#f59e0b' }}>
                      {unconfiguredSelected.length} tool{unconfiguredSelected.length > 1 ? 's' : ''} need setup — credentials required before they will work
                    </div>
                  ) : null;
                })()}
                <div className="space-y-3 max-h-64 overflow-y-auto">
                  {CATEGORY_ORDER.map((cat) => {
                    const catTools = availableTools.filter((t) => getToolCategory(t) === cat);
                    if (catTools.length === 0) return null;
                    const popular = catTools.filter((t) => POPULAR_TOOLS.has(t.name));
                    const rest = catTools.filter((t) => !POPULAR_TOOLS.has(t.name));
                    const isExpanded = expandedCategories.has(cat);
                    const shown = isExpanded ? catTools : popular;

                    return (
                      <div key={cat}>
                        <div
                          className="flex items-center justify-between cursor-pointer mb-1"
                          onClick={() => rest.length > 0 && toggleCategory(cat)}
                        >
                          <span className="text-[10px] font-semibold uppercase tracking-wide" style={{ color: 'var(--color-text-tertiary)' }}>
                            {cat} ({catTools.length})
                          </span>
                          {rest.length > 0 && (
                            <span className="text-[10px]" style={{ color: 'var(--color-accent)' }}>
                              {isExpanded ? 'Show less' : `Show all (${catTools.length})`}
                            </span>
                          )}
                        </div>
                        <div className="grid grid-cols-2 gap-1.5">
                          {shown.map((tool) => {
                            const isSelected = tool.name === 'browser'
                              ? BROWSER_SUB_TOOLS.every((t) => wizard.selectedTools.includes(t))
                              : wizard.selectedTools.includes(tool.name);
                            const needsSetup = tool.requires_credentials && !tool.configured;
                            return (
                              <div key={tool.name}>
                                <button
                                  type="button"
                                  onClick={() => handleToggleTool(tool.name)}
                                  className="w-full text-left p-2 rounded-lg text-xs transition-colors cursor-pointer"
                                  style={{
                                    background: isSelected ? 'var(--color-accent)' + '10' : 'var(--color-bg-secondary)',
                                    border: `1px solid ${isSelected ? 'var(--color-accent)' + '50' : 'var(--color-border)'}`,
                                    color: 'var(--color-text)',
                                  }}
                                >
                                  <div className="flex items-center gap-1.5">
                                    {isSelected && <span style={{ color: 'var(--color-accent)' }}>&#10003;</span>}
                                    <span className="font-medium">{tool.name.replace(/_/g, ' ')}</span>
                                    {needsSetup && <span className="w-1.5 h-1.5 rounded-full inline-block" style={{ background: '#f59e0b' }} />}
                                  </div>
                                  {tool.description && (
                                    <div className="text-[10px] mt-0.5 truncate" style={{ color: 'var(--color-text-tertiary)' }}>
                                      {tool.description.slice(0, 60)}
                                    </div>
                                  )}
                                </button>
                                {isSelected && needsSetup && (
                                  <div className="mt-1 p-2 rounded-lg text-xs space-y-1.5" style={{ background: 'var(--color-bg)', border: '1px solid #f59e0b40' }}>
                                    {tool.credential_keys.map((key) => (
                                      <div key={key}>
                                        <label className="block text-[10px] mb-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
                                          {key.replace(/_/g, ' ')}
                                        </label>
                                        <input
                                          type="password"
                                          value={credentialInputs[tool.name]?.[key] || ''}
                                          onChange={(e) => setCredentialInputs((prev) => ({
                                            ...prev,
                                            [tool.name]: { ...prev[tool.name], [key]: e.target.value },
                                          }))}
                                          className="w-full px-2 py-1 rounded text-xs bg-transparent outline-none"
                                          style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                                          placeholder={`Enter ${key}`}
                                        />
                                      </div>
                                    ))}
                                    <button
                                      type="button"
                                      onClick={() => handleSaveCredentials(tool.name)}
                                      disabled={savingCredentials === tool.name}
                                      className="px-2 py-1 rounded text-[10px] font-medium cursor-pointer"
                                      style={{ background: 'var(--color-accent)', color: 'white' }}
                                    >
                                      {savingCredentials === tool.name ? 'Saving...' : 'Save'}
                                    </button>
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>
                    Budget (optional)
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
                  <div className="text-[10px] mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
                    Cloud API models only (OpenAI, Anthropic, Google). Local models have no cost.
                  </div>
                </div>
                <div>
                  <div className="flex items-center gap-1.5 mb-1">
                    <label className="block text-xs font-medium" style={{ color: 'var(--color-text-secondary)' }}>
                      Learning
                    </label>
                    <div className="relative group">
                      <span
                        className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full text-[9px] font-bold cursor-help"
                        style={{ background: 'var(--color-border)', color: 'var(--color-text-tertiary)' }}
                      >
                        i
                      </span>
                      <div
                        className="absolute right-0 bottom-full mb-1 w-56 p-2 rounded-lg text-xs hidden group-hover:block z-50"
                        style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
                      >
                        Router policies let the agent learn which model works best for different query types over time.
                      </div>
                    </div>
                  </div>
                  <select
                    value={wizard.routerPolicy}
                    onChange={(e) => update({ routerPolicy: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg text-sm"
                    style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                  >
                    <option value="">None — Always use selected model</option>
                    <option value="heuristic">Heuristic — Rule-based model selection</option>
                    <option value="learned">Trace-Driven — Learns from past runs</option>
                  </select>
                </div>
              </div>
              {/* Agent Strategies — shown for monitor_operative (default when no template selected) */}
              {(!wizard.templateId || templates.find((t) => t.id === wizard.templateId)?.agent_type === 'monitor_operative') && (
                <div>
                  <div className="flex items-center gap-1.5 mb-1">
                    <label className="block text-xs font-medium" style={{ color: 'var(--color-text-secondary)' }}>
                      Agent Strategies
                    </label>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    {([
                      { label: 'Memory Extraction', key: 'memoryExtraction' as const, tooltip: 'How the agent stores findings between runs',
                        options: [['causality_graph', 'Causality Graph'], ['scratchpad', 'Scratchpad'], ['structured_json', 'Structured JSON'], ['none', 'None']] },
                      { label: 'Observation Compression', key: 'observationCompression' as const, tooltip: 'How long tool outputs are compressed',
                        options: [['summarize', 'Summarize'], ['truncate', 'Truncate'], ['none', 'None']] },
                      { label: 'Retrieval Strategy', key: 'retrievalStrategy' as const, tooltip: 'How the agent retrieves past context',
                        options: [['hybrid_with_self_eval', 'Hybrid + Self-Eval'], ['keyword', 'Keyword'], ['semantic', 'Semantic'], ['none', 'None']] },
                      { label: 'Task Decomposition', key: 'taskDecomposition' as const, tooltip: 'How complex instructions are broken down',
                        options: [['phased', 'Phased'], ['monolithic', 'Monolithic'], ['hierarchical', 'Hierarchical']] },
                    ] as const).map((s) => (
                      <div key={s.key}>
                        <div className="flex items-center gap-1 mb-0.5">
                          <span className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>{s.label}</span>
                          <div className="relative group">
                            <span className="inline-flex items-center justify-center w-3 h-3 rounded-full text-[8px] font-bold cursor-help"
                              style={{ background: 'var(--color-border)', color: 'var(--color-text-tertiary)' }}>i</span>
                            <div className="absolute left-0 bottom-full mb-1 w-48 p-1.5 rounded text-[10px] hidden group-hover:block z-50"
                              style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}>
                              {s.tooltip}
                            </div>
                          </div>
                        </div>
                        <select
                          value={wizard[s.key]}
                          onChange={(e) => update({ [s.key]: e.target.value } as Partial<WizardState>)}
                          className="w-full px-2 py-1.5 rounded text-xs"
                          style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                        >
                          {s.options.map(([val, label]) => (
                            <option key={val} value={val}>{label}</option>
                          ))}
                        </select>
                      </div>
                    ))}
                  </div>
                </div>
              )}
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
                  <span style={{ color: 'var(--color-text)' }}>{wizard.budget ? `$${wizard.budget}` : 'Unlimited (local models free)'}</span>
                </div>
                <div className="flex justify-between">
                  <span style={{ color: 'var(--color-text-tertiary)' }}>Learning</span>
                  <span style={{ color: 'var(--color-text)' }}>
                    {wizard.routerPolicy ? (wizard.routerPolicy === 'heuristic' ? 'Heuristic Router' : 'Trace-Driven Router') : 'Disabled'}
                  </span>
                </div>
                {wizard.routerPolicy && (
                  <div className="flex justify-between">
                    <span style={{ color: 'var(--color-text-tertiary)' }}>Strategies</span>
                    <span className="text-xs text-right" style={{ color: 'var(--color-text)' }}>
                      {wizard.memoryExtraction}, {wizard.observationCompression}, {wizard.retrievalStrategy}, {wizard.taskDecomposition}
                    </span>
                  </div>
                )}
              </div>
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
// Detail view — Configuration grid with editable model
// ---------------------------------------------------------------------------

function AgentConfigGrid({ agent, onAgentUpdated }: { agent: ManagedAgent; onAgentUpdated: () => void }) {
  const [editingModel, setEditingModel] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const currentModel = (agent.config?.model as string) || '(default)';

  async function startEditing() {
    try {
      const fetched = await fetchModels();
      setModels(fetched.map((m) => m.id));
    } catch {
      // ignore
    }
    setEditingModel(true);
  }

  async function changeModel(newModel: string) {
    try {
      const newConfig = { ...(agent.config || {}), model: newModel };
      await updateManagedAgent(agent.id, { config: newConfig });
      onAgentUpdated();
    } catch {
      // ignore
    }
    setEditingModel(false);
  }

  const rows: [string, React.ReactNode][] = [
    ['Intelligence', editingModel ? (
      <select
        autoFocus
        defaultValue={currentModel}
        onChange={(e) => changeModel(e.target.value)}
        onBlur={() => setEditingModel(false)}
        className="text-sm rounded px-1 py-0.5"
        style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
      >
        {models.map((m) => <option key={m} value={m}>{m}</option>)}
      </select>
    ) : (
      <span
        onClick={startEditing}
        className="cursor-pointer underline decoration-dotted"
        style={{ color: 'var(--color-accent)' }}
        title="Click to change model"
      >
        {currentModel}
      </span>
    )],
    ['Agent Type', <span key="at">{agent.agent_type}</span>],
    ['Schedule', <span key="sc">{formatSchedule(agent.schedule_type, agent.schedule_value)}</span>],
    ['Last Run', <span key="lr">{formatRelativeTime(agent.last_run_at)}</span>],
    ['Budget', <span key="bg">{agent.budget ? formatCost(agent.budget) : 'Unlimited'}</span>],
    ['Learning', <span key="le">{agent.learning_enabled ? 'Enabled' : 'Disabled'}</span>],
    ['Input Tokens', <span key="it">{String(agent.input_tokens ?? 0)}</span>],
    ['Output Tokens', <span key="ot">{String(agent.output_tokens ?? 0)}</span>],
  ];

  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-1.5">
      {rows.map(([label, value]) => (
        <div key={label as string} className="flex gap-2 items-center text-sm">
          <span className="font-medium" style={{ color: 'var(--color-text-secondary)', minWidth: 110 }}>{label}</span>
          <span style={{ color: 'var(--color-text)' }}>{value}</span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detail view — Interact tab
// ---------------------------------------------------------------------------

function InteractTab({ agentId, agentStatus }: { agentId: string; agentStatus: string }) {
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [currentActivity, setCurrentActivity] = useState('');
  const [liveStatus, setLiveStatus] = useState(agentStatus);
  const bottomRef = useRef<HTMLDivElement>(null);

  const loadData = useCallback(async () => {
    try {
      const [msgs, agent] = await Promise.all([
        fetchAgentMessages(agentId),
        fetchManagedAgent(agentId),
      ]);
      setMessages(msgs);
      setLiveStatus(agent.status);
      setCurrentActivity(agent.current_activity || '');
    } catch {
      // ignore
    }
  }, [agentId]);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 2000);
    return () => clearInterval(interval);
  }, [loadData]);

  useEffect(() => { setLiveStatus(agentStatus); }, [agentStatus]);

  // Scroll to bottom only on initial load, not on every poll update.
  const hasScrolled = useRef(false);
  useEffect(() => {
    if (!hasScrolled.current && messages.length > 0) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
      hasScrolled.current = true;
    }
  }, [messages]);

  async function handleSend(mode: 'immediate' | 'queued') {
    if (!input.trim()) return;
    setSending(true);
    try {
      await sendAgentMessage(agentId, input.trim(), mode);
      setInput('');
      await loadData();
    } catch {
      // ignore
    } finally {
      setSending(false);
    }
  }

  // Reverse so newest messages appear at the bottom (closest to input).
  // Filter out agent responses with empty content.
  const displayMessages = [...messages]
    .filter((m) => m.direction === 'user_to_agent' || m.content.trim())
    .reverse();

  const isAgentWorking = liveStatus === 'running';
  const hasPending = messages.some((m) => m.status === 'pending');

  return (
    <div className="flex flex-col h-full" style={{ minHeight: 320 }}>
      <div className="flex-1 overflow-y-auto space-y-3 pb-4" style={{ maxHeight: 400 }}>
        {displayMessages.length === 0 && !isAgentWorking && (
          <div className="text-sm text-center py-8" style={{ color: 'var(--color-text-tertiary)' }}>
            No messages yet. Send a message to interact with this agent.
          </div>
        )}
        {displayMessages.map((msg) => (
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
              <p className="text-xs mt-1 opacity-70">
                {msg.status === 'pending' ? 'sending...' : new Date(msg.created_at * 1000).toLocaleTimeString()}
              </p>
            </div>
          </div>
        ))}
        {/* Progress indicator with live activity from the executor */}
        {(isAgentWorking || hasPending) && (
          <div className="flex justify-start">
            <div
              className="px-3 py-2 rounded-lg text-sm"
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text-secondary)',
              }}
            >
              <div className="flex items-center gap-2">
                <span className="inline-block w-2 h-2 rounded-full animate-pulse" style={{ background: 'var(--color-accent)' }} />
                {sending ? 'Sending message...' : currentActivity || 'Agent is thinking...'}
              </div>
            </div>
          </div>
        )}
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
              handleSend('immediate');
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
          >
            <Send size={13} /> Send
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
  const [expandedTrace, setExpandedTrace] = useState<string | null>(null);

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
          {traces.map((t) => {
            const errorDetail = t.metadata?.error_detail as
              | { error_type: string; error_message: string; suggested_action: string }
              | undefined;
            const isError = t.outcome !== 'success';
            const isExpanded = expandedTrace === t.id;

            return (
              <div
                key={t.id}
                className="rounded-lg p-3 text-sm cursor-pointer"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
                onClick={() => isError && errorDetail && setExpandedTrace(isExpanded ? null : t.id)}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className="w-2 h-2 rounded-full inline-block"
                      style={{ background: t.outcome === 'success' ? '#22c55e' : '#ef4444' }}
                    />
                    <span style={{ color: 'var(--color-text)' }}>{t.outcome}</span>
                    {errorDetail && (
                      <span
                        className="text-[10px] px-1.5 py-0.5 rounded font-medium"
                        style={{
                          background: errorDetail.error_type === 'fatal' ? '#ef444420' :
                            errorDetail.error_type === 'escalate' ? '#f59e0b20' : '#3b82f620',
                          color: errorDetail.error_type === 'fatal' ? '#ef4444' :
                            errorDetail.error_type === 'escalate' ? '#f59e0b' : '#3b82f6',
                        }}
                      >
                        {errorDetail.error_type}
                      </span>
                    )}
                  </div>
                  <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                    {formatRelativeTime(t.started_at)}
                  </span>
                </div>
                <div className="flex items-center gap-3 mt-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                  <span>{t.duration.toFixed(1)}s</span>
                  <span>{t.steps} step{t.steps !== 1 ? 's' : ''}</span>
                </div>
                {isExpanded && errorDetail && (
                  <div className="mt-2 pt-2 space-y-1.5 text-xs" style={{ borderTop: '1px solid var(--color-border)' }}>
                    <div>
                      <span className="font-medium" style={{ color: 'var(--color-text-secondary)' }}>Error: </span>
                      <span style={{ color: 'var(--color-text)' }}>{errorDetail.error_message}</span>
                    </div>
                    <div>
                      <span className="font-medium" style={{ color: 'var(--color-text-secondary)' }}>Action: </span>
                      <span style={{ color: 'var(--color-text)' }}>{errorDetail.suggested_action}</span>
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

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------

export function AgentsPage() {
  const managedAgents = useAppStore((s) => s.managedAgents);
  const setManagedAgents = useAppStore((s) => s.setManagedAgents);
  const selectedAgentId = useAppStore((s) => s.selectedAgentId);
  const setSelectedAgentId = useAppStore((s) => s.setSelectedAgentId);
  const [loading, setLoading] = useState(true);
  const [agentManagerAvailable, setAgentManagerAvailable] = useState<boolean | null>(null);
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [channels, setChannels] = useState<ChannelBinding[]>([]);
  const [templates, setTemplates] = useState<AgentTemplate[]>([]);
  const [showWizard, setShowWizard] = useState(false);
  const [detailTab, setDetailTab] = useState<'overview' | 'interact' | 'tasks' | 'memory' | 'learning' | 'logs'>('overview');

  const refresh = useCallback(async () => {
    try {
      const agents = await fetchManagedAgents();
      setManagedAgents(agents);
      setAgentManagerAvailable(true);
    } catch (err: any) {
      if (err.message?.includes('404')) {
        setAgentManagerAvailable(false);
      }
      setManagedAgents([]);
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
    try {
      await runManagedAgent(id);
    } catch (err: any) {
      toast.error('Failed to start agent', {
        description: err.message || 'Unknown error',
      });
      await refresh();
      return;
    }
    await refresh();
    setTimeout(async () => {
      try {
        const agent = await fetchManagedAgent(id);
        if (agent.status === 'error') {
          toast.error(`Agent "${agent.name}" failed`, {
            description: agent.summary_memory?.replace(/^ERROR: /, '') || 'Unknown error',
          });
          useAppStore.getState().addLogEntry({
            timestamp: Date.now(), level: 'error', category: 'model',
            message: `Agent "${agent.name}" failed: ${agent.summary_memory || 'Unknown error'}`,
          });
        }
      } catch {}
      await refresh();
    }, 3000);
  };

  const handleRecover = async (id: string) => {
    try {
      const result = await recoverManagedAgent(id);
      if (result.checkpoint) {
        toast.success('Agent recovered from checkpoint');
      } else {
        toast.success('Agent reset to idle (no checkpoint available)');
      }
      setDetailTab('overview');
    } catch (err: any) {
      toast.error('Recovery failed', {
        description: err.message || 'Unknown error',
      });
    }
    await refresh();
  };

  const prevStatuses = useRef<Record<string, string>>({});
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const agents = await fetchManagedAgents();
        for (const agent of agents) {
          const prev = prevStatuses.current[agent.id];
          if (prev && prev !== 'error' && agent.status === 'error') {
            toast.error(`Agent "${agent.name}" failed`, {
              description: agent.summary_memory?.replace(/^ERROR: /, '') || 'Unknown error',
            });
          }
          prevStatuses.current[agent.id] = agent.status;
        }
      } catch {}
    }, 30000);
    return () => clearInterval(interval);
  }, []);

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
          <div className="space-y-3">
            {/* Stat cards — compact row */}
            <div className="grid grid-cols-3 gap-2">
              {[
                { label: 'Total Runs', value: String(selectedAgent.total_runs ?? 0), icon: Activity, color: '#3b82f6' },
                { label: 'Success Rate', value: successRate !== null ? `${successRate}%` : '—', icon: Zap, color: '#22c55e' },
                { label: 'Total Cost', value: formatCost(selectedAgent.total_cost), icon: DollarSign, color: '#f59e0b' },
              ].map(({ label, value, icon: Icon, color }) => (
                <div
                  key={label}
                  className="p-3 rounded-lg flex items-center gap-3"
                  style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
                >
                  <Icon size={16} style={{ color, flexShrink: 0 }} />
                  <div>
                    <p className="text-base font-semibold leading-tight" style={{ color: 'var(--color-text)' }}>{value}</p>
                    <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>{label}</p>
                  </div>
                </div>
              ))}
            </div>

            {/* Config display — tighter spacing */}
            <div
              className="p-3 rounded-lg"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <h3 className="text-sm font-semibold mb-2" style={{ color: 'var(--color-text)' }}>
                Configuration
              </h3>
              <AgentConfigGrid agent={selectedAgent} onAgentUpdated={refresh} />
              <div className="mt-2 pt-2" style={{ borderTop: '1px solid var(--color-border)' }}>
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
        {detailTab === 'interact' && <InteractTab agentId={selectedAgent.id} agentStatus={selectedAgent.status} />}

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
          onClick={() => agentManagerAvailable && setShowWizard(true)}
          disabled={agentManagerAvailable === false}
          className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium cursor-pointer transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          style={{
            background: agentManagerAvailable === false ? 'var(--color-bg-tertiary)' : 'var(--color-accent)',
            color: agentManagerAvailable === false ? 'var(--color-text-tertiary)' : '#fff',
          }}
        >
          <Plus size={15} /> New Agent
        </button>
      </div>

      {agentManagerAvailable === false && (
        <div
          className="mx-4 mt-2 px-4 py-3 rounded-lg flex items-center gap-3 text-sm"
          style={{
            background: 'var(--color-accent-amber-subtle)',
            border: '1px solid rgba(245, 158, 11, 0.2)',
            color: 'var(--color-accent-amber)',
          }}
        >
          <AlertTriangle size={16} />
          <span>Agent manager is not enabled. Set <code className="font-mono text-xs">agent_manager.enabled = true</code> in your config.</span>
        </div>
      )}

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
            onClick={() => agentManagerAvailable && setShowWizard(true)}
            disabled={agentManagerAvailable === false}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
            style={{
              background: agentManagerAvailable === false ? 'var(--color-bg-tertiary)' : 'var(--color-accent)',
              color: agentManagerAvailable === false ? 'var(--color-text-tertiary)' : '#fff',
            }}
          >
            <Plus size={15} /> Launch your first agent
          </button>
        </div>
      )}
    </div>
  );
}
