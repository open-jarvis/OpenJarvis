import { useState, useEffect, useCallback, useRef } from 'react';
import { Loader2, CheckCircle2, XCircle, Cpu, Server, Database } from 'lucide-react';
import {
  getSetupStatus,
  fetchModels,
  fetchRecommendedModel,
  type SetupStatus,
} from '../lib/api';
import { useAppStore } from '../lib/store';

const STEPS = [
  { key: 'ollama_ready', label: 'Inference Engine', icon: Cpu, detail: 'Starting Ollama...' },
  { key: 'model_ready', label: 'AI Model', icon: Database, detail: 'Loading model...' },
  { key: 'server_ready', label: 'API Server', icon: Server, detail: 'Starting server...' },
] as const;

type StepKey = (typeof STEPS)[number]['key'];

function StepRow({
  icon: Icon,
  label,
  done,
  active,
  detail,
}: {
  icon: typeof Cpu;
  label: string;
  done: boolean;
  active: boolean;
  detail: string;
}) {
  return (
    <div
      className="flex items-center gap-4 px-5 py-4 rounded-xl transition-all"
      style={{
        background: done
          ? 'var(--color-accent-subtle)'
          : active
            ? 'var(--color-surface)'
            : 'transparent',
        border: active ? '1px solid var(--color-border)' : '1px solid transparent',
      }}
    >
      <div
        className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
        style={{
          background: done ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
          color: done ? 'white' : 'var(--color-text-tertiary)',
        }}
      >
        <Icon size={18} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
          {label}
        </div>
        <div className="text-xs truncate" style={{ color: 'var(--color-text-tertiary)', maxWidth: '280px' }}>
          {done ? 'Ready' : active ? detail : 'Waiting...'}
        </div>
      </div>
      <div className="shrink-0">
        {done ? (
          <CheckCircle2 size={18} style={{ color: 'var(--color-accent)' }} />
        ) : active ? (
          <Loader2 size={18} className="animate-spin" style={{ color: 'var(--color-accent)' }} />
        ) : (
          <div
            className="w-4 h-4 rounded-full"
            style={{ border: '2px solid var(--color-border)' }}
          />
        )}
      </div>
    </div>
  );
}

export function SetupScreen({ onReady }: { onReady: () => void }) {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const handedOffRef = useRef(false);
  const poll = useCallback(async () => {
    const s = await getSetupStatus();
    if (s) setStatus(s);
    if (s?.phase === 'ready' && !handedOffRef.current) {
      handedOffRef.current = true;
      // Pre-select a model BEFORE handing off so the chat is usable on
      // first send. Without this, the main app's post-mount fetch can
      // lose a race to a fast first message and Ollama 400s.
      try {
        const [models, rec] = await Promise.all([
          fetchModels().catch(() => []),
          fetchRecommendedModel().catch(() => ({ model: '', reason: '' })),
        ]);
        const store = useAppStore.getState();
        store.setModels(models);
        store.setModelsLoading(false);
        const recommended = rec.model && models.some((m) => m.id === rec.model)
          ? rec.model
          : models[0]?.id || '';
        if (recommended && !store.selectedModel) {
          store.setSelectedModel(recommended);
        }
      } catch {
        // Non-fatal: store.setModels auto-selects on later fetch, and
        // the InputArea guards the empty-model case with a toast.
      }
      setTimeout(() => onReady(), 600);
    }
  }, [onReady]);

  useEffect(() => {
    poll();
    const interval = setInterval(poll, 800);
    return () => clearInterval(interval);
  }, [poll]);

  const activeStep: StepKey | null =
    status && !status.ollama_ready
      ? 'ollama_ready'
      : status && !status.model_ready
        ? 'model_ready'
        : status && !status.server_ready
          ? 'server_ready'
          : null;

  return (
    <div
      className="fixed inset-0 flex items-center justify-center"
      style={{ background: 'var(--color-bg)' }}
    >
      <div className="w-full max-w-md px-6">
        {/* Logo */}
        <div className="text-center mb-10">
          <div
            className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-4"
            style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}
          >
            <Cpu size={32} />
          </div>
          <h1 className="text-2xl font-bold mb-1" style={{ color: 'var(--color-text)' }}>
            OpenJarvis
          </h1>
          <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
            Setting up your local AI...
          </p>
        </div>

        {/* Steps */}
        <div className="flex flex-col gap-2 mb-8">
          {(status?.source === 'custom'
            ? [
                { key: 'ollama_ready' as const, label: 'Inference Engine', icon: Cpu, detail: 'Connecting to your server...' },
                { key: 'model_ready' as const, label: 'Endpoint', icon: Database, detail: 'Checking endpoint...' },
                { key: 'server_ready' as const, label: 'API Server', icon: Server, detail: 'Starting server...' },
              ]
            : STEPS
          ).map((step) => (
            <StepRow
              key={step.key}
              icon={step.icon}
              label={step.label}
              done={status?.[step.key] ?? false}
              active={activeStep === step.key}
              detail={
                activeStep === step.key && status?.detail
                  ? status.detail
                  : step.detail
              }
            />
          ))}
        </div>

        {/* Error */}
        {status?.error && (
          <div
            className="flex items-start gap-3 px-4 py-3 rounded-xl text-sm"
            style={{
              background: 'color-mix(in srgb, var(--color-error) 10%, transparent)',
              border: '1px solid color-mix(in srgb, var(--color-error) 20%, transparent)',
              color: 'var(--color-error)',
            }}
          >
            <XCircle size={16} className="shrink-0 mt-0.5" />
            <span style={{ wordBreak: 'break-word', overflowWrap: 'anywhere' }}>{status.error}</span>
          </div>
        )}

        {/* Progress bar */}
        {!status?.error && (
          <div
            className="h-1 rounded-full overflow-hidden"
            style={{ background: 'var(--color-bg-tertiary)' }}
          >
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                background: 'var(--color-accent)',
                width: `${
                  ((status?.ollama_ready ? 1 : 0) +
                    (status?.model_ready ? 1 : 0) +
                    (status?.server_ready ? 1 : 0)) *
                  33.33
                }%`,
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
