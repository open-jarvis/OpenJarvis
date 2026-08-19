import { useState, type FormEvent } from 'react';
import { FlaskConical, Save } from 'lucide-react';

interface ObjectiveInputProps {
  onSubmit: (description: string, projectName: string) => void;
  loading: boolean;
}

export function ObjectiveInput({ onSubmit, loading }: ObjectiveInputProps) {
  const [description, setDescription] = useState('');
  const [projectName, setProjectName] = useState('');
  const [showSave, setShowSave] = useState(false);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!description.trim() || loading) return;
    onSubmit(description.trim(), showSave ? projectName.trim() : '');
  };

  return (
    <form onSubmit={handleSubmit} className="hud-panel p-5">
      <div className="flex items-center gap-2 mb-3">
        <FlaskConical size={14} style={{ color: 'var(--color-accent)' }} />
        <span className="hud-label">OBJETIVO</span>
      </div>
      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Descreva o que você quer criar ou investigar (ex: quero um fluido que se comporte como uma teia de aranha)..."
        rows={3}
        className="w-full resize-none rounded-lg px-3 py-2 text-sm outline-none"
        style={{
          background: 'var(--color-bg-secondary)',
          border: '1px solid var(--color-border)',
          color: 'var(--color-text)',
        }}
        disabled={loading}
      />
      <div className="flex items-center justify-between mt-3 gap-3">
        <label className="flex items-center gap-2 text-xs cursor-pointer" style={{ color: 'var(--color-text-secondary)' }}>
          <input
            type="checkbox"
            checked={showSave}
            onChange={(e) => setShowSave(e.target.checked)}
            disabled={loading}
          />
          <Save size={12} />
          Salvar como projeto
        </label>
        {showSave && (
          <input
            type="text"
            value={projectName}
            onChange={(e) => setProjectName(e.target.value)}
            placeholder="nome-do-projeto"
            className="flex-1 rounded-lg px-3 py-1.5 text-xs outline-none hud-mono"
            style={{
              background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text)',
            }}
            disabled={loading}
          />
        )}
        <button
          type="submit"
          disabled={loading || !description.trim()}
          className="shrink-0 px-4 py-1.5 rounded-lg text-sm font-medium transition-opacity cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
          style={{ background: 'var(--color-accent)', color: 'white' }}
        >
          Analisar
        </button>
      </div>
    </form>
  );
}
