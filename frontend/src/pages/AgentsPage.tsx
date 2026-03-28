import { useEffect, useState, useCallback, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import { toast } from 'sonner';
import { useAppStore } from '../lib/store';
import {
  fetchManagedAgents,
  fetchAgentTasks,
  fetchAgentChannels,
  bindAgentChannel,
  unbindAgentChannel,
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
  fetchRecommendedModel,
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
  Wifi,
  Database,
  Copy,
  Check,
} from 'lucide-react';
import { SOURCE_CATALOG } from '../types/connectors';
import type { ConnectRequest } from '../types/connectors';
import { listConnectors, connectSource } from '../lib/connectors-api';

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
  step: 1 | 2;
  templateId: string;
  templateData: AgentTemplate | null;
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
  maxTurns: number;
  temperature: number;
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
  const UNIVERSAL_DEFAULTS = {
    memoryExtraction: 'structured_json',
    observationCompression: 'summarize',
    retrievalStrategy: 'sqlite',
    taskDecomposition: 'hierarchical',
    maxTurns: 25,
    temperature: 0.3,
  };

  const [wizard, setWizard] = useState<WizardState>({
    step: 1,
    templateId: '',
    templateData: null,
    name: '',
    instruction: '',
    model: '',
    scheduleType: 'manual',
    scheduleValue: '',
    selectedTools: [],
    budget: '',
    routerPolicy: '',
    ...UNIVERSAL_DEFAULTS,
  });
  const [launching, setLaunching] = useState(false);
  const [recommendedModel, setRecommendedModel] = useState('');
  const models = useAppStore((s) => s.models);

  useEffect(() => {
    fetchRecommendedModel().then((r) => {
      setRecommendedModel(r.model);
      if (!wizard.model) {
        setWizard((w) => ({ ...w, model: r.model }));
      }
    }).catch(() => {});
  }, []);

  function selectTemplate(tpl: AgentTemplate | null) {
    if (tpl) {
      setWizard((w) => ({
        ...w,
        step: 2,
        templateId: tpl.id,
        templateData: tpl,
        name: '',
        instruction: '',
        model: recommendedModel || w.model,
        scheduleType: (tpl as any).schedule_type || 'manual',
        scheduleValue: (tpl as any).schedule_value || '',
        selectedTools: (tpl as any).tools || [],
        memoryExtraction: (tpl as any).memory_extraction || UNIVERSAL_DEFAULTS.memoryExtraction,
        observationCompression: (tpl as any).observation_compression || UNIVERSAL_DEFAULTS.observationCompression,
        retrievalStrategy: (tpl as any).retrieval_strategy || UNIVERSAL_DEFAULTS.retrievalStrategy,
        taskDecomposition: (tpl as any).task_decomposition || UNIVERSAL_DEFAULTS.taskDecomposition,
        maxTurns: (tpl as any).max_turns || UNIVERSAL_DEFAULTS.maxTurns,
        temperature: (tpl as any).temperature ?? UNIVERSAL_DEFAULTS.temperature,
      }));
    } else {
      setWizard((w) => ({
        ...w,
        step: 2,
        templateId: '',
        templateData: null,
        name: '',
        instruction: '',
        model: recommendedModel || w.model,
        scheduleType: 'manual',
        scheduleValue: '',
        selectedTools: [],
        ...UNIVERSAL_DEFAULTS,
      }));
    }
  }

  async function handleLaunch() {
    if (!wizard.name.trim()) { toast.error('Name is required'); return; }
    setLaunching(true);
    try {
      const config: Record<string, unknown> = {
        schedule_type: wizard.scheduleType,
        schedule_value: wizard.scheduleValue || undefined,
        tools: wizard.selectedTools,
        learning_enabled: !!wizard.routerPolicy,
        memory_extraction: wizard.memoryExtraction,
        observation_compression: wizard.observationCompression,
        retrieval_strategy: wizard.retrievalStrategy,
        task_decomposition: wizard.taskDecomposition,
        max_turns: wizard.maxTurns,
        temperature: wizard.temperature,
      };
      if (wizard.budget) config.budget = parseFloat(wizard.budget);
      if (wizard.instruction.trim()) config.instruction = wizard.instruction.trim();
      if (wizard.model) config.model = wizard.model;
      if (wizard.routerPolicy) config.router_policy = wizard.routerPolicy;

      await createManagedAgent({
        name: wizard.name.trim(),
        template_id: wizard.templateId || undefined,
        config,
      });
      toast.success(`Agent "${wizard.name}" created`);
      onLaunched();
    } catch (err: any) {
      toast.error(err.message || 'Failed to create agent');
    } finally {
      setLaunching(false);
    }
  }

  const formatScheduleLabel = (type: string, value: string) => {
    if (type === 'manual') return 'Manual (run on demand)';
    if (type === 'cron') return `Cron: ${value}`;
    if (type === 'interval') {
      const secs = parseInt(value, 10);
      if (secs >= 3600) return `Every ${secs / 3600}h`;
      if (secs >= 60) return `Every ${secs / 60}m`;
      return `Every ${secs}s`;
    }
    return type;
  };

  // ── Step 1: Template Selection ──
  if (wizard.step === 1) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.6)' }}>
        <div className="rounded-xl p-6 w-full max-w-lg" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}>
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>New Agent — Choose Template</h2>
            <button onClick={onClose} className="p-1 rounded hover:bg-opacity-10" style={{ color: 'var(--color-text-tertiary)' }}><X size={18} /></button>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {templates.map((tpl) => (
              <button
                key={tpl.id}
                onClick={() => selectTemplate(tpl)}
                className="text-left p-4 rounded-lg transition-all items-start"
                style={{ border: '1px solid var(--color-border)', background: 'var(--color-bg-secondary)' }}
                onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--color-accent)'; e.currentTarget.style.background = 'rgba(124,58,237,0.06)'; }}
                onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--color-border)'; e.currentTarget.style.background = 'var(--color-bg-secondary)'; }}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-lg">{(tpl as any).icon || '🤖'}</span>
                  <span className="font-semibold text-sm" style={{ color: 'var(--color-text)' }}>{tpl.name}</span>
                </div>
                <div className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)', textAlign: 'left' }}>{tpl.description}</div>
                {(tpl as any).tools && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {((tpl as any).tools as string[]).slice(0, 4).map((t: string) => (
                      <span key={t} className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(124,58,237,0.12)', color: '#a78bfa' }}>{t}</span>
                    ))}
                    {((tpl as any).tools as string[]).length > 4 && (
                      <span className="text-xs px-1.5 py-0.5 rounded" style={{ color: 'var(--color-text-tertiary)' }}>+{((tpl as any).tools as string[]).length - 4}</span>
                    )}
                  </div>
                )}
              </button>
            ))}
            <button
              onClick={() => selectTemplate(null)}
              className="text-left p-4 rounded-lg transition-all items-start"
              style={{ border: '1px solid var(--color-border)', background: 'var(--color-bg-secondary)' }}
              onMouseEnter={(e) => { e.currentTarget.style.borderColor = 'var(--color-accent)'; e.currentTarget.style.background = 'rgba(124,58,237,0.06)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--color-border)'; e.currentTarget.style.background = 'var(--color-bg-secondary)'; }}
            >
              <div className="flex items-center gap-2 mb-1">
                <span className="text-lg">⚙️</span>
                <span className="font-semibold text-sm" style={{ color: 'var(--color-text)' }}>Custom Agent</span>
              </div>
              <div className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)', textAlign: 'left' }}>Start from scratch. Pick your own tools, schedule, and behavior.</div>
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── Step 2: Configuration ──
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.6)' }}>
      <div className="rounded-xl p-6 w-full max-w-lg max-h-[85vh] overflow-y-auto" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}>
        <div className="flex justify-between items-center mb-4">
          <div className="flex items-center gap-2">
            <button onClick={() => setWizard((w) => ({ ...w, step: 1 }))} className="p-1 rounded" style={{ color: 'var(--color-text-tertiary)' }}><ChevronLeft size={18} /></button>
            <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>
              {wizard.templateData ? `New ${wizard.templateData.name}` : 'New Custom Agent'}
            </h2>
          </div>
          <button onClick={onClose} className="p-1 rounded" style={{ color: 'var(--color-text-tertiary)' }}><X size={18} /></button>
        </div>

        <div className="space-y-4">
          {/* Name */}
          <div>
            <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>Agent Name</label>
            <input
              value={wizard.name}
              onChange={(e) => setWizard((w) => ({ ...w, name: e.target.value }))}
              placeholder="e.g. AI Research Tracker"
              className="w-full px-3 py-2 rounded-lg text-sm bg-transparent"
              style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
            />
          </div>

          {/* Instruction */}
          <div>
            <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>What should this agent do?</label>
            <textarea
              value={wizard.instruction}
              onChange={(e) => setWizard((w) => ({ ...w, instruction: e.target.value }))}
              placeholder="e.g. Monitor the latest research papers on reasoning and chain-of-thought in LLMs"
              rows={3}
              className="w-full px-3 py-2 rounded-lg text-sm bg-transparent resize-none"
              style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
            />
          </div>

          {/* Model + Schedule row */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>Intelligence</label>
              <select
                value={wizard.model}
                onChange={(e) => setWizard((w) => ({ ...w, model: e.target.value }))}
                className="w-full px-3 py-2 rounded-lg text-sm"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              >
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.id}{m.id === recommendedModel ? ' (recommended)' : ''}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>Schedule</label>
              <select
                value={wizard.scheduleType}
                onChange={(e) => setWizard((w) => ({ ...w, scheduleType: e.target.value, scheduleValue: e.target.value === 'manual' ? '' : w.scheduleValue }))}
                className="w-full px-3 py-2 rounded-lg text-sm"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              >
                <option value="manual">Manual (run on demand)</option>
                <option value="interval">Interval</option>
                <option value="cron">Cron</option>
              </select>
              {wizard.scheduleType === 'cron' && (
                <input
                  value={wizard.scheduleValue}
                  onChange={(e) => setWizard((w) => ({ ...w, scheduleValue: e.target.value }))}
                  placeholder="0 9 * * *"
                  className="w-full px-3 py-1.5 rounded-lg text-xs bg-transparent mt-1.5"
                  style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                />
              )}
              {wizard.scheduleType === 'interval' && (
                <div className="flex gap-2 mt-1.5">
                  <div className="flex items-center gap-1">
                    <input
                      type="number" min="0" max="24"
                      value={Math.floor(parseInt(wizard.scheduleValue || '0', 10) / 3600)}
                      onChange={(e) => {
                        const hrs = Math.min(24, Math.max(0, parseInt(e.target.value, 10) || 0));
                        const mins = Math.floor((parseInt(wizard.scheduleValue || '0', 10) % 3600) / 60);
                        setWizard((w) => ({ ...w, scheduleValue: String(hrs * 3600 + mins * 60) }));
                      }}
                      className="w-14 px-2 py-1 rounded text-xs text-center"
                      style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                    />
                    <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>hrs</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <input
                      type="number" min="0" max="59"
                      value={Math.floor((parseInt(wizard.scheduleValue || '0', 10) % 3600) / 60)}
                      onChange={(e) => {
                        const hrs = Math.floor(parseInt(wizard.scheduleValue || '0', 10) / 3600);
                        const mins = Math.min(59, Math.max(0, parseInt(e.target.value, 10) || 0));
                        setWizard((w) => ({ ...w, scheduleValue: String(hrs * 3600 + mins * 60) }));
                      }}
                      className="w-14 px-2 py-1 rounded text-xs text-center"
                      style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                    />
                    <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>min</span>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Tools tags */}
          {wizard.selectedTools.length > 0 && (
            <div>
              <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>
                Tools <span style={{ color: 'var(--color-text-tertiary)', fontWeight: 400 }}>(from template)</span>
              </label>
              <div className="flex flex-wrap gap-1.5">
                {wizard.selectedTools.map((t) => (
                  <span key={t} className="text-xs px-2 py-1 rounded" style={{ background: 'rgba(124,58,237,0.12)', color: '#a78bfa' }}>{t}</span>
                ))}
              </div>
            </div>
          )}

          {/* Advanced Settings */}
          <details className="rounded-lg" style={{ border: '1px solid var(--color-border)' }}>
            <summary className="px-3 py-2 cursor-pointer text-sm font-medium" style={{ color: 'var(--color-text-tertiary)' }}>
              Advanced Settings
            </summary>
            <div className="px-3 pb-3 pt-1 space-y-3" style={{ borderTop: '1px solid var(--color-border)' }}>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Memory Extraction</label>
                  <select value={wizard.memoryExtraction} onChange={(e) => setWizard((w) => ({ ...w, memoryExtraction: e.target.value }))}
                    className="w-full px-2 py-1 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                    <option value="structured_json">Structured JSON</option>
                    <option value="causality_graph">Causality Graph</option>
                    <option value="scratchpad">Scratchpad</option>
                    <option value="none">None</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Observation Compression</label>
                  <select value={wizard.observationCompression} onChange={(e) => setWizard((w) => ({ ...w, observationCompression: e.target.value }))}
                    className="w-full px-2 py-1 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                    <option value="summarize">Summarize</option>
                    <option value="truncate">Truncate</option>
                    <option value="none">None</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Retrieval Strategy</label>
                  <select value={wizard.retrievalStrategy} onChange={(e) => setWizard((w) => ({ ...w, retrievalStrategy: e.target.value }))}
                    className="w-full px-2 py-1 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                    <option value="sqlite">BM25 (SQLite FTS5)</option>
                    <option value="hybrid">Hybrid (BM25 + Semantic)</option>
                    <option value="colbert">ColBERTv2</option>
                    <option value="none">None</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Task Decomposition</label>
                  <select value={wizard.taskDecomposition} onChange={(e) => setWizard((w) => ({ ...w, taskDecomposition: e.target.value }))}
                    className="w-full px-2 py-1 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                    <option value="hierarchical">Hierarchical</option>
                    <option value="phased">Phased</option>
                    <option value="monolithic">Monolithic</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Max Turns</label>
                  <input type="number" value={wizard.maxTurns} onChange={(e) => setWizard((w) => ({ ...w, maxTurns: parseInt(e.target.value, 10) || 25 }))}
                    className="w-full px-2 py-1 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
                </div>
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Temperature</label>
                  <input type="number" step="0.1" min="0" max="2" value={wizard.temperature}
                    onChange={(e) => setWizard((w) => ({ ...w, temperature: parseFloat(e.target.value) || 0.3 }))}
                    className="w-full px-2 py-1 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
                </div>
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Budget ($)</label>
                  <input type="number" step="0.01" value={wizard.budget} onChange={(e) => setWizard((w) => ({ ...w, budget: e.target.value }))}
                    placeholder="Unlimited"
                    className="w-full px-2 py-1 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
                </div>
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Schedule Type</label>
                  <select value={wizard.scheduleType} onChange={(e) => setWizard((w) => ({ ...w, scheduleType: e.target.value }))}
                    className="w-full px-2 py-1 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                    <option value="manual">Manual</option>
                    <option value="cron">Cron</option>
                    <option value="interval">Interval</option>
                  </select>
                </div>
              </div>
            </div>
          </details>

          {/* Launch */}
          <div className="flex gap-3 pt-2">
            <button
              onClick={handleLaunch}
              disabled={launching || !wizard.name.trim()}
              className="flex-1 py-2.5 rounded-lg text-sm font-semibold"
              style={{ background: 'var(--color-accent)', color: '#fff', opacity: launching || !wizard.name.trim() ? 0.5 : 1 }}
            >
              {launching ? 'Creating...' : 'Launch Agent'}
            </button>
            <button onClick={onClose} className="px-4 py-2.5 rounded-lg text-sm" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}>
              Cancel
            </button>
          </div>
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

function AgentInstructionSection({ agent, onAgentUpdated }: { agent: ManagedAgent; onAgentUpdated: () => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const currentInstruction = (agent.config?.instruction as string) || '';

  async function save() {
    try {
      const newConfig = { ...(agent.config || {}), instruction: draft.trim() };
      await updateManagedAgent(agent.id, { config: newConfig });
      onAgentUpdated();
    } catch { /* ignore */ }
    setEditing(false);
  }

  return (
    <div
      className="p-3 rounded-lg"
      style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
    >
      <div className="flex items-center gap-2 mb-2">
        <h3 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>Instruction</h3>
        {!editing && (
          <button
            onClick={() => { setDraft(currentInstruction); setEditing(true); }}
            className="text-xs px-2 py-0.5 rounded cursor-pointer"
            style={{ color: 'var(--color-accent)', border: '1px solid var(--color-accent)', opacity: 0.8 }}
          >
            Edit
          </button>
        )}
      </div>
      {editing ? (
        <div className="space-y-2">
          <textarea
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={3}
            className="w-full px-3 py-2 rounded-lg text-sm bg-transparent resize-none"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
          />
          <div className="flex gap-2">
            <button onClick={save} className="text-xs px-3 py-1 rounded font-medium cursor-pointer" style={{ background: 'var(--color-accent)', color: '#fff' }}>Save</button>
            <button onClick={() => setEditing(false)} className="text-xs px-3 py-1 rounded cursor-pointer" style={{ color: 'var(--color-text-tertiary)', border: '1px solid var(--color-border)' }}>Cancel</button>
          </div>
        </div>
      ) : (
        <p className="text-sm" style={{ color: currentInstruction ? 'var(--color-text)' : 'var(--color-text-tertiary)' }}>
          {currentInstruction || '(No instruction set — click Edit to add one)'}
        </p>
      )}
    </div>
  );
}

function AgentConfigGrid({ agent, onAgentUpdated }: { agent: ManagedAgent; onAgentUpdated: () => void }) {
  const [editingModel, setEditingModel] = useState(false);
  const [changingModel, setChangingModel] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const currentModel = (agent.config?.model as string) || '(default)';

  async function startEditingModel() {
    try {
      const fetched = await fetchModels();
      setModels(fetched.map((m) => m.id));
    } catch { /* ignore */ }
    setEditingModel(true);
  }

  async function changeModel(newModel: string) {
    setChangingModel(true);
    try {
      const newConfig = { ...(agent.config || {}), model: newModel };
      await updateManagedAgent(agent.id, { config: newConfig });
      onAgentUpdated();
      toast.success(`Model changed to ${newModel}`);
    } catch { /* ignore */ }
    setEditingModel(false);
    setChangingModel(false);
  }

  const rows: [string, React.ReactNode][] = [
    ['Intelligence', editingModel ? (
      changingModel ? (
        <span className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>Switching model...</span>
      ) : (
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
      )
    ) : (
      <span className="flex items-center gap-2">
        <span style={{ color: 'var(--color-text)' }}>{currentModel}</span>
        <button
          onClick={startEditingModel}
          className="text-xs px-2 py-0.5 rounded cursor-pointer"
          style={{ color: 'var(--color-accent)', border: '1px solid var(--color-accent)', opacity: 0.8 }}
        >
          Change
        </button>
      </span>
    )],
    ['Agent Type', <span key="at">{agent.agent_type}</span>],
    ['Schedule', <span key="sc">{formatSchedule(agent.schedule_type, agent.schedule_value)}</span>],
    ['Last Run', <span key="lr">{formatRelativeTime(agent.last_run_at)}</span>],
    ['Budget', <span key="bg">{agent.budget ? formatCost(agent.budget) : 'Unlimited'}</span>],
    ['Learning', <span key="le">{agent.learning_enabled ? 'Enabled' : 'Disabled'}</span>],
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

/** AgentMessage extended with optional response metadata for the footer. */
type InteractMessage = AgentMessage & {
  _elapsed?: string;
  _toolCalls?: number;
  _usage?: Record<string, number>;
  _telemetry?: Record<string, unknown>;
};

function AgentResponseFooter({
  msg, copiedId, onCopy,
}: {
  msg: InteractMessage;
  copiedId: string | null;
  onCopy: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const u = msg._usage;
  const t = msg._telemetry as Record<string, unknown> | undefined;
  const elapsed = msg._elapsed;
  const toolCalls = msg._toolCalls || 0;

  // Build summary line like Chat: "ollama - qwen3.5:9b - 18.3s - 50 tokens"
  const parts: string[] = [];
  if (t?.engine) parts.push(String(t.engine));
  if (t?.model_id) parts.push(String(t.model_id));
  if (elapsed) parts.push(`${elapsed}s`);
  if (u?.prompt_tokens) parts.push(`${u.prompt_tokens} input tokens`);
  if (u?.completion_tokens) parts.push(`${u.completion_tokens} output tokens`);
  if (toolCalls > 0) parts.push(`${toolCalls} tool ${toolCalls === 1 ? 'call' : 'calls'}`);

  const summary = parts.length > 0 ? parts.join(' - ') : elapsed ? `${elapsed}s` : '';

  // Build expanded rows
  const rows: Array<{ label: string; value: string }> = [];
  if (t?.engine) rows.push({ label: 'Engine', value: `${t.engine}${t.model_id ? ` (${t.model_id})` : ''}` });
  if (u) {
    const tokenParts = [];
    if (u.completion_tokens) tokenParts.push(`${u.completion_tokens} generated`);
    if (u.prompt_tokens) tokenParts.push(`${u.prompt_tokens} prompt`);
    if (tokenParts.length) rows.push({ label: 'Tokens', value: tokenParts.join(' · ') });
  }
  if (toolCalls > 0) rows.push({ label: 'Tool calls', value: `${toolCalls}` });
  if (t?.tokens_per_sec) rows.push({ label: 'Speed', value: `${Math.round(Number(t.tokens_per_sec))} tok/s` });
  if (t?.total_ms) rows.push({ label: 'Latency', value: `${(Number(t.total_ms) / 1000).toFixed(1)}s total` });

  if (!summary) return null;

  return (
    <div style={{ borderTop: '1px solid var(--color-border-subtle)', marginTop: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', paddingTop: 4 }}>
        <button
          onClick={() => rows.length > 0 && setExpanded(!expanded)}
          style={{
            flex: 1, display: 'flex', alignItems: 'center', gap: 6,
            background: 'none', border: 'none', cursor: rows.length > 0 ? 'pointer' : 'default',
            padding: 0, textAlign: 'left',
          }}
        >
          <span style={{ width: 4, height: 4, borderRadius: '50%', background: 'var(--color-accent)', flexShrink: 0 }} />
          <span style={{ fontSize: 11, color: 'var(--color-text-tertiary)', fontFamily: 'system-ui' }}>
            {summary}
          </span>
          {rows.length > 0 && (
            <span style={{ fontSize: 10, color: 'var(--color-text-tertiary)' }}>
              {expanded ? '▲' : '▼'}
            </span>
          )}
        </button>
        <button
          onClick={() => onCopy(msg.id)}
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: 'var(--color-text-tertiary)', padding: 2,
            display: 'flex', alignItems: 'center',
          }}
          title="Copy response"
        >
          {copiedId === msg.id ? <Check size={12} /> : <Copy size={12} />}
        </button>
      </div>
      {expanded && rows.length > 0 && (
        <div style={{
          borderRadius: 6, marginTop: 4, padding: '6px 10px',
          background: 'rgba(0, 0, 0, 0.15)',
        }}>
          <div style={{
            display: 'grid', gridTemplateColumns: 'auto 1fr',
            columnGap: 12, rowGap: 2,
          }}>
            {rows.map((row) => (
              <div key={row.label} style={{ display: 'contents' }}>
                <span style={{ fontSize: 11, color: 'var(--color-text-tertiary)', fontFamily: 'monospace' }}>
                  {row.label}
                </span>
                <span style={{ fontSize: 11, color: 'var(--color-text-secondary)', fontFamily: 'monospace' }}>
                  {row.value}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function InteractTab({ agentId, agentStatus }: { agentId: string; agentStatus: string }) {
  const [messages, setMessages] = useState<InteractMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [waitingForResponse, setWaitingForResponse] = useState(false);
  const [progressLabel, setProgressLabel] = useState('');
  const [streamingContent, setStreamingContent] = useState('');
  const [currentActivity, setCurrentActivity] = useState('');
  const [liveStatus, setLiveStatus] = useState(agentStatus);
  const [streamElapsedMs, setStreamElapsedMs] = useState(0);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

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

  // Clean up elapsed-time timer on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, []);

  // Scroll to bottom only on initial load, not on every poll update.
  const hasScrolled = useRef(false);
  useEffect(() => {
    if (!hasScrolled.current && messages.length > 0) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
      hasScrolled.current = true;
    }
  }, [messages]);

  // Scroll to bottom when streaming content updates
  useEffect(() => {
    if (streamingContent) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [streamingContent]);

  async function handleSend(mode: 'immediate' | 'queued') {
    if (!input.trim()) return;
    const text = input.trim();
    setInput('');
    setSending(true);

    // Show user message immediately as a local bubble
    const localMsg: AgentMessage = {
      id: `local-${Date.now()}`,
      agent_id: agentId,
      direction: 'user_to_agent',
      content: text,
      mode,
      status: 'delivered',
      created_at: Date.now() / 1000,
    };
    setMessages((prev) => [localMsg, ...prev]);
    setSending(false);
    setWaitingForResponse(true);
    setProgressLabel('Initializing agent...');
    setStreamingContent('');

    // Start elapsed-time timer
    const startTime = Date.now();
    setStreamElapsedMs(0);
    timerRef.current = setInterval(() => {
      setStreamElapsedMs(Date.now() - startTime);
    }, 100);

    let toolCount = 0;
    let responseUsage: Record<string, number> | undefined;
    let responseTelemetry: Record<string, unknown> | undefined;
    try {
      const response = await sendAgentMessage(agentId, text, mode, {
        onProgress: (label) => {
          setProgressLabel(label);
          toolCount++;
        },
        onContentDelta: (_delta, full) => setStreamingContent(full),
        onDone: (_content, usage, telemetry) => {
          setStreamingContent('');
          responseUsage = usage;
          responseTelemetry = telemetry;
        },
      });
      const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
      // Add the agent's response as a local bubble immediately
      if (response && response.content) {
        setMessages((prev) => [
          {
            ...response,
            id: response.id || `response-${Date.now()}`,
            direction: 'agent_to_user' as const,
            _elapsed: elapsed,
            _toolCalls: toolCount,
            _usage: responseUsage,
            _telemetry: responseTelemetry,
          },
          ...prev,
        ]);
      }
      // Also refresh from server to sync any persisted messages
      await loadData();
    } catch {
      // ignore
    } finally {
      setWaitingForResponse(false);
      setStreamingContent('');
      setProgressLabel('');
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      setStreamElapsedMs(0);
    }
  }

  // Reverse so newest messages appear at the bottom (closest to input).
  // Filter out agent responses with empty content.
  const displayMessages = [...messages]
    .filter((m) => m.direction === 'user_to_agent' || m.content.trim())
    .reverse();

  return (
    <div className="flex flex-col h-full" style={{ minHeight: 320 }}>
      <div className="flex-1 overflow-y-auto space-y-3 pb-4" style={{ maxHeight: 400 }}>
        {displayMessages.length === 0 && !waitingForResponse && (
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
              {msg.direction === 'agent_to_user' ? (
                <div className="prose prose-sm prose-invert max-w-none"><ReactMarkdown>{msg.content}</ReactMarkdown></div>
              ) : (
                <p>{msg.content}</p>
              )}
              <p className="text-xs mt-1 opacity-70">
                {msg.status === 'pending' ? 'sending...' : new Date(msg.created_at * 1000).toLocaleTimeString()}
              </p>
              {msg.direction === 'agent_to_user' && (
                <AgentResponseFooter msg={msg} copiedId={copiedId} onCopy={(id) => {
                  navigator.clipboard.writeText(msg.content);
                  setCopiedId(id);
                  setTimeout(() => setCopiedId(null), 2000);
                }} />
              )}
            </div>
          </div>
        ))}
        {/* Progress indicator — shown when waiting but no streamed content yet */}
        {(waitingForResponse || sending) && !streamingContent && (
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
                {sending
                  ? 'Sending message...'
                  : progressLabel || 'Agent is thinking...'}
              </div>
            </div>
          </div>
        )}
        {/* Streaming content bubble — real-time response as it arrives */}
        {waitingForResponse && streamingContent && (
          <div className="flex justify-start">
            <div
              className="max-w-[75%] px-3 py-2 rounded-lg text-sm"
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text)',
              }}
            >
              {progressLabel && (
                <div className="flex items-center gap-2 mb-2 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  <span className="inline-block w-2 h-2 rounded-full animate-pulse" style={{ background: 'var(--color-accent)' }} />
                  {progressLabel}
                </div>
              )}
              <p className="whitespace-pre-wrap">{streamingContent}</p>
              <p className="text-xs mt-1 opacity-70">
                {streamElapsedMs > 0 && `${(streamElapsedMs / 1000).toFixed(1)}s elapsed`}
              </p>
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
            disabled={sending || waitingForResponse || !input.trim()}
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
// Channels tab component (data sources)
// ---------------------------------------------------------------------------

function ChannelsTab({ agentId }: { agentId: string }) {
  const [connectors, setConnectors] = useState<
    Array<{ connector_id: string; display_name: string; connected: boolean; chunks: number }>
  >([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // suppress unused var – agentId reserved for future per-agent source binding
  void agentId;

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

  useEffect(() => {
    loadConnectors();
    // Poll every 10s to catch background OAuth completions
    const interval = setInterval(loadConnectors, 10000);
    return () => clearInterval(interval);
  }, [loadConnectors]);

  const handleConnect = async (id: string, req: ConnectRequest) => {
    setLoading(true);
    try {
      await connectSource(id, req);
      setExpandedId(null);
      // Poll for connection status (OAuth flow runs in background thread)
      for (let i = 0; i < 30; i++) {
        await new Promise((r) => setTimeout(r, 3000));
        await loadConnectors();
        // Check if this connector is now connected
        const updated = await listConnectors();
        const target = updated.find((c) => c.connector_id === id);
        if (target?.connected) break;
      }
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
    gmail: '\u2709\uFE0F', gmail_imap: '\u2709\uFE0F', slack: '#',
    imessage: '\uD83D\uDCAC', gdrive: '\uD83D\uDCC1', notion: '\uD83D\uDCC4',
    obsidian: '\uD83D\uDCC1', granola: '\uD83C\uDF99\uFE0F', gcalendar: '\uD83D\uDCC5',
    gcontacts: '\uD83D\uDCC7', outlook: '\u2709\uFE0F', apple_notes: '\uD83C\uDF4E',
    dropbox: '\uD83D\uDCE6', whatsapp: '\uD83D\uDCF1',
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
          gap: 6, marginBottom: 12,
        }}>
          {connected.map((c) => {
            const meta = SOURCE_CATALOG.find(s => s.connector_id === c.connector_id);
            const unit = meta?.unitLabel || 'items';
            const isReconnecting = expandedId === c.connector_id;
            return (
            <div
              key={c.connector_id}
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid #2a5a3a',
                borderRadius: 6,
                overflow: 'hidden',
                gridColumn: isReconnecting ? '1 / -1' : undefined,
              }}
            >
              <div style={{
                padding: '12px 14px',
                display: 'flex', alignItems: 'center', gap: 8,
              }}>
                <span style={{ fontSize: 20 }}>{iconMap[c.connector_id] || '\uD83D\uDD17'}</span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 14, fontWeight: 600 }}>
                    {c.display_name}
                  </div>
                  <div style={{ fontSize: 12, color: c.chunks > 0 ? '#4ade80' : '#f59e0b' }}>
                    {c.chunks > 0
                      ? `${c.chunks.toLocaleString()} ${unit}`
                      : 'Connected — no data synced yet'}
                  </div>
                </div>
                <button
                  onClick={() => setExpandedId(isReconnecting ? null : c.connector_id)}
                  style={{
                    fontSize: 10, padding: '3px 10px',
                    background: 'transparent',
                    color: 'var(--color-text-secondary)',
                    border: '1px solid var(--color-border)',
                    borderRadius: 4, cursor: 'pointer',
                  }}
                >
                  {isReconnecting ? 'Cancel' : 'Reconnect'}
                </button>
              </div>
              {isReconnecting && meta?.steps && (
                <div style={{
                  borderTop: '1px solid var(--color-border)',
                  padding: 12,
                }}>
                  <div style={{
                    fontSize: 12, color: '#f59e0b',
                    marginBottom: 8,
                  }}>
                    Re-enter credentials to reconnect this source.
                  </div>
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
                      <div style={{ fontSize: 12, marginBottom: step.url ? 4 : 0 }}>
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
                      onSubmit={(req) => handleConnect(c.connector_id, req)}
                    />
                  )}
                </div>
              )}
            </div>
            );
          })}
        </div>
      )}

      {/* Not connected grid */}
      {notConnected.length > 0 && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: 6,
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
                    padding: '12px 14px', display: 'flex',
                    alignItems: 'center', gap: 8,
                    cursor: 'pointer',
                  }}
                  onClick={() =>
                    setExpandedId(isExpanded ? null : c.connector_id)
                  }
                >
                  <span style={{ fontSize: 20 }}>{iconMap[c.connector_id] || '\uD83D\uDD17'}</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 14, fontWeight: 600,
                      color: 'var(--color-text-secondary)' }}>
                      {c.display_name}
                    </div>
                    <div style={{ fontSize: 12,
                      color: 'var(--color-text-secondary)' }}>
                      Not connected
                    </div>
                  </div>
                  <span style={{
                    color: '#7c3aed', fontSize: 11, fontWeight: 500,
                  }}>
                    {isExpanded ? '\u2715 Close' : '+ Add'}
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
                            {step.urlLabel || 'Open'} {'\u2192'}
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
                      {'\uD83D\uDD12'} Read-only access {'\u00B7'} No data leaves your device
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

// ---------------------------------------------------------------------------
// Messaging tab component
// ---------------------------------------------------------------------------

interface ChannelField {
  key: string;
  label: string;
  placeholder: string;
  type?: 'text' | 'password';
  required?: boolean;
}

interface MessagingChannelConfig {
  type: string;
  name: string;
  icon: string;
  description: string;
  setupSteps: string[];
  fields: ChannelField[];
  activeLabel: (cfg: Record<string, unknown>) => string;
  howToUse: (cfg: Record<string, unknown>) => string;
}

const MESSAGING_CHANNELS: MessagingChannelConfig[] = [
  {
    type: 'imessage',
    name: 'iMessage',
    icon: '\uD83D\uDCAC',
    description: 'Talk to your agent via iMessage from your iPhone or another Apple device',
    setupSteps: [
      'Your agent monitors iMessage on this Mac using the Messages app.',
      'Enter your phone number or Apple ID below — your agent will watch for texts from that contact.',
      'Then open iMessage on your iPhone and text this Mac. Your agent reads the message, researches your data, and responds in the same conversation.',
      'Requires macOS Full Disk Access + Accessibility permissions (System Settings \u2192 Privacy & Security).',
    ],
    fields: [
      { key: 'identifier', label: 'Your phone number or Apple ID', placeholder: '+15551234567 or you@icloud.com', required: true },
    ],
    activeLabel: (cfg) => `Monitoring messages from ${(cfg.identifier as string) || '?'}`,
    howToUse: (cfg) => `Open iMessage on your phone and text this Mac from ${(cfg.identifier as string) || 'your phone'}. Your agent will respond automatically.`,
  },
  {
    type: 'slack',
    name: 'Slack',
    icon: '#',
    description: 'DM your agent in any Slack workspace',
    setupSteps: [
      '1. Go to api.slack.com/apps \u2192 Create New App \u2192 From Scratch',
      '2. Under OAuth & Permissions, add bot scopes: chat:write, channels:history, im:history, im:read',
      '3. Install the app to your workspace and authorize it',
      '4. Copy the Bot User OAuth Token (starts with xoxb-) from the OAuth page',
      '5. For real-time DMs: enable Socket Mode, create an App-Level Token (starts with xapp-)',
    ],
    fields: [
      { key: 'bot_token', label: 'Bot Token', placeholder: 'xoxb-...', type: 'password', required: true },
      { key: 'app_token', label: 'App Token (optional \u2014 enables receiving DMs)', placeholder: 'xapp-...', type: 'password' },
    ],
    activeLabel: () => 'Connected to Slack',
    howToUse: () => 'Open Slack and DM @Jarvis to talk to your agent.',
  },
  {
    type: 'whatsapp',
    name: 'WhatsApp',
    icon: '\uD83D\uDCF1',
    description: 'Message your agent on WhatsApp \u2014 runs locally, no cloud API needed',
    setupSteps: [
      'OpenJarvis connects to WhatsApp using the Baileys protocol (local, on-device).',
      'Click Connect below. A QR code will appear in the server terminal.',
      'On your phone: open WhatsApp \u2192 Settings \u2192 Linked Devices \u2192 Link a Device, then scan the QR code.',
      'Once linked, send a WhatsApp message to the connected number to talk to your agent.',
    ],
    fields: [
      { key: 'assistant_name', label: 'Agent display name (optional)', placeholder: 'Jarvis' },
    ],
    activeLabel: () => 'WhatsApp linked',
    howToUse: () => 'Send a WhatsApp message to the linked number. Your agent will respond in the chat.',
  },
  {
    type: 'twilio',
    name: 'SMS',
    icon: '\uD83D\uDCE8',
    description: 'Text your agent from any phone via Twilio',
    setupSteps: [
      '1. Create a free Twilio account at twilio.com/try-twilio',
      '2. In the Twilio Console, buy a phone number (or use the trial number)',
      '3. Copy your Account SID and Auth Token from the Console Dashboard',
      '4. Enter all three values below',
      'After setup, text the Twilio number from any phone to talk to your agent.',
    ],
    fields: [
      { key: 'account_sid', label: 'Account SID', placeholder: 'ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', required: true },
      { key: 'auth_token', label: 'Auth Token', placeholder: 'Your Twilio auth token', type: 'password', required: true },
      { key: 'phone_number', label: 'Twilio Phone Number', placeholder: '+15551234567', required: true },
    ],
    activeLabel: (cfg) => {
      const num = (cfg.phone_number as string) || '';
      return num ? `SMS active on ${num}` : 'SMS connected via Twilio';
    },
    howToUse: (cfg) => {
      const num = (cfg.phone_number as string) || 'your Twilio number';
      return `Text ${num} from any phone to talk to your agent.`;
    },
  },
];

function MessagingTab({ agentId }: { agentId: string }) {
  const [bindings, setBindings] = useState<ChannelBinding[]>([]);
  const [setupType, setSetupType] = useState<string | null>(null);
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);

  const loadBindings = useCallback(() => {
    fetchAgentChannels(agentId).then(setBindings).catch(() => setBindings([]));
  }, [agentId]);

  useEffect(() => { loadBindings(); }, [loadBindings]);

  const setField = (key: string, value: string) => {
    setFormValues((prev) => ({ ...prev, [key]: value }));
  };

  const handleSetup = async (ch: MessagingChannelConfig) => {
    // Check required fields
    const missing = ch.fields.filter(
      (f) => f.required && !formValues[f.key]?.trim(),
    );
    if (missing.length > 0) return;

    setLoading(true);
    try {
      const config: Record<string, string> = {};
      for (const f of ch.fields) {
        const v = formValues[f.key]?.trim();
        if (v) config[f.key] = v;
      }
      await bindAgentChannel(agentId, ch.type, config);
      setSetupType(null);
      setFormValues({});
      loadBindings();
    } catch { /* */ } finally { setLoading(false); }
  };

  const handleRemove = async (bindingId: string) => {
    try {
      await unbindAgentChannel(agentId, bindingId);
      loadBindings();
    } catch { /* */ }
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', padding: '6px 10px',
    background: 'var(--color-bg-secondary)',
    border: '1px solid var(--color-border)',
    borderRadius: 4, color: 'var(--color-text)',
    fontSize: 12, boxSizing: 'border-box',
  };

  return (
    <div style={{ padding: 16 }}>
      <div style={{
        color: 'var(--color-text-secondary)',
        fontSize: 12, marginBottom: 14,
      }}>
        Connect a messaging platform so you can talk to your agent from your phone or other devices.
      </div>

      {MESSAGING_CHANNELS.map((ch) => {
        const binding = bindings.find((b) => b.channel_type === ch.type);
        const cfg = (binding?.config || {}) as Record<string, unknown>;
        const isSetup = setupType === ch.type;

        // Check if required fields are filled
        const canConnect = ch.fields.every(
          (f) => !f.required || formValues[f.key]?.trim(),
        );

        return (
          <div
            key={ch.type}
            style={{
              background: 'var(--color-bg-secondary)',
              border: binding
                ? '1px solid #2a5a3a'
                : '1px dashed var(--color-border)',
              borderRadius: 8, marginBottom: 10,
              overflow: 'hidden',
            }}
          >
            {/* Header row */}
            <div style={{
              display: 'flex', alignItems: 'center',
              padding: '12px 14px',
            }}>
              <span style={{ fontSize: 18, marginRight: 10 }}>{ch.icon}</span>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{ch.name}</div>
                <div style={{
                  fontSize: 11,
                  color: binding ? '#4ade80' : 'var(--color-text-secondary)',
                }}>
                  {binding ? ch.activeLabel(cfg) : ch.description}
                </div>
              </div>
              {binding ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{
                    background: '#2a5a3a', color: '#4ade80',
                    padding: '2px 8px', borderRadius: 10,
                    fontSize: 10, fontWeight: 600,
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
                    setFormValues({});
                  }}
                  style={{
                    fontSize: 10, padding: '3px 12px',
                    background: '#7c3aed', color: 'white',
                    border: 'none', borderRadius: 5,
                    cursor: 'pointer', fontWeight: 600,
                  }}
                >
                  {isSetup ? 'Cancel' : 'Set Up'}
                </button>
              )}
            </div>

            {/* Active state: how to use */}
            {binding && (
              <div style={{
                borderTop: '1px solid var(--color-border)',
                padding: '10px 14px',
                background: 'var(--color-bg)',
              }}>
                <div style={{
                  fontSize: 11, color: 'var(--color-text-secondary)',
                  display: 'flex', alignItems: 'flex-start', gap: 6,
                }}>
                  <span style={{ flexShrink: 0 }}>{'\u2192'}</span>
                  <span>{ch.howToUse(cfg)}</span>
                </div>
              </div>
            )}

            {/* Setup form */}
            {isSetup && (
              <div style={{
                borderTop: '1px solid var(--color-border)',
                padding: '14px',
                background: 'var(--color-bg)',
              }}>
                {/* Setup instructions */}
                <div style={{
                  fontSize: 11, lineHeight: 1.5,
                  color: 'var(--color-text-secondary)',
                  marginBottom: 12,
                  padding: '8px 10px',
                  background: 'var(--color-bg-secondary)',
                  borderRadius: 6,
                  borderLeft: '3px solid var(--color-accent, #7c3aed)',
                }}>
                  {ch.setupSteps.map((step, i) => (
                    <div key={i} style={{ marginBottom: i < ch.setupSteps.length - 1 ? 4 : 0 }}>
                      {step}
                    </div>
                  ))}
                </div>

                {/* Form fields */}
                {ch.fields.map((field) => (
                  <div key={field.key} style={{ marginBottom: 8 }}>
                    <label style={{
                      display: 'block', fontSize: 11,
                      color: 'var(--color-text-secondary)',
                      marginBottom: 3, fontWeight: 500,
                    }}>
                      {field.label}{field.required ? ' *' : ''}
                    </label>
                    <input
                      type={field.type || 'text'}
                      value={formValues[field.key] || ''}
                      onChange={(e) => setField(field.key, e.target.value)}
                      placeholder={field.placeholder}
                      style={inputStyle}
                    />
                  </div>
                ))}

                {/* Connect button */}
                <button
                  onClick={() => handleSetup(ch)}
                  disabled={loading || !canConnect}
                  style={{
                    fontSize: 12, padding: '7px 20px',
                    background: '#7c3aed', color: 'white',
                    border: 'none', borderRadius: 5,
                    cursor: 'pointer', fontWeight: 600,
                    opacity: loading || !canConnect ? 0.5 : 1,
                    marginTop: 4,
                  }}
                >
                  {loading ? 'Connecting...' : 'Connect'}
                </button>
              </div>
            )}
          </div>
        );
      })}
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
  const [learningEntries, setLearningEntries] = useState<LearningLogEntry[]>([]);
  const [expandedTrace, setExpandedTrace] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    try {
      const [t, l] = await Promise.all([
        fetchAgentTraces(agentId),
        fetchLearningLog(agentId),
      ]);
      setTraces(t);
      setLearningEntries(l);
    } catch {
      // ignore
    }
  }, [agentId]);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 5000);
    return () => clearInterval(interval);
  }, [loadData]);

  // Merge traces and learning entries into a unified timeline
  type TimelineEntry =
    | { kind: 'trace'; data: AgentTrace; ts: number }
    | { kind: 'learning'; data: LearningLogEntry; ts: number };

  const timeline: TimelineEntry[] = [
    ...traces.map((t): TimelineEntry => ({ kind: 'trace', data: t, ts: t.started_at })),
    ...learningEntries.map((e): TimelineEntry => ({ kind: 'learning', data: e, ts: e.created_at })),
  ].sort((a, b) => b.ts - a.ts);

  const learningEventColor = (eventType: string) => {
    if (eventType === 'query_start') return '#3b82f6';
    if (eventType === 'query_complete') return '#22c55e';
    if (eventType === 'tool_call') return '#f59e0b';
    if (eventType === 'tool_result') return '#8b5cf6';
    if (eventType === 'query_error') return '#ef4444';
    return 'var(--color-text-secondary)';
  };

  const learningEventLabel = (eventType: string) => {
    if (eventType === 'query_start') return 'Query';
    if (eventType === 'query_complete') return 'Complete';
    if (eventType === 'tool_call') return 'Tool Call';
    if (eventType === 'tool_result') return 'Tool Result';
    if (eventType === 'query_error') return 'Error';
    return eventType;
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
          Activity Log
        </span>
        <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
          {timeline.length} entr{timeline.length !== 1 ? 'ies' : 'y'} (auto-refreshing)
        </span>
      </div>
      {timeline.length === 0 ? (
        <div className="text-sm text-center py-8" style={{ color: 'var(--color-text-tertiary)' }}>
          No activity yet. Send a message or run the agent to generate logs.
        </div>
      ) : (
        <div className="space-y-2">
          {timeline.map((entry) => {
            if (entry.kind === 'learning') {
              const e = entry.data;
              return (
                <div
                  key={`learn-${e.id}`}
                  className="rounded-lg p-3 text-sm"
                  style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span
                        className="w-2 h-2 rounded-full inline-block"
                        style={{ background: learningEventColor(e.event_type) }}
                      />
                      <span
                        className="text-[10px] px-1.5 py-0.5 rounded font-medium"
                        style={{
                          background: `${learningEventColor(e.event_type)}20`,
                          color: learningEventColor(e.event_type),
                        }}
                      >
                        {learningEventLabel(e.event_type)}
                      </span>
                    </div>
                    <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                      {formatRelativeTime(e.created_at)}
                    </span>
                  </div>
                  <div className="mt-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                    {e.description}
                  </div>
                </div>
              );
            }

            // Trace entry
            const t = entry.data;
            const errorDetail = t.metadata?.error_detail as
              | { error_type: string; error_message: string; suggested_action: string }
              | undefined;
            const isError = t.outcome !== 'success';
            const isExpanded = expandedTrace === t.id;

            return (
              <div
                key={`trace-${t.id}`}
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
                    <span
                      className="text-[10px] px-1.5 py-0.5 rounded font-medium"
                      style={{ background: 'var(--color-bg)', color: 'var(--color-text-secondary)' }}
                    >
                      Trace
                    </span>
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
  const savings = useAppStore((s) => s.savings);
  const [loading, setLoading] = useState(true);
  const [agentManagerAvailable, setAgentManagerAvailable] = useState<boolean | null>(null);
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [channels, setChannels] = useState<ChannelBinding[]>([]);
  const [templates, setTemplates] = useState<AgentTemplate[]>([]);
  const [showWizard, setShowWizard] = useState(false);
  const [detailTab, setDetailTab] = useState<'overview' | 'interact' | 'channels' | 'messaging' | 'tasks' | 'memory' | 'learning' | 'logs'>('overview');

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
      { id: 'channels', label: 'Channels', icon: Database },
      { id: 'messaging', label: 'Messaging', icon: Wifi },
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
            {detailTab === 'interact' ? (
              <span
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs"
                style={{ background: '#22c55e20', color: '#22c55e', border: '1px solid #22c55e40' }}
              >
                <MessageSquare size={13} /> Chat ready — just type below
              </span>
            ) : (
              <button
                onClick={() => handleRun(selectedAgent.id)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm cursor-pointer font-medium"
                style={{ background: 'var(--color-accent)', color: '#fff' }}
              >
                <Zap size={13} /> Run Now
              </button>
            )}
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
            {/* Instruction */}
            <AgentInstructionSection agent={selectedAgent} onAgentUpdated={refresh} />

            {/* Configuration */}
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

            {/* Usage stats + savings — single compact row */}
            {(() => {
              const inTok = selectedAgent.input_tokens ?? 0;
              const outTok = selectedAgent.output_tokens ?? 0;
              const modelName = (selectedAgent.config?.model as string) || '';
              const paramMatch = modelName.match(/:(\d+(?:\.\d+)?)b/i);
              const paramsB = paramMatch ? parseFloat(paramMatch[1]) : 9;
              const flops = 2 * paramsB * 1e9 * (inTok + outTok);
              const providers = [
                { label: 'GPT-5.3', inPer1M: 2.0, outPer1M: 10.0 },
                { label: 'Claude Opus 4.6', inPer1M: 5.0, outPer1M: 25.0 },
                { label: 'Gemini 3.1 Pro', inPer1M: 2.0, outPer1M: 12.0 },
              ];
              const energyWh = (inTok + outTok) / 1000 * 0.4;
              const energyKj = energyWh * 3.6;
              const fmtFlops = flops >= 1e15 ? `${(flops / 1e15).toFixed(1)} PFLOPs` : `${(flops / 1e12).toFixed(1)} TFLOPs`;
              const hasSavings = inTok + outTok > 0;
              const sectionTitle = { fontSize: 11, fontWeight: 600, color: 'var(--color-text-tertiary)', textTransform: 'uppercase' as const, letterSpacing: '0.05em', marginBottom: 8 };
              return (
                <div className="p-4 rounded-xl" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
                  <div className="flex gap-0 flex-wrap items-stretch">
                    {/* Agent Statistics */}
                    <div className="pr-5">
                      <p style={sectionTitle}>Agent Statistics</p>
                      <div className="flex gap-5">
                        <div>
                          <p className="text-xl font-bold leading-none" style={{ color: 'var(--color-text)' }}>{selectedAgent.total_runs ?? 0}</p>
                          <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Total Queries</p>
                        </div>
                        <div>
                          <p className="text-xl font-bold leading-none" style={{ color: 'var(--color-text)' }}>{inTok.toLocaleString()}</p>
                          <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Input Tokens</p>
                        </div>
                        <div>
                          <p className="text-xl font-bold leading-none" style={{ color: 'var(--color-text)' }}>{outTok.toLocaleString()}</p>
                          <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Output Tokens</p>
                        </div>
                      </div>
                    </div>
                    {hasSavings && (<>
                      <div style={{ width: 1, background: 'var(--color-border)' }} />
                      {/* Local Utilization */}
                      <div className="px-5">
                        <p style={sectionTitle}>Local Utilization</p>
                        <div className="flex gap-5">
                          <div>
                            <p className="text-xl font-bold leading-none" style={{ color: '#22c55e' }}>{fmtFlops}</p>
                            <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Compute</p>
                          </div>
                          <div>
                            <p className="text-xl font-bold leading-none" style={{ color: '#22c55e' }}>{energyKj.toFixed(2)} kJ</p>
                            <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Energy</p>
                          </div>
                        </div>
                      </div>
                      <div style={{ width: 1, background: 'var(--color-border)' }} />
                      {/* Dollars Saved */}
                      <div className="pl-5">
                        <p style={sectionTitle}>Dollars Saved vs.</p>
                        <div className="flex gap-5">
                          {providers.map((p) => {
                            const cost = (inTok / 1e6) * p.inPer1M + (outTok / 1e6) * p.outPer1M;
                            return (
                              <div key={p.label}>
                                <p className="text-xl font-bold leading-none" style={{ color: '#22c55e' }}>${cost.toFixed(4)}</p>
                                <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>{p.label}</p>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    </>)}
                  </div>
                </div>);
            })()}

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

        {/* Tab: Channels */}
        {detailTab === 'channels' && (
          <ChannelsTab agentId={selectedAgent.id} />
        )}

        {/* Tab: Messaging */}
        {detailTab === 'messaging' && (
          <MessagingTab agentId={selectedAgent.id} />
        )}

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
