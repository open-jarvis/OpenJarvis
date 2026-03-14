import { useRef, useEffect } from 'react';
import { ScrollText, Copy, Trash2 } from 'lucide-react';
import { useAppStore } from '../lib/store';

const LEVEL_COLORS: Record<string, string> = {
  info: 'var(--color-text)',
  warn: 'var(--color-warning)',
  error: 'var(--color-error)',
};

function formatTime(ts: number): string {
  const d = new Date(ts);
  return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function LogsPage() {
  const logEntries = useAppStore((s) => s.logEntries);
  const clearLogs = useAppStore((s) => s.clearLogs);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logEntries.length]);

  const handleCopy = async () => {
    const text = logEntries
      .map((e) => `${formatTime(e.timestamp)} [${e.level}] [${e.category}] ${e.message}`)
      .join('\n');
    await navigator.clipboard.writeText(text);
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden p-6">
      <div className="max-w-4xl mx-auto w-full flex flex-col flex-1 overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-3 mb-4 shrink-0">
          <ScrollText size={24} style={{ color: 'var(--color-accent)' }} />
          <h1 className="text-xl font-semibold flex-1" style={{ color: 'var(--color-text)' }}>
            Logs
          </h1>
          <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            {logEntries.length} entries
          </span>
          <button
            onClick={handleCopy}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer"
            style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
          >
            <Copy size={12} /> Copy All
          </button>
          <button
            onClick={clearLogs}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer"
            style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
          >
            <Trash2 size={12} /> Clear
          </button>
        </div>

        {/* Log entries */}
        <div
          className="flex-1 overflow-y-auto rounded-xl p-4 font-mono text-xs leading-relaxed"
          style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
        >
          {logEntries.length === 0 ? (
            <div className="text-center py-12" style={{ color: 'var(--color-text-tertiary)' }}>
              No log entries yet. Logs appear as you chat, switch models, and interact with the app.
            </div>
          ) : (
            logEntries.map((entry, i) => (
              <div key={i} className="py-0.5">
                <span style={{ color: 'var(--color-text-tertiary)' }}>{formatTime(entry.timestamp)}</span>
                {' '}
                <span style={{ color: LEVEL_COLORS[entry.level] || 'var(--color-text)' }}>
                  [{entry.category}]
                </span>
                {' '}
                <span style={{ color: LEVEL_COLORS[entry.level] || 'var(--color-text)' }}>
                  {entry.message}
                </span>
              </div>
            ))
          )}
          <div ref={bottomRef} />
        </div>
      </div>
    </div>
  );
}
