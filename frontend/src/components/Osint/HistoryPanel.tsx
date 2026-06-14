import { useState, useEffect, useCallback } from 'react';
import {
  Clock,
  Star,
  Target,
  Trash2,
  Shield,
  Terminal,
  ChevronDown,
  ChevronUp,
  Loader2,
  AlertTriangle,
  Zap,
  ArrowRight,
} from 'lucide-react';
import {
  fetchOsintHistory,
  deleteHistoryEntry,
  clearHistory,
  fetchFavorites,
  fetchOsintToolDetail,
  type HistoryEntry,
} from '../Desktop/lib/api';

const API_URL = (import.meta.env.VITE_API_URL as string) || 'http://127.0.0.1:8000';

type Tab = 'history' | 'favorites' | 'recent';

export function HistoryPanel() {
  const [activeTab, setActiveTab] = useState<Tab>('history');
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [favorites, setFavorites] = useState<string[]>([]);
  const [favoriteTools, setFavoriteTools] = useState<Record<string, { name: string; category: string; description: string }>>({});
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadHistory = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await fetchOsintHistory(API_URL, 50);
      setHistory(data.entries);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load history');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadFavorites = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const data = await fetchFavorites(API_URL);
      setFavorites(data.favorites);
      // Load tool details for favorites
      const details: Record<string, { name: string; category: string; description: string }> = {};
      for (const name of data.favorites) {
        try {
          const tool = await fetchOsintToolDetail(API_URL, name);
          details[name] = tool;
        } catch {
          details[name] = { name, category: 'Unknown', description: '' };
        }
      }
      setFavoriteTools(details);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load favorites');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'history') loadHistory();
    else if (activeTab === 'favorites') loadFavorites();
    else if (activeTab === 'recent') loadHistory();
  }, [activeTab, loadHistory, loadFavorites]);

  const handleDelete = async (id: string) => {
    try {
      await deleteHistoryEntry(API_URL, id);
      setHistory((prev) => prev.filter((e) => e.id !== id));
    } catch {
      // ignore
    }
  };

  const handleClearAll = async () => {
    if (!window.confirm('Clear all history? This cannot be undone.')) return;
    try {
      await clearHistory(API_URL);
      setHistory([]);
    } catch {
      // ignore
    }
  };

  const handleRerun = (target: string) => {
    window.dispatchEvent(new CustomEvent('osint-watchdog-target', { detail: target }));
    window.dispatchEvent(new CustomEvent('osint-tab-change', { detail: 'watchdog' }));
  };

  const recentTargets = history
    .filter((e) => e.target)
    .map((e) => e.target!)
    .filter((v, i, a) => a.indexOf(v) === i)
    .slice(0, 10);

  const tabs: { key: Tab; label: string; icon: React.ElementType }[] = [
    { key: 'history', label: 'History', icon: Clock },
    { key: 'favorites', label: 'Favorites', icon: Star },
    { key: 'recent', label: 'Recent Targets', icon: Target },
  ];

  return (
    <div className="flex flex-col gap-4 max-w-4xl mx-auto">
      <div className="flex gap-2">
        {tabs.map((t) => {
          const Icon = t.icon;
          const isActive = activeTab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => setActiveTab(t.key)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer"
              style={{
                background: isActive ? 'var(--color-accent-subtle)' : 'var(--color-bg-secondary)',
                color: isActive ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                border: `1px solid ${isActive ? 'var(--color-accent-muted)' : 'var(--color-border)'}`,
              }}
            >
              <Icon size={12} />
              {t.label}
            </button>
          );
        })}
      </div>

      {error && (
        <div
          className="px-4 py-3 rounded-lg text-sm flex items-center gap-2"
          style={{
            background: 'color-mix(in srgb, var(--color-error) 8%, transparent)',
            border: '1px solid color-mix(in srgb, var(--color-error) 15%, transparent)',
            color: 'var(--color-error)',
          }}
        >
          <AlertTriangle size={14} />
          {error}
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-2 text-xs py-8 justify-center" style={{ color: 'var(--color-text-tertiary)' }}>
          <Loader2 size={14} className="animate-spin" />
          Loading...
        </div>
      )}

      {!loading && activeTab === 'history' && (
        <div className="flex flex-col gap-2">
          {history.length > 0 && (
            <div className="flex justify-end">
              <button
                onClick={handleClearAll}
                className="flex items-center gap-1.5 text-[10px] px-2 py-1 rounded-md cursor-pointer"
                style={{ color: 'var(--color-error)', border: '1px solid var(--color-error-muted)' }}
              >
                <Trash2 size={10} />
                Clear All
              </button>
            </div>
          )}
          {history.length === 0 && (
            <div className="text-sm py-8 text-center" style={{ color: 'var(--color-text-tertiary)' }}>
              No history yet. Run a scan or execute a tool.
            </div>
          )}
          {history.map((entry) => (
            <HistoryCard
              key={entry.id}
              entry={entry}
              expanded={expandedId === entry.id}
              onToggle={() => setExpandedId(expandedId === entry.id ? null : entry.id)}
              onDelete={() => handleDelete(entry.id)}
              onRerun={entry.type === 'scan' && entry.target ? () => handleRerun(entry.target!) : undefined}
            />
          ))}
        </div>
      )}

      {!loading && activeTab === 'favorites' && (
        <div className="flex flex-col gap-2">
          {favorites.length === 0 && (
            <div className="text-sm py-8 text-center" style={{ color: 'var(--color-text-tertiary)' }}>
              No favorites yet. Click the star on any tool card.
            </div>
          )}
          {favorites.map((name) => {
            const tool = favoriteTools[name];
            return (
              <div
                key={name}
                className="rounded-lg p-3 flex items-center justify-between gap-3"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
              >
                <div className="flex items-center gap-2">
                  <Star size={14} style={{ color: 'var(--color-accent)' }} fill="currentColor" />
                  <div className="flex flex-col">
                    <span className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                      {tool?.name || name}
                    </span>
                    {tool?.category && (
                      <span className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
                        {tool.category}
                      </span>
                    )}
                  </div>
                </div>
                {tool?.description && (
                  <span className="text-xs truncate flex-1" style={{ color: 'var(--color-text-secondary)' }}>
                    {tool.description}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}

      {!loading && activeTab === 'recent' && (
        <div className="flex flex-col gap-2">
          {recentTargets.length === 0 && (
            <div className="text-sm py-8 text-center" style={{ color: 'var(--color-text-tertiary)' }}>
              No recent targets yet. Run a scan first.
            </div>
          )}
          {recentTargets.map((target) => (
            <button
              key={target}
              onClick={() => handleRerun(target)}
              className="rounded-lg p-3 flex items-center justify-between gap-3 text-left transition-colors cursor-pointer hover:opacity-90 w-full"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <div className="flex items-center gap-2">
                <Target size={14} style={{ color: 'var(--color-accent)' }} />
                <span className="text-sm font-mono" style={{ color: 'var(--color-text)' }}>
                  {target}
                </span>
              </div>
              <ArrowRight size={14} style={{ color: 'var(--color-text-tertiary)' }} />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function HistoryCard({
  entry,
  expanded,
  onToggle,
  onDelete,
  onRerun,
}: {
  entry: HistoryEntry;
  expanded: boolean;
  onToggle: () => void;
  onDelete: () => void;
  onRerun?: () => void;
}) {
  const isScan = entry.type === 'scan';
  const Icon = isScan ? Shield : Terminal;
  const date = new Date(entry.timestamp).toLocaleString();

  return (
    <div
      className="rounded-lg p-3 flex flex-col gap-2"
      style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 flex-1">
          <Icon size={14} style={{ color: isScan ? 'var(--color-accent)' : 'var(--color-text-tertiary)' }} />
          <span className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
            {isScan ? `Scan: ${entry.target}` : `Exec: ${entry.tool_name}`}
          </span>
          <span
            className="text-[10px] px-1.5 py-0.5 rounded-full"
            style={{
              background: entry.success
                ? 'color-mix(in srgb, var(--color-success) 12%, transparent)'
                : 'color-mix(in srgb, var(--color-error) 12%, transparent)',
              color: entry.success ? 'var(--color-success)' : 'var(--color-error)',
            }}
          >
            {entry.success ? 'Success' : 'Failed'}
          </span>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <span className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
            {date}
          </span>
          <button
            onClick={onToggle}
            className="p-1 rounded transition-colors cursor-pointer"
            style={{ color: 'var(--color-text-tertiary)' }}
            title="Toggle details"
          >
            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
          {isScan && onRerun && (
            <button
              onClick={onRerun}
              className="p-1 rounded transition-colors cursor-pointer"
              style={{ color: 'var(--color-accent)' }}
              title="Rerun scan"
            >
              <Zap size={14} />
            </button>
          )}
          <button
            onClick={onDelete}
            className="p-1 rounded transition-colors cursor-pointer"
            style={{ color: 'var(--color-error)' }}
            title="Delete entry"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {expanded && (
        <div className="rounded-md p-2 overflow-auto max-h-64">
          {isScan && entry.results && (
            <pre
              className="text-[11px] font-mono whitespace-pre-wrap"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              {JSON.stringify(entry.results, null, 2)}
            </pre>
          )}
          {!isScan && entry.output && (
            <pre
              className="text-[11px] font-mono whitespace-pre-wrap"
              style={{ color: 'var(--color-text-secondary)' }}
            >
              {entry.output}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
