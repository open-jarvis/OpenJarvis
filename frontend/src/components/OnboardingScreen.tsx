import { useState, useEffect, useCallback } from 'react';
import { Loader2, Cpu, Server } from 'lucide-react';
import { probeLocalEngines, setInferenceSource, startBackend, type ProbeResult } from '../lib/api';
import {
  InferenceSourceForm,
  DEFAULT_CUSTOM_FORM_VALUE,
  type InferenceSourceFormValue,
} from './InferenceSourceForm';

const buttonBase =
  'text-sm px-3 py-1.5 rounded-lg outline-none cursor-pointer disabled:opacity-50 disabled:cursor-default';
const primaryButtonStyle = {
  background: 'var(--color-accent, var(--color-bg-tertiary))',
  color: 'var(--color-text)',
  border: '1px solid var(--color-border)',
} as const;
const secondaryButtonStyle = {
  background: 'transparent',
  color: 'var(--color-text-secondary)',
  border: '1px solid var(--color-border)',
} as const;

/**
 * First-run screen: probes for an already-running Ollama/LM Studio, lets the
 * user confirm or pick something else, and on completion calls
 * setInferenceSource + startBackend so SetupScreen's normal progress UI
 * takes over (its poll picks up the phase change away from "onboarding").
 */
export function OnboardingScreen() {
  const [probing, setProbing] = useState(true);
  const [results, setResults] = useState<ProbeResult[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [formValue, setFormValue] = useState<InferenceSourceFormValue>(DEFAULT_CUSTOM_FORM_VALUE);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    probeLocalEngines().then((r) => {
      setResults(r);
      setProbing(false);
    });
  }, []);

  const finish = useCallback(
    async (src: { kind: 'ollama' | 'custom'; host?: string; model?: string; engine?: string; apiKey?: string }) => {
      setBusy(true);
      setError('');
      try {
        await setInferenceSource(src);
        await startBackend();
      } catch (e: any) {
        setError(e?.message ?? 'Failed to save.');
        setBusy(false);
      }
    },
    [],
  );

  const useDetected = (r: ProbeResult) => {
    if (r.engine === 'ollama') {
      finish({ kind: 'ollama' });
    } else {
      finish({ kind: 'custom', engine: 'lmstudio', host: r.host, model: r.model ?? '' });
    }
  };

  const openFormFor = (r?: ProbeResult) => {
    if (r && r.engine === 'lmstudio') {
      setFormValue({
        kind: 'custom',
        host: `${r.host}/v1`,
        model: r.model ?? '',
        engine: 'lmstudio',
        apiKey: '',
      });
    }
    setError('');
    setShowForm(true);
  };

  const submitForm = () => {
    if (formValue.kind === 'ollama') {
      finish({ kind: 'ollama' });
    } else {
      finish({
        kind: 'custom',
        host: formValue.host,
        model: formValue.model,
        engine: formValue.engine,
        apiKey: formValue.apiKey || undefined,
      });
    }
  };

  const found = results.filter((r) => r.found);

  return (
    <div className="fixed inset-0 flex items-center justify-center" style={{ background: 'var(--color-bg)' }}>
      <div className="w-full max-w-md px-6">
        <div className="text-center mb-8">
          <div
            className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-4"
            style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}
          >
            <Cpu size={32} />
          </div>
          <h1 className="text-2xl font-bold mb-1" style={{ color: 'var(--color-text)' }}>
            Welcome to OpenJarvis
          </h1>
          <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
            Let's connect to a local AI model.
          </p>
        </div>

        {probing && (
          <div className="flex items-center justify-center gap-2 py-8">
            <Loader2 size={18} className="animate-spin" style={{ color: 'var(--color-accent)' }} />
            <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              Looking for a local AI server...
            </span>
          </div>
        )}

        {!probing && !showForm && (
          <div className="flex flex-col gap-3">
            {found.map((r) => (
              <div
                key={r.engine}
                className="flex items-center justify-between gap-3 px-4 py-3 rounded-xl"
                style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
              >
                <div className="flex items-center gap-3 min-w-0">
                  <Server size={18} style={{ color: 'var(--color-accent)' }} className="shrink-0" />
                  <div className="min-w-0">
                    <div className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                      {r.label}
                    </div>
                    <div className="text-xs truncate" style={{ color: 'var(--color-text-tertiary)' }}>
                      Found at {r.host}{r.model ? ` (${r.model})` : ''}
                    </div>
                  </div>
                </div>
                <div className="flex gap-2 shrink-0">
                  <button disabled={busy} onClick={() => useDetected(r)} className={buttonBase} style={primaryButtonStyle}>
                    Use this
                  </button>
                  <button disabled={busy} onClick={() => openFormFor(r)} className={buttonBase} style={secondaryButtonStyle}>
                    Choose different
                  </button>
                </div>
              </div>
            ))}

            {found.length === 0 && (
              <div className="flex flex-col gap-3">
                <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                  No local AI server detected. OpenJarvis can install and run
                  Ollama for you, or you can connect to a server you already
                  have running.
                </p>
                <button disabled={busy} onClick={() => finish({ kind: 'ollama' })} className={`${buttonBase} py-2 text-center`} style={primaryButtonStyle}>
                  Use Ollama (recommended)
                </button>
                <button disabled={busy} onClick={() => openFormFor()} className={`${buttonBase} py-2 text-center`} style={secondaryButtonStyle}>
                  I have a custom server
                </button>
              </div>
            )}

            {found.length > 0 && (
              <button
                disabled={busy}
                onClick={() => openFormFor()}
                className={`${buttonBase} py-2 text-center`}
                style={{ ...secondaryButtonStyle, color: 'var(--color-text-tertiary)' }}
              >
                Configure manually
              </button>
            )}
          </div>
        )}

        {showForm && (
          <InferenceSourceForm
            value={formValue}
            onChange={setFormValue}
            onSubmit={submitForm}
            submitLabel="Get started"
            message={error}
          />
        )}

        {error && !showForm && (
          <p className="text-sm mt-3" style={{ color: 'var(--color-error)' }}>
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
