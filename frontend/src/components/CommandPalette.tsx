import { useState, useRef, useEffect } from 'react';
import { Search, Cpu, X, Download, Loader2, Trash2, Check } from 'lucide-react';
import { useAppStore } from '../lib/store';
import { pullModel, deleteModel, fetchModels, preloadModel } from '../lib/api';

/** Popular models that users can download from the catalogue. */
const CATALOGUE_MODELS = [
  { id: 'qwen3.5:0.8b', size: '~1 GB', desc: 'Qwen 3.5 0.8B — fast, lightweight' },
  { id: 'qwen3.5:2b', size: '~2.7 GB', desc: 'Qwen 3.5 2B' },
  { id: 'qwen3.5:4b', size: '~3.4 GB', desc: 'Qwen 3.5 4B — recommended default' },
  { id: 'qwen3.5:9b', size: '~6.6 GB', desc: 'Qwen 3.5 9B' },
  { id: 'qwen3.5:27b', size: '~17 GB', desc: 'Qwen 3.5 27B' },
  { id: 'qwen3.5:35b', size: '~24 GB', desc: 'Qwen 3.5 35B' },
  { id: 'qwen3.5:122b', size: '~81 GB', desc: 'Qwen 3.5 122B — largest' },
  { id: 'llama3.3:latest', size: '~4.9 GB', desc: 'Llama 3.3 8B' },
  { id: 'mistral:latest', size: '~4.1 GB', desc: 'Mistral 7B' },
  { id: 'gemma3:latest', size: '~3.3 GB', desc: 'Gemma 3 4B' },
  { id: 'deepseek-r1:7b', size: '~4.7 GB', desc: 'DeepSeek R1 7B' },
  { id: 'phi4:latest', size: '~9.1 GB', desc: 'Phi-4 14B' },
];

type Tab = 'installed' | 'catalogue';

export function CommandPalette() {
  const [query, setQuery] = useState('');
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [tab, setTab] = useState<Tab>('installed');
  const [pulling, setPulling] = useState<string | null>(null);
  const [pullError, setPullError] = useState<string | null>(null);
  const [pullSuccess, setPullSuccess] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [customModel, setCustomModel] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const models = useAppStore((s) => s.models);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const setSelectedModel = useAppStore((s) => s.setSelectedModel);
  const setModels = useAppStore((s) => s.setModels);
  const setCommandPaletteOpen = useAppStore((s) => s.setCommandPaletteOpen);

  const installedIds = new Set(models.map((m) => m.id));

  const filtered = tab === 'installed'
    ? (query
        ? models.filter((m) => m.id.toLowerCase().includes(query.toLowerCase()))
        : models)
    : CATALOGUE_MODELS.filter((m) =>
        !installedIds.has(m.id) &&
        (!query || m.id.toLowerCase().includes(query.toLowerCase()) || m.desc.toLowerCase().includes(query.toLowerCase()))
      );

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    setSelectedIdx(0);
  }, [query, tab]);

  // Clear success message after a delay
  useEffect(() => {
    if (pullSuccess) {
      const t = setTimeout(() => setPullSuccess(null), 3000);
      return () => clearTimeout(t);
    }
  }, [pullSuccess]);

  const handleSelect = async (modelId: string) => {
    const previousModel = selectedModel;
    setSelectedModel(modelId);
    setCommandPaletteOpen(false);

    // Preload the model if switching to a different one
    if (modelId !== previousModel) {
      const { setModelLoading, addLogEntry } = useAppStore.getState();
      setModelLoading(true);
      addLogEntry({ timestamp: Date.now(), level: 'info', category: 'model', message: `Switching to ${modelId}...` });
      try {
        await preloadModel(modelId);
        addLogEntry({ timestamp: Date.now(), level: 'info', category: 'model', message: `${modelId} loaded` });
      } catch (e: any) {
        addLogEntry({ timestamp: Date.now(), level: 'error', category: 'model', message: `Failed to load ${modelId}: ${e.message}` });
      } finally {
        setModelLoading(false);
      }
    }
  };

  const refreshModels = async () => {
    try {
      const m = await fetchModels();
      setModels(m);
    } catch {}
  };

  const handlePull = async (modelId: string) => {
    setPulling(modelId);
    setPullError(null);
    try {
      await pullModel(modelId);
      setPullSuccess(modelId);
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(), level: 'info', category: 'model',
        message: `Downloaded ${modelId}`,
      });
      await refreshModels();
      // Auto-select the newly pulled model
      setSelectedModel(modelId);
    } catch (e: any) {
      setPullError(e.message || 'Download failed');
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(), level: 'error', category: 'model',
        message: `Download failed for ${modelId}: ${e.message}`,
      });
    } finally {
      setPulling(null);
    }
  };

  const handleDelete = async (modelId: string) => {
    if (!confirm(`Delete model ${modelId}? You can re-download it later.`)) return;
    setDeleting(modelId);
    try {
      await deleteModel(modelId);
      useAppStore.getState().addLogEntry({
        timestamp: Date.now(), level: 'info', category: 'model',
        message: `Deleted ${modelId}`,
      });
      await refreshModels();
      if (selectedModel === modelId) {
        const remaining = models.filter((m) => m.id !== modelId);
        if (remaining.length > 0) setSelectedModel(remaining[0].id);
      }
    } catch {} finally {
      setDeleting(null);
    }
  };

  const handleCustomPull = async () => {
    const name = customModel.trim();
    if (!name) return;
    await handlePull(name);
    setCustomModel('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      setCommandPaletteOpen(false);
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIdx((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter' && tab === 'installed' && filtered.length > 0) {
      e.preventDefault();
      handleSelect((filtered[selectedIdx] as any).id);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh]"
      onClick={() => setCommandPaletteOpen(false)}
    >
      {/* Backdrop */}
      <div className="fixed inset-0" style={{ background: 'rgba(0,0,0,0.5)' }} />

      {/* Palette */}
      <div
        className="relative w-full max-w-lg rounded-xl overflow-hidden"
        style={{
          background: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          boxShadow: 'var(--shadow-lg)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Tabs */}
        <div
          className="flex"
          style={{ borderBottom: '1px solid var(--color-border)' }}
        >
          {(['installed', 'catalogue'] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className="flex-1 px-4 py-2.5 text-xs font-medium transition-colors cursor-pointer"
              style={{
                color: tab === t ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
                borderBottom: tab === t ? '2px solid var(--color-accent)' : '2px solid transparent',
                background: 'transparent',
              }}
            >
              {t === 'installed' ? `Installed (${models.length})` : 'Download Models'}
            </button>
          ))}
        </div>

        {/* Search input */}
        <div
          className="flex items-center gap-3 px-4 py-3"
          style={{ borderBottom: '1px solid var(--color-border)' }}
        >
          <Search size={18} style={{ color: 'var(--color-text-tertiary)' }} />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={tab === 'installed' ? 'Search installed models...' : 'Search models to download...'}
            className="flex-1 bg-transparent outline-none text-sm"
            style={{ color: 'var(--color-text)' }}
          />
          <button
            onClick={() => setCommandPaletteOpen(false)}
            className="p-1 rounded cursor-pointer"
            style={{ color: 'var(--color-text-tertiary)' }}
          >
            <X size={16} />
          </button>
        </div>

        {/* Status messages */}
        {pullError && (
          <div className="px-4 py-2 text-xs" style={{ color: 'var(--color-error)', background: 'rgba(220,38,38,0.05)' }}>
            {pullError}
          </div>
        )}
        {pullSuccess && (
          <div className="px-4 py-2 text-xs flex items-center gap-1.5" style={{ color: 'var(--color-success)', background: 'rgba(34,197,94,0.05)' }}>
            <Check size={12} /> Downloaded {pullSuccess} successfully
          </div>
        )}

        {/* Results */}
        <div className="max-h-[300px] overflow-y-auto py-2">
          {tab === 'installed' ? (
            /* ── Installed models tab ── */
            filtered.length === 0 ? (
              <div className="px-4 py-6 text-center text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                {models.length === 0
                  ? 'No models available — switch to "Download Models" to get started'
                  : 'No matching models'}
              </div>
            ) : (
              (filtered as typeof models).map((model, idx) => {
                const isActive = model.id === selectedModel;
                const isSelected = idx === selectedIdx;
                const isDeleting = deleting === model.id;
                return (
                  <div
                    key={model.id}
                    className="flex items-center gap-3 w-full px-4 py-2.5 transition-colors"
                    style={{
                      background: isSelected ? 'var(--color-bg-secondary)' : 'transparent',
                    }}
                    onMouseEnter={() => setSelectedIdx(idx)}
                  >
                    <button
                      onClick={() => handleSelect(model.id)}
                      className="flex items-center gap-3 flex-1 min-w-0 text-left cursor-pointer"
                      style={{ background: 'none', border: 'none', padding: 0 }}
                    >
                      <Cpu size={16} style={{ color: isActive ? 'var(--color-accent)' : 'var(--color-text-tertiary)' }} />
                      <div className="flex-1 min-w-0">
                        <div
                          className="text-sm truncate"
                          style={{
                            color: isActive ? 'var(--color-accent)' : 'var(--color-text)',
                            fontWeight: isActive ? 500 : 400,
                          }}
                        >
                          {model.id}
                        </div>
                      </div>
                      {isActive && (
                        <span className="text-[10px] px-2 py-0.5 rounded-full" style={{
                          background: 'var(--color-accent-subtle)',
                          color: 'var(--color-accent)',
                        }}>
                          Active
                        </span>
                      )}
                    </button>
                    <button
                      onClick={() => handleDelete(model.id)}
                      disabled={isDeleting}
                      className="p-1 rounded transition-colors cursor-pointer opacity-0 group-hover:opacity-100"
                      style={{ color: 'var(--color-text-tertiary)' }}
                      title="Delete model"
                      onMouseEnter={(e) => (e.currentTarget.style.opacity = '1', e.currentTarget.style.color = 'var(--color-error)')}
                      onMouseLeave={(e) => (e.currentTarget.style.opacity = '0', e.currentTarget.style.color = 'var(--color-text-tertiary)')}
                    >
                      {isDeleting ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                    </button>
                  </div>
                );
              })
            )
          ) : (
            /* ── Catalogue tab ── */
            <>
              {(filtered as typeof CATALOGUE_MODELS).map((model) => {
                const isPulling = pulling === model.id;
                const justInstalled = pullSuccess === model.id;
                return (
                  <div
                    key={model.id}
                    className="flex items-center gap-3 w-full px-4 py-2.5 transition-colors"
                    style={{ background: 'transparent' }}
                  >
                    <Download size={16} style={{ color: 'var(--color-text-tertiary)' }} />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm truncate" style={{ color: 'var(--color-text)' }}>
                        {model.id}
                      </div>
                      <div className="text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
                        {model.desc} &middot; {model.size}
                      </div>
                    </div>
                    <button
                      onClick={() => handlePull(model.id)}
                      disabled={isPulling || !!pulling}
                      className="flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-medium transition-colors cursor-pointer"
                      style={{
                        background: justInstalled ? 'var(--color-accent-subtle)' : 'var(--color-accent)',
                        color: justInstalled ? 'var(--color-accent)' : '#fff',
                        opacity: (isPulling || (pulling && !isPulling)) ? 0.5 : 1,
                      }}
                    >
                      {isPulling ? (
                        <><Loader2 size={12} className="animate-spin" /> Downloading...</>
                      ) : justInstalled ? (
                        <><Check size={12} /> Installed</>
                      ) : (
                        <><Download size={12} /> Download</>
                      )}
                    </button>
                  </div>
                );
              })}

              {/* Custom model input */}
              <div
                className="px-4 py-3 mt-1"
                style={{ borderTop: '1px solid var(--color-border)' }}
              >
                <div className="text-[11px] mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
                  Or enter any Ollama model name:
                </div>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={customModel}
                    onChange={(e) => setCustomModel(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleCustomPull(); } }}
                    placeholder="e.g. codellama:7b"
                    className="flex-1 text-sm px-3 py-1.5 rounded-lg outline-none"
                    style={{
                      background: 'var(--color-bg-secondary)',
                      color: 'var(--color-text)',
                      border: '1px solid var(--color-border)',
                    }}
                  />
                  <button
                    onClick={handleCustomPull}
                    disabled={!customModel.trim() || !!pulling}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer"
                    style={{
                      background: 'var(--color-accent)',
                      color: '#fff',
                      opacity: (!customModel.trim() || pulling) ? 0.5 : 1,
                    }}
                  >
                    <Download size={12} /> Pull
                  </button>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Footer */}
        <div
          className="flex items-center gap-4 px-4 py-2 text-[11px]"
          style={{ borderTop: '1px solid var(--color-border)', color: 'var(--color-text-tertiary)' }}
        >
          {tab === 'installed' ? (
            <>
              <span><kbd className="font-mono">↑↓</kbd> Navigate</span>
              <span><kbd className="font-mono">Enter</kbd> Select</span>
              <span><kbd className="font-mono">Esc</kbd> Close</span>
            </>
          ) : (
            <span>Models are downloaded from the Ollama registry</span>
          )}
        </div>
      </div>
    </div>
  );
}
