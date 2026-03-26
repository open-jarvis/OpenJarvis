import { Sparkles, MessageSquare, ArrowRight } from 'lucide-react';
import { SOURCE_CATALOG } from '../../types/connectors';

// ---------------------------------------------------------------------------
// Starter queries
// ---------------------------------------------------------------------------

function getStarterQueries(connectedSources: string[]): string[] {
  const queries: string[] = [];
  const has = (id: string) => connectedSources.includes(id);

  if (has('gmail') || has('gmail_imap')) {
    queries.push('What emails need my attention today?');
  }
  if (has('gcalendar')) {
    queries.push("What's on my calendar this week?");
  }
  if (has('slack')) {
    queries.push('Summarize important Slack messages from yesterday');
  }
  if (has('gdrive') || has('notion') || has('obsidian')) {
    queries.push('Find my notes about project planning');
  }
  if (has('imessage')) {
    queries.push('What have I been texting about lately?');
  }
  if (has('gcontacts')) {
    queries.push('Who are my most frequent collaborators?');
  }
  if (has('granola')) {
    queries.push('Summarize my recent meeting notes');
  }

  // Fallback defaults
  if (queries.length === 0) {
    return [
      'What should I focus on today?',
      'Summarize my recent activity',
      'Help me draft a quick update',
    ];
  }

  return queries.slice(0, 3);
}

// ---------------------------------------------------------------------------
// StarterCard
// ---------------------------------------------------------------------------

function StarterCard({
  query,
  onSelect,
}: {
  query: string;
  onSelect: (q: string) => void;
}) {
  return (
    <button
      onClick={() => onSelect(query)}
      className="flex items-center justify-between gap-3 w-full px-4 py-3 rounded-xl text-left transition-all group"
      style={{
        background: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
      }}
    >
      <div className="flex items-center gap-3">
        <MessageSquare size={16} style={{ color: 'var(--color-accent)', flexShrink: 0 }} />
        <span className="text-sm" style={{ color: 'var(--color-text)' }}>
          {query}
        </span>
      </div>
      <ArrowRight
        size={14}
        className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
        style={{ color: 'var(--color-text-tertiary)' }}
      />
    </button>
  );
}

// ---------------------------------------------------------------------------
// ReadyScreen
// ---------------------------------------------------------------------------

export function ReadyScreen({
  connectedSources,
  onStart,
}: {
  connectedSources: string[];
  onStart: (query?: string) => void;
}) {
  const starters = getStarterQueries(connectedSources);

  const connectedCards = connectedSources
    .map((id) => SOURCE_CATALOG.find((c) => c.connector_id === id))
    .filter(Boolean);

  return (
    <div className="flex flex-col items-center text-center h-full justify-center gap-6">
      {/* Icon */}
      <div
        className="w-20 h-20 rounded-2xl flex items-center justify-center"
        style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}
      >
        <Sparkles size={36} />
      </div>

      {/* Headline */}
      <div>
        <h2 className="text-2xl font-bold mb-2" style={{ color: 'var(--color-text)' }}>
          You're all set!
        </h2>
        <p className="text-sm max-w-sm" style={{ color: 'var(--color-text-secondary)' }}>
          {connectedCards.length > 0
            ? `Connected ${connectedCards.length} source${connectedCards.length !== 1 ? 's' : ''}: ${connectedCards.map((c) => c!.display_name).join(', ')}.`
            : 'Your personal AI is ready to help.'}
          {' '}Ask anything about your work and life.
        </p>
      </div>

      {/* Starter queries */}
      <div className="w-full max-w-sm flex flex-col gap-2">
        <p className="text-xs font-semibold uppercase tracking-wider mb-1 text-left"
          style={{ color: 'var(--color-text-tertiary)' }}>
          Try asking
        </p>
        {starters.map((q) => (
          <StarterCard key={q} query={q} onSelect={onStart} />
        ))}
      </div>

      {/* Open Chat button */}
      <button
        onClick={() => onStart()}
        className="px-8 py-3 rounded-xl font-semibold text-sm transition-all"
        style={{ background: 'var(--color-accent)', color: 'white' }}
      >
        Open Chat
      </button>
    </div>
  );
}
