import { useState, useEffect, useRef, useCallback } from 'react';
import {
  Cpu,
  Bot,
  Sparkles,
  Building2,
  Scale,
  Megaphone,
  Wrench,
  ShieldCheck,
  ChevronDown,
  Zap,
  FlaskConical,
  Lightbulb,
  Search,
} from 'lucide-react';
import { useAppStore } from '../../lib/store';
import { fetchModels } from '../../lib/api';
import type { ModelInfo } from '../../types';

const DOMAIN_AGENTS = [
  { id: 'auto', label: 'Auto', icon: Sparkles, color: '#f59e0b' },
  { id: 'bavaria_booking', label: 'Bavaria Booking', icon: Building2, color: '#2563eb' },
  { id: 'legal_assistant', label: 'Legal', icon: Scale, color: '#7c3aed' },
  { id: 'marketing_assistant', label: 'Marketing', icon: Megaphone, color: '#db2777' },
  { id: 'operations_assistant', label: 'Operations', icon: Wrench, color: '#059669' },
  { id: 'security_assistant', label: 'Security', icon: ShieldCheck, color: '#dc2626' },
];

function useClickOutside(ref: React.RefObject<HTMLElement | null>, handler: () => void) {
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) handler();
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, [ref, handler]);
}

export function ChatToolbar() {
  const selectedModel = useAppStore((s) => s.selectedModel);
  const setSelectedModel = useAppStore((s) => s.setSelectedModel);
  const activeDomainAgent = useAppStore((s) => s.activeDomainAgent);
  const setActiveDomainAgent = useAppStore((s) => s.setActiveDomainAgent);
  const deepResearch = useAppStore((s) => s.deepResearch);
  const setDeepResearch = useAppStore((s) => s.setDeepResearch);
  const planMode = useAppStore((s) => s.planMode);
  const setPlanMode = useAppStore((s) => s.setPlanMode);
  const serverInfo = useAppStore((s) => s.serverInfo);
  const modelLoading = useAppStore((s) => s.modelLoading);
  const createConversation = useAppStore((s) => s.createConversation);

  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelOpen, setModelOpen] = useState(false);
  const [agentOpen, setAgentOpen] = useState(false);

  const modelRef = useRef<HTMLDivElement>(null);
  const agentRef = useRef<HTMLDivElement>(null);

  useClickOutside(modelRef, () => setModelOpen(false));
  useClickOutside(agentRef, () => setAgentOpen(false));

  // Load models on mount
  useEffect(() => {
    setModelsLoading(true);
    fetchModels()
      .then((ms) => setModels(ms))
      .catch(() => setModels([]))
      .finally(() => setModelsLoading(false));
  }, []);

  const handleModelSelect = useCallback(
    (modelId: string) => {
      setSelectedModel(modelId);
      setModelOpen(false);
    },
    [setSelectedModel],
  );

  const handleAgentSelect = useCallback(
    (agentId: string) => {
      if (agentId === activeDomainAgent) {
        setActiveDomainAgent(null);
      } else {
        setActiveDomainAgent(agentId);
      }
      setAgentOpen(false);
    },
    [activeDomainAgent, setActiveDomainAgent],
  );

  const activeAgent = DOMAIN_AGENTS.find((a) => a.id === activeDomainAgent);
  const displayModel = selectedModel || serverInfo?.model || 'Select model';

  return (
    <div className="flex items-center gap-2 mb-2 flex-wrap">
      {/* Model Dropdown */}
      <div ref={modelRef} className="relative">
        <button
          onClick={() => setModelOpen(!modelOpen)}
          disabled={modelLoading}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs transition-colors cursor-pointer"
          style={{
            background: 'var(--color-bg-secondary)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text-secondary)',
          }}
        >
          {modelLoading ? (
            <span className="inline-block w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin" />
          ) : (
            <Cpu size={12} />
          )}
          <span className="max-w-[120px] truncate">{displayModel}</span>
          <ChevronDown size={10} className={`transition-transform ${modelOpen ? 'rotate-180' : ''}`} />
        </button>

        {modelOpen && (
          <div
            className="absolute bottom-full left-0 mb-1.5 rounded-lg shadow-lg py-1 z-50 min-w-[200px] max-h-[240px] overflow-y-auto"
            style={{
              background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)',
            }}
          >
            {modelsLoading && (
              <div className="px-3 py-2 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                Loading models...
              </div>
            )}
            {!modelsLoading && models.length === 0 && (
              <div className="px-3 py-2 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                No models available
              </div>
            )}
            {models.map((m) => (
              <button
                key={m.id}
                onClick={() => handleModelSelect(m.id)}
                className="w-full text-left px-3 py-1.5 text-xs transition-colors cursor-pointer"
                style={{
                  background: selectedModel === m.id ? 'var(--color-accent-subtle)' : 'transparent',
                  color: selectedModel === m.id ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                }}
                onMouseEnter={(e) => {
                  if (selectedModel !== m.id) e.currentTarget.style.background = 'var(--color-bg-tertiary)';
                }}
                onMouseLeave={(e) => {
                  if (selectedModel !== m.id) e.currentTarget.style.background = 'transparent';
                }}
              >
                {m.id}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Agent Dropdown */}
      <div ref={agentRef} className="relative">
        <button
          onClick={() => setAgentOpen(!agentOpen)}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs transition-colors cursor-pointer"
          style={{
            background: activeDomainAgent ? `${activeAgent?.color || '#666'}15` : 'var(--color-bg-secondary)',
            border: `1px solid ${activeDomainAgent ? activeAgent?.color || 'var(--color-accent)' : 'var(--color-border)'}`,
            color: activeDomainAgent ? activeAgent?.color || 'var(--color-accent)' : 'var(--color-text-secondary)',
          }}
        >
          {activeAgent ? (
            <activeAgent.icon size={12} />
          ) : (
            <Bot size={12} />
          )}
          <span>{activeAgent?.label || 'Agent'}</span>
          <ChevronDown size={10} className={`transition-transform ${agentOpen ? 'rotate-180' : ''}`} />
        </button>

        {agentOpen && (
          <div
            className="absolute bottom-full left-0 mb-1.5 rounded-lg shadow-lg py-1 z-50 min-w-[180px]"
            style={{
              background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)',
            }}
          >
            {DOMAIN_AGENTS.map((da) => {
              const Icon = da.icon;
              const isActive = activeDomainAgent === da.id;
              return (
                <button
                  key={da.id}
                  onClick={() => handleAgentSelect(da.id)}
                  className="w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors cursor-pointer"
                  style={{
                    background: isActive ? `${da.color}15` : 'transparent',
                    color: isActive ? da.color : 'var(--color-text-secondary)',
                  }}
                  onMouseEnter={(e) => {
                    if (!isActive) e.currentTarget.style.background = 'var(--color-bg-tertiary)';
                  }}
                  onMouseLeave={(e) => {
                    if (!isActive) e.currentTarget.style.background = 'transparent';
                  }}
                >
                  <Icon size={12} style={{ color: da.color }} />
                  <span>{da.label}</span>
                  {isActive && <Zap size={10} className="ml-auto" />}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Mode toggles */}
      <div className="flex items-center gap-1.5 ml-auto">
        {/* Plan Mode */}
        <button
          type="button"
          onClick={() => setPlanMode(!planMode)}
          disabled={modelLoading}
          aria-pressed={planMode}
          className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-[10px] transition-colors cursor-pointer disabled:cursor-default disabled:opacity-50"
          style={{
            background: planMode ? 'var(--color-accent-subtle)' : 'transparent',
            border: `1px solid ${planMode ? 'var(--color-accent)' : 'var(--color-border)'}`,
            color: planMode ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
          }}
          title={planMode ? 'Plan Mode: on' : 'Plan Mode: off'}
        >
          <Lightbulb size={10} />
          Plan
        </button>

        {/* Deep Research */}
        <button
          type="button"
          onClick={() => setDeepResearch(!deepResearch)}
          disabled={modelLoading}
          aria-pressed={deepResearch}
          className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-[10px] transition-colors cursor-pointer disabled:cursor-default disabled:opacity-50"
          style={{
            background: deepResearch ? 'var(--color-accent-subtle)' : 'transparent',
            border: `1px solid ${deepResearch ? 'var(--color-accent)' : 'var(--color-border)'}`,
            color: deepResearch ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
          }}
          title={deepResearch ? 'Deep Research: on' : 'Deep Research: off'}
        >
          <FlaskConical size={10} />
          Research
        </button>
      </div>
    </div>
  );
}
