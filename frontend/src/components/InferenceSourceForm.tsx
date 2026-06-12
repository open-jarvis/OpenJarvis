import type { InferenceSource } from '../lib/api';

export interface InferenceSourceFormValue {
  kind: InferenceSource['kind'];
  host: string;
  model: string;
  engine: string;
  apiKey: string;
}

/** Sensible starting point for "I have a custom server" / manual entry. */
export const DEFAULT_CUSTOM_FORM_VALUE: InferenceSourceFormValue = {
  kind: 'custom',
  host: 'http://127.0.0.1:1234/v1',
  model: '',
  engine: 'lmstudio',
  apiKey: '',
};

const fieldStyle = {
  background: 'var(--color-bg-secondary)',
  color: 'var(--color-text)',
  border: '1px solid var(--color-border)',
} as const;

const inputClass = 'text-sm px-3 py-1.5 rounded-lg outline-none w-full';
const labelClass = 'text-xs block mb-1';
const labelStyle = { color: 'var(--color-text-tertiary)' } as const;

/**
 * Inference-source picker: Ollama vs. a custom OpenAI-compatible endpoint
 * (host, model, server type, optional API key). Shared by SettingsPage
 * ("Save inference source"), OnboardingScreen ("Get started"), and
 * SetupScreen's Reconfigure flow ("Save & retry") — each supplies its own
 * `onSubmit`.
 */
export function InferenceSourceForm({
  value,
  onChange,
  onSubmit,
  submitLabel,
  message,
  disabled,
}: {
  value: InferenceSourceFormValue;
  onChange: (next: InferenceSourceFormValue) => void;
  onSubmit: () => void;
  submitLabel: string;
  message?: string;
  disabled?: boolean;
}) {
  const set = <K extends keyof InferenceSourceFormValue>(
    key: K,
    v: InferenceSourceFormValue[K],
  ) => onChange({ ...value, [key]: v });

  return (
    <div className="flex flex-col gap-3">
      <div>
        <label className={labelClass} style={labelStyle}>Source</label>
        <select
          value={value.kind}
          onChange={(e) => set('kind', e.target.value as InferenceSource['kind'])}
          className={inputClass}
          style={fieldStyle}
        >
          <option value="ollama">Bundled Ollama (default)</option>
          <option value="custom">Custom OpenAI-compatible server</option>
        </select>
      </div>
      {value.kind === 'custom' && (
        <>
          <div>
            <label className={labelClass} style={labelStyle}>
              Server URL — e.g. LM Studio: http://127.0.0.1:1234/v1
            </label>
            <input
              type="text"
              value={value.host}
              onChange={(e) => set('host', e.target.value)}
              placeholder="http://127.0.0.1:1234/v1"
              className={inputClass}
              style={fieldStyle}
            />
          </div>
          <div>
            <label className={labelClass} style={labelStyle}>Model</label>
            <input
              type="text"
              value={value.model}
              onChange={(e) => set('model', e.target.value)}
              placeholder="qwen2.5-7b-instruct"
              className={inputClass}
              style={fieldStyle}
            />
          </div>
          <div>
            <label className={labelClass} style={labelStyle}>Server type</label>
            <select
              value={value.engine}
              onChange={(e) => set('engine', e.target.value)}
              className={inputClass}
              style={fieldStyle}
            >
              <option value="lmstudio">LM Studio</option>
              <option value="vllm">vLLM</option>
              <option value="sglang">SGLang</option>
              <option value="llamacpp">llama.cpp</option>
              <option value="mlx">MLX</option>
            </select>
          </div>
          <div>
            <label className={labelClass} style={labelStyle}>API key (optional)</label>
            <input
              type="password"
              value={value.apiKey}
              onChange={(e) => set('apiKey', e.target.value)}
              placeholder="leave blank if none"
              className={inputClass}
              style={fieldStyle}
            />
          </div>
        </>
      )}
      <div className="flex items-center justify-between gap-3 mt-1">
        {message && (
          <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            {message}
          </span>
        )}
        <button
          onClick={onSubmit}
          disabled={disabled}
          className="text-sm px-3 py-1.5 rounded-lg outline-none cursor-pointer ml-auto disabled:opacity-50 disabled:cursor-default"
          style={{
            background: 'var(--color-accent, var(--color-bg-tertiary))',
            color: 'var(--color-text)',
            border: '1px solid var(--color-border)',
          }}
        >
          {submitLabel}
        </button>
      </div>
    </div>
  );
}
