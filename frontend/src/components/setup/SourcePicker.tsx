import { useState } from 'react';
import {
  Mail,
  Hash,
  MessageSquare,
  FolderOpen,
  FileText,
  Diamond,
  Mic,
  Calendar,
  Users,
  CheckCircle2,
} from 'lucide-react';
import { SOURCE_CATALOG, type ConnectorMeta, type SourceCard } from '../../types/connectors';

// ---------------------------------------------------------------------------
// Icon map
// ---------------------------------------------------------------------------

const ICON_MAP: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  Mail,
  Hash,
  MessageSquare,
  FolderOpen,
  FileText,
  Diamond,
  Mic,
  Calendar,
  Users,
};

// ---------------------------------------------------------------------------
// CategorySection
// ---------------------------------------------------------------------------

function CategorySection({
  category,
  label,
  cards,
  selected,
  onToggle,
}: {
  category: string;
  label: string;
  cards: ConnectorMeta[];
  selected: Set<string>;
  onToggle: (id: string) => void;
}) {
  return (
    <div className="mb-6">
      <h3 className="text-xs font-semibold uppercase tracking-wider mb-3"
        style={{ color: 'var(--color-text-tertiary)' }}>
        {label}
      </h3>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {cards.map((card) => {
          const Icon = ICON_MAP[card.icon] ?? Mail;
          const isSelected = selected.has(card.connector_id);
          return (
            <button
              key={card.connector_id}
              onClick={() => onToggle(card.connector_id)}
              className="relative flex flex-col items-start gap-2 p-4 rounded-xl text-left transition-all"
              style={{
                background: isSelected
                  ? 'var(--color-accent-subtle)'
                  : 'var(--color-surface)',
                border: isSelected
                  ? '1.5px solid var(--color-accent)'
                  : '1.5px solid var(--color-border)',
              }}
            >
              {isSelected && (
                <CheckCircle2
                  size={16}
                  className="absolute top-3 right-3"
                  style={{ color: 'var(--color-accent)' }}
                />
              )}
              <div
                className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
                style={{ background: 'var(--color-bg-tertiary)' }}
              >
                <Icon size={18} className={card.color} />
              </div>
              <div>
                <div
                  className="text-sm font-semibold leading-snug"
                  style={{ color: 'var(--color-text)' }}
                >
                  {card.display_name}
                </div>
                <div
                  className="text-xs leading-snug mt-0.5"
                  style={{ color: 'var(--color-text-tertiary)' }}
                >
                  {card.description}
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SourcePicker
// ---------------------------------------------------------------------------

const CATEGORIES: { key: 'communication' | 'documents' | 'pim'; label: string }[] = [
  { key: 'communication', label: 'Communication' },
  { key: 'documents', label: 'Documents' },
  { key: 'pim', label: 'Personal Info' },
];

export function SourcePicker({ onContinue }: { onContinue: (selectedIds: string[]) => void }) {
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="mb-6">
        <h2 className="text-xl font-bold mb-1" style={{ color: 'var(--color-text)' }}>
          Connect your sources
        </h2>
        <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
          Choose which data sources to include in your personal knowledge base.
        </p>
      </div>

      {/* Cards by category */}
      <div className="flex-1 overflow-y-auto">
        {CATEGORIES.map(({ key, label }) => (
          <CategorySection
            key={key}
            category={key}
            label={label}
            cards={SOURCE_CATALOG.filter((s) => s.category === key)}
            selected={selected}
            onToggle={toggle}
          />
        ))}
      </div>

      {/* Footer */}
      <div className="pt-4 border-t" style={{ borderColor: 'var(--color-border)' }}>
        <button
          onClick={() => onContinue(Array.from(selected))}
          disabled={selected.size === 0}
          className="w-full py-3 px-4 rounded-xl font-semibold text-sm transition-all"
          style={{
            background: selected.size > 0 ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
            color: selected.size > 0 ? 'white' : 'var(--color-text-tertiary)',
            cursor: selected.size > 0 ? 'pointer' : 'not-allowed',
          }}
        >
          {selected.size === 0
            ? 'Select sources to continue'
            : `Connect ${selected.size} source${selected.size !== 1 ? 's' : ''}`}
        </button>
      </div>
    </div>
  );
}
