import { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Database,
  FileText,
  Link2,
  Search,
  Shield,
} from 'lucide-react';
import {
  fetchCanonicalTasks,
  fetchVaultMemoryCandidates,
  fetchVaultMemoryConflicts,
  fetchVaultMemoryHealth,
  fetchVaultMemoryLinks,
  fetchVaultMemoryNote,
  reviewVaultMemory,
  searchVaultStructure,
  searchVaultMemory,
} from '../lib/api';
import type {
  CanonicalTask,
  VaultMemoryCandidate,
  VaultMemoryConflict,
  VaultMemoryHealth,
  VaultMemoryLinks,
  VaultMemoryNote,
  VaultMemoryRetrieval,
  VaultMemorySource,
} from '../lib/api';

const EVIDENCE_COLORS: Record<string, string> = {
  sufficient: 'var(--color-success)',
  partial: 'var(--color-warning)',
  insufficient: 'var(--color-error)',
  conflicting: 'var(--color-error)',
  unavailable: 'var(--color-text-tertiary)',
};

function shortId(value: string): string {
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}

function countLinks(links: VaultMemoryLinks | null, key: 'outgoing' | 'backlinks'): number {
  return links?.[key]?.length ?? 0;
}

export function EvidenceSources({
  sources,
  onSelect,
}: {
  sources: VaultMemorySource[];
  onSelect?: (noteId: string) => void;
}) {
  if (sources.length === 0) {
    return (
      <div className="rounded-lg px-4 py-3 text-sm" style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-warning)' }}>
        insufficient_evidence — no vault source was selected.
      </div>
    );
  }
  return (
    <div className="space-y-2" aria-label="Selected memory sources">
      {sources.map(source => (
        <button
          type="button"
          key={source.source_id}
          onClick={() => onSelect?.(source.note_id)}
          className="w-full text-left rounded-lg px-3 py-3 cursor-pointer"
          style={{ background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)' }}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
              {source.title}
            </span>
            <span className="text-[11px] font-mono" style={{ color: 'var(--color-text-tertiary)' }}>
              {source.path}
            </span>
          </div>
          <p className="text-xs mt-2 line-clamp-3" style={{ color: 'var(--color-text-secondary)' }}>
            {source.relevant_text}
          </p>
          <div className="flex flex-wrap gap-3 mt-2 text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
            <span>{source.note_type}</span>
            <span>{source.trust_class}</span>
            <span>{source.retrieval_class}</span>
            <span style={{ color: source.authority_class === 'none' ? undefined : 'var(--color-error)' }}>
              {source.authority_class}
            </span>
            <span>Note {shortId(source.note_id)}</span>
            <span>
              {source.section || 'span'}
              {source.line_start ? ` · lines ${source.line_start}${source.line_end ? `–${source.line_end}` : ''}` : ''}
            </span>
            <span>score {source.score.toFixed(3)}</span>
            <span>{source.selection_reason}</span>
          </div>
        </button>
      ))}
    </div>
  );
}

export function MemoryVaultPanel() {
  const [health, setHealth] = useState<VaultMemoryHealth | null>(null);
  const [tasks, setTasks] = useState<CanonicalTask[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState('');
  const [query, setQuery] = useState('');
  const [searchMode, setSearchMode] = useState<'normal' | 'review' | 'structure'>('normal');
  const [retrieval, setRetrieval] = useState<VaultMemoryRetrieval | null>(null);
  const [candidates, setCandidates] = useState<VaultMemoryCandidate[]>([]);
  const [conflicts, setConflicts] = useState<VaultMemoryConflict[]>([]);
  const [note, setNote] = useState<VaultMemoryNote | null>(null);
  const [links, setLinks] = useState<VaultMemoryLinks | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const nextHealth = await fetchVaultMemoryHealth();
      setHealth(nextHealth);
      if (!nextHealth.vault_configured) return;
      const [nextTasks, nextCandidates, nextConflicts] = await Promise.all([
        fetchCanonicalTasks(),
        fetchVaultMemoryCandidates(),
        fetchVaultMemoryConflicts(),
      ]);
      setTasks(nextTasks);
      setCandidates(nextCandidates);
      setConflicts(nextConflicts);
      setSelectedTaskId(current =>
        current && nextTasks.some(task => task.task_id === current)
          ? current
          : nextTasks[0]?.task_id ?? '',
      );
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const runSearch = useCallback(async () => {
    const selected = tasks.find(task => task.task_id === selectedTaskId);
    if (!query.trim() || (searchMode === 'normal' && !selected)) return;
    setSearching(true);
    setError(null);
    try {
      const result = searchMode === 'review'
        ? await reviewVaultMemory(query.trim())
        : searchMode === 'structure'
          ? await searchVaultStructure(query.trim())
          : await searchVaultMemory(query.trim(), {
              task_id: selected!.task_id,
              session_id: selected!.session_id,
              correlation_id: selected!.correlation_id,
            });
      setRetrieval(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSearching(false);
    }
  }, [query, searchMode, selectedTaskId, tasks]);

  const selectSource = useCallback(async (noteId: string) => {
    setError(null);
    try {
      const [nextNote, nextLinks] = await Promise.all([
        fetchVaultMemoryNote(noteId),
        fetchVaultMemoryLinks(noteId),
      ]);
      setNote(nextNote);
      setLinks(nextLinks);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  if (health && !health.vault_configured) {
    return (
      <section className="rounded-xl p-6" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
        <div className="flex items-center gap-2">
          <Database size={16} style={{ color: 'var(--color-text-tertiary)' }} />
          <h2 className="text-sm font-semibold">Vault memory is not configured</h2>
        </div>
        <p className="text-sm mt-2" style={{ color: 'var(--color-text-secondary)' }}>
          No default vault is created or probed. Configure an explicit existing test vault to enable this view.
        </p>
      </section>
    );
  }

  return (
    <div className="space-y-4">
      {error && (
        <div className="rounded-lg px-4 py-3 text-sm" style={{ color: 'var(--color-error)', background: 'color-mix(in srgb, var(--color-error) 10%, transparent)' }}>
          {error}
        </div>
      )}

      {health && (
        <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            ['Discovered', health.discovered_count],
            ['Schema valid', health.schema_valid_count],
            ['FTS documents', health.fts_document_count],
            ['Normal retrieval', health.retrieval_eligible_count],
            ['Review only', health.review_only_count],
            ['Authority sensitive', health.authority_sensitive_count],
            ['Parser errors', health.parser_error_count],
            ['Rejected', health.rejected_count],
          ].map(([label, value]) => (
            <div key={String(label)} className="rounded-xl p-4" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
              <div className="text-xl font-semibold">{String(value)}</div>
              <div className="text-xs mt-1" style={{ color: 'var(--color-text-secondary)' }}>{String(label)}</div>
            </div>
          ))}
          <div className="col-span-2 md:col-span-4 flex flex-wrap gap-3 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            <span className="flex items-center gap-1"><Shield size={12} />{health.mode}</span>
            <span className="flex items-center gap-1">
              {health.fts5_available ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
              {health.retrieval_mode}
            </span>
            <span>Embeddings {health.embeddings_enabled ? 'enabled' : 'disabled'}</span>
          </div>
        </section>
      )}

      <section className="rounded-xl p-4" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
        <div className="flex items-center gap-2 mb-3">
          <Search size={15} style={{ color: 'var(--color-accent)' }} />
          <h2 className="text-sm font-semibold">Evidence-bound search</h2>
        </div>
        <div className="grid md:grid-cols-[minmax(150px,0.5fr)_minmax(180px,0.7fr)_minmax(260px,1.4fr)_auto] gap-2">
          <select
            value={searchMode}
            onChange={event => setSearchMode(event.target.value as 'normal' | 'review' | 'structure')}
            className="rounded-lg px-3 py-2 text-sm"
            style={{ background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)' }}
            aria-label="Vault query boundary"
          >
            <option value="normal">Normal memory</option>
            <option value="review">Explicit review only</option>
            <option value="structure">Vault structure only</option>
          </select>
          <select
            value={selectedTaskId}
            onChange={event => setSelectedTaskId(event.target.value)}
            disabled={searchMode !== 'normal'}
            className="rounded-lg px-3 py-2 text-sm"
            style={{ background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)' }}
            aria-label="Canonical task"
          >
            {tasks.length === 0 && <option value="">No canonical task available</option>}
            {tasks.map(task => (
              <option key={task.task_id} value={task.task_id}>
                {task.description.slice(0, 48)} · {shortId(task.task_id)}
              </option>
            ))}
          </select>
          <input
            value={query}
            onChange={event => setQuery(event.target.value)}
            onKeyDown={event => {
              if (event.key === 'Enter') runSearch();
            }}
            placeholder="Search the configured synthetic or approved vault"
            className="rounded-lg px-3 py-2 text-sm outline-none"
            style={{ background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)' }}
          />
          <button
            type="button"
            onClick={runSearch}
            disabled={!query.trim() || (searchMode === 'normal' && !selectedTaskId) || searching}
            className="rounded-lg px-4 py-2 text-sm font-medium disabled:opacity-50 cursor-pointer"
            style={{ background: 'var(--color-accent)', color: 'var(--color-bg)' }}
          >
            {searching ? 'Searching…' : 'Search'}
          </button>
        </div>
        {searchMode !== 'normal' && (
          <p className="mt-2 text-xs" style={{ color: 'var(--color-warning)' }}>
            This explicit inspection is isolated from task context and grants no runtime authority.
          </p>
        )}
      </section>

      {retrieval && (
        <section className="rounded-xl p-4" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
          <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
            <h2 className="text-sm font-semibold">Actually used sources</h2>
            <span className="text-xs font-medium" style={{ color: EVIDENCE_COLORS[retrieval.evidence_status] }}>
              {retrieval.evidence_code} · confidence {retrieval.confidence.toFixed(2)}
            </span>
          </div>
          <p className="text-xs mb-3" style={{ color: 'var(--color-text-tertiary)' }}>
            Query boundary: {retrieval.retrieval_purpose}
          </p>
          {retrieval.warnings.length > 0 && (
            <p className="text-xs mb-3" style={{ color: 'var(--color-warning)' }}>
              {retrieval.warnings.join(' · ')}
            </p>
          )}
          <EvidenceSources sources={retrieval.selected_sources} onSelect={selectSource} />
        </section>
      )}

      <div className="grid lg:grid-cols-2 gap-4">
        <section className="rounded-xl p-4" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
          <h2 className="text-sm font-semibold mb-3">Recent memory writes</h2>
          {candidates.length === 0 ? (
            <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>No candidates.</p>
          ) : candidates.map(candidate => (
            <details key={candidate.candidate_id} className="mb-2 rounded-lg p-3" style={{ background: 'var(--color-bg-tertiary)' }}>
              <summary className="cursor-pointer text-sm">
                {candidate.note_type} · {candidate.status}
              </summary>
              <div className="mt-2 text-xs space-y-1" style={{ color: 'var(--color-text-secondary)' }}>
                <div>Note {shortId(candidate.note_id)}</div>
                <div>{candidate.proposed_path}</div>
                <div>Conflict {candidate.conflict_state}</div>
              </div>
              <pre className="mt-3 p-2 rounded overflow-auto text-[11px] max-h-56" style={{ background: 'var(--color-bg)', color: 'var(--color-text-secondary)' }}>
                {candidate.planned_diff}
              </pre>
            </details>
          ))}
        </section>

        <section className="rounded-xl p-4" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
          <h2 className="text-sm font-semibold mb-3">Open conflicts</h2>
          {conflicts.length === 0 ? (
            <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>No open conflicts.</p>
          ) : conflicts.map(conflict => (
            <div key={conflict.conflict_id} className="mb-2 rounded-lg p-3 text-sm" style={{ background: 'var(--color-bg-tertiary)', borderLeft: '3px solid var(--color-error)' }}>
              <div className="font-medium">{conflict.conflict_type} · {conflict.state}</div>
              <p className="text-xs mt-1" style={{ color: 'var(--color-text-secondary)' }}>{conflict.summary}</p>
              <div className="text-[11px] mt-2 font-mono" style={{ color: 'var(--color-text-tertiary)' }}>
                {conflict.note_ids.map(shortId).join(' · ')}
              </div>
            </div>
          ))}
        </section>
      </div>

      {note && (
        <section className="rounded-xl p-4" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <FileText size={15} />
              <h2 className="text-sm font-semibold">{note.title}</h2>
            </div>
            <span className="text-xs font-mono" style={{ color: 'var(--color-text-tertiary)' }}>{note.path}</span>
          </div>
          <div className="flex flex-wrap gap-3 mt-2 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            <span>Note {shortId(note.note_id)}</span>
            <span>{note.identity_kind}</span>
            <span>{note.note_type}</span>
            <span>{note.trust_class}</span>
            <span>{note.retrieval_class}</span>
            <span style={{ color: note.authority_class === 'none' ? undefined : 'var(--color-error)' }}>
              {note.authority_class}
            </span>
            <span>{note.scope_class}</span>
            <span>{note.parse_status}</span>
            <span>{note.conflict_state}</span>
            <span className="flex items-center gap-1"><Link2 size={11} />{countLinks(links, 'outgoing')} links · {countLinks(links, 'backlinks')} backlinks</span>
          </div>
          <p className="mt-3 text-sm whitespace-pre-wrap line-clamp-6" style={{ color: 'var(--color-text-secondary)' }}>
            {note.body.slice(0, 1200)}
          </p>
        </section>
      )}
    </div>
  );
}
