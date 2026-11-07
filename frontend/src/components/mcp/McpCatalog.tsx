import { useState } from 'react';
import { ExternalLink, Plus, Search } from 'lucide-react';
import catalogData from '../../data/mcp-catalog.json';
import { searchCatalog, type McpCatalogEntry, type McpCatalogKind } from '../../lib/mcp-api';
import { inputStyle, mutedText, smallButton } from './McpServerParts';

export const MCP_CATALOG = catalogData.entries as McpCatalogEntry[];

const CATEGORY_LABELS: Record<string, string> = {
  productivity: 'Productivity',
  communication: 'Communication',
  dev: 'Developer',
  data: 'Data',
  files: 'Files',
  search: 'Search',
  web: 'Web',
  payments: 'Payments',
  design: 'Design',
  utilities: 'Utilities',
};

const KIND_LABELS: Record<McpCatalogKind, { label: string; title: string }> = {
  official: { label: 'Official', title: 'Made by the service itself' },
  reference: { label: 'Reference', title: 'Reference server from modelcontextprotocol/servers' },
  community: { label: 'Community', title: 'Maintained by a third party' },
};

export function McpCatalogCard({ entry, onPick }: { entry: McpCatalogEntry; onPick: () => void }) {
  const kind = KIND_LABELS[entry.kind];
  return (
    <li className="rounded-lg p-3 flex flex-col gap-1.5" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium truncate" style={{ color: 'var(--color-text)' }}>
          {entry.name}
        </span>
        <span
          className="text-[10px] px-1 rounded shrink-0"
          title={kind.title}
          style={{
            ...mutedText,
            border: '1px solid var(--color-border)',
            ...(entry.kind === 'official' ? { color: 'var(--color-accent)', borderColor: 'var(--color-accent)' } : {}),
          }}
        >
          {kind.label}
        </span>
      </div>
      <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
        {entry.description}
      </div>
      <div className="text-[11px]" style={mutedText}>
        {entry.server.transport === 'http' ? 'Remote (HTTP)' : 'Local (stdio)'} · {entry.auth_note}
      </div>
      <div className="flex items-center justify-between gap-2 mt-auto pt-1">
        <a href={entry.source} target="_blank" rel="noreferrer" className="text-[11px] flex items-center gap-1" style={mutedText}>
          <ExternalLink size={10} /> Docs
        </a>
        {entry.requires_oauth ? (
          <span className="text-[11px]" style={mutedText} title="This server only accepts OAuth sign-in">
            Needs OAuth — not supported yet
          </span>
        ) : (
          <button type="button" onClick={onPick} className={smallButton} style={inputStyle} aria-label={`Add ${entry.name}`}>
            <Plus size={11} /> Add
          </button>
        )}
      </div>
    </li>
  );
}

export function McpCatalog({
  entries = MCP_CATALOG,
  onPick,
  onCustom,
}: {
  entries?: McpCatalogEntry[];
  onPick: (entry: McpCatalogEntry) => void;
  onCustom: () => void;
}) {
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState<string | null>(null);
  const categories = [...new Set(entries.map((e) => e.category))];
  // Servers that can be added now come first; OAuth-only ones last.
  const shown = searchCatalog(entries, query, category).sort(
    (a, b) => Number(!!a.requires_oauth) - Number(!!b.requires_oauth),
  );
  const chip = (active: boolean) => ({
    ...inputStyle,
    ...(active ? { background: 'var(--color-accent)', color: 'white', borderColor: 'var(--color-accent)' } : {}),
  });

  return (
    <div>
      <div className="flex items-center justify-between gap-3 mb-3">
        <h2 className="text-base font-semibold" style={{ color: 'var(--color-text)' }}>
          Add MCP server
        </h2>
        <button type="button" onClick={onCustom} className={smallButton} style={inputStyle}>
          <Plus size={11} /> Custom server
        </button>
      </div>
      <p className="text-xs mb-3" style={mutedText}>
        Pick a server to pre-fill the form, then add your own token, test and save. Entries link to the docs they were checked against.
      </p>
      <label className="flex items-center gap-2 px-2 py-1.5 rounded mb-2" style={inputStyle}>
        <Search size={12} style={mutedText} />
        <input
          className="flex-1 bg-transparent text-xs outline-none"
          placeholder="Search servers"
          aria-label="Search servers"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      <div className="flex flex-wrap gap-1 mb-3">
        <button type="button" className={smallButton} style={chip(category === null)} onClick={() => setCategory(null)}>
          All
        </button>
        {categories.map((c) => (
          <button key={c} type="button" className={smallButton} style={chip(category === c)} onClick={() => setCategory(c)}>
            {CATEGORY_LABELS[c] || c}
          </button>
        ))}
      </div>
      {shown.length === 0 ? (
        <div className="text-xs" style={mutedText}>
          No match. Use “Custom server” to add any MCP server by URL or command.
        </div>
      ) : (
        <ul className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))' }}>
          {shown.map((entry) => (
            <McpCatalogCard key={entry.id} entry={entry} onPick={() => onPick(entry)} />
          ))}
        </ul>
      )}
    </div>
  );
}
