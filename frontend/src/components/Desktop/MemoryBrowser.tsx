import { useState, useEffect, useCallback } from 'react';
import type React from 'react';
import { invoke } from '@tauri-apps/api/core';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MemoryChunk {
  content: string;
  score: number;
  metadata: Record<string, string | number | boolean>;
}

interface SearchResponse {
  results: MemoryChunk[];
  query: string;
  total: number;
}

interface MemoryStats {
  backend: string;
  total_documents: number;
  total_chunks: number;
  index_size_bytes: number;
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles: Record<string, React.CSSProperties> = {
  container: {
    backgroundColor: '#1e1e2e',
    color: '#cdd6f4',
    padding: 24,
    borderRadius: 12,
    fontFamily: 'system-ui, -apple-system, sans-serif',
    minHeight: 400,
  },
  header: {
    fontSize: 20,
    fontWeight: 700,
    marginBottom: 20,
    color: '#cdd6f4',
  },
  searchBar: {
    display: 'flex',
    gap: 8,
    marginBottom: 20,
  },
  input: {
    flex: 1,
    padding: '10px 14px',
    fontSize: 14,
    backgroundColor: '#313244',
    border: '1px solid #45475a',
    borderRadius: 8,
    color: '#cdd6f4',
    outline: 'none',
  },
  button: {
    padding: '10px 20px',
    fontSize: 14,
    fontWeight: 600,
    backgroundColor: '#89b4fa',
    color: '#1e1e2e',
    border: 'none',
    borderRadius: 8,
    cursor: 'pointer',
    whiteSpace: 'nowrap' as const,
  },
  buttonDisabled: {
    opacity: 0.5,
    cursor: 'not-allowed',
  },
  statsPanel: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
    gap: 12,
    marginBottom: 20,
  },
  statCard: {
    backgroundColor: '#313244',
    borderRadius: 8,
    padding: 14,
    textAlign: 'center' as const,
  },
  statValue: {
    fontSize: 22,
    fontWeight: 700,
    color: '#89b4fa',
    lineHeight: 1.2,
  },
  statLabel: {
    fontSize: 12,
    color: '#a6adc8',
    marginTop: 4,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.04em',
  },
  resultsList: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: 12,
  },
  resultCard: {
    backgroundColor: '#313244',
    borderRadius: 8,
    padding: 16,
    borderLeft: '3px solid #89b4fa',
  },
  resultContent: {
    fontSize: 14,
    lineHeight: 1.6,
    color: '#cdd6f4',
    marginBottom: 10,
    wordBreak: 'break-word' as const,
  },
  scoreContainer: {
    marginBottom: 8,
  },
  scoreHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 4,
  },
  scoreLabel: {
    fontSize: 12,
    color: '#a6adc8',
  },
  scoreValue: {
    fontSize: 12,
    fontWeight: 600,
    color: '#89b4fa',
  },
  scoreBar: {
    height: 6,
    borderRadius: 3,
    backgroundColor: '#45475a',
    overflow: 'hidden' as const,
  },
  scoreFill: {
    height: '100%',
    borderRadius: 3,
    backgroundColor: '#89b4fa',
    transition: 'width 0.3s ease',
  },
  metadataRow: {
    display: 'flex',
    flexWrap: 'wrap' as const,
    gap: 6,
    marginTop: 8,
  },
  metaTag: {
    display: 'inline-block',
    padding: '2px 8px',
    borderRadius: 4,
    fontSize: 11,
    backgroundColor: '#45475a',
    color: '#a6adc8',
  },
  emptyState: {
    textAlign: 'center' as const,
    padding: 40,
    color: '#a6adc8',
  },
  error: {
    color: '#f38588',
    padding: 12,
    backgroundColor: '#f3858811',
    borderRadius: 8,
    fontSize: 13,
    marginBottom: 16,
  },
  resultCount: {
    fontSize: 13,
    color: '#a6adc8',
    marginBottom: 12,
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatBytes(bytes: number): string {
  if (bytes >= 1_073_741_824) return (bytes / 1_073_741_824).toFixed(1) + ' GB';
  if (bytes >= 1_048_576) return (bytes / 1_048_576).toFixed(1) + ' MB';
  if (bytes >= 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return bytes + ' B';
}

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max) + '...';
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MemoryBrowser({ apiUrl }: { apiUrl: string }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<MemoryChunk[]>([]);
  const [resultTotal, setResultTotal] = useState(0);
  const [hasSearched, setHasSearched] = useState(false);
  const [searching, setSearching] = useState(false);
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Fetch stats on mount
  const loadStats = useCallback(async () => {
    try {
      const result = await invoke<MemoryStats>('fetch_memory_stats', { apiUrl });
      setStats(result);
    } catch (err) {
      // Stats are non-critical; silently ignore
    }
  }, [apiUrl]);

  useEffect(() => {
    loadStats();
  }, [loadStats]);

  const handleSearch = useCallback(async () => {
    if (!query.trim()) return;

    setSearching(true);
    setError(null);
    try {
      const response = await invoke<SearchResponse>('search_memory', {
        apiUrl,
        query: query.trim(),
        topK: 10,
      });
      setResults(response.results ?? []);
      setResultTotal(response.total ?? (response.results ?? []).length);
      setHasSearched(true);
      // Refresh stats after search
      loadStats();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setResults([]);
      setHasSearched(true);
    } finally {
      setSearching(false);
    }
  }, [apiUrl, query, loadStats]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter') {
        handleSearch();
      }
    },
    [handleSearch],
  );

  return (
    <div style={styles.container}>
      <div style={styles.header}>Memory Browser</div>

      {/* Stats panel */}
      {stats && (
        <div style={styles.statsPanel}>
          <div style={styles.statCard}>
            <div style={styles.statValue}>{stats.backend}</div>
            <div style={styles.statLabel}>Backend</div>
          </div>
          <div style={styles.statCard}>
            <div style={styles.statValue}>{stats.total_documents.toLocaleString()}</div>
            <div style={styles.statLabel}>Documents</div>
          </div>
          <div style={styles.statCard}>
            <div style={styles.statValue}>{stats.total_chunks.toLocaleString()}</div>
            <div style={styles.statLabel}>Chunks</div>
          </div>
          <div style={styles.statCard}>
            <div style={styles.statValue}>{formatBytes(stats.index_size_bytes)}</div>
            <div style={styles.statLabel}>Index Size</div>
          </div>
        </div>
      )}

      {/* Search bar */}
      <div style={styles.searchBar}>
        <input
          style={styles.input}
          type="text"
          placeholder="Search memory..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
        />
        <button
          style={{
            ...styles.button,
            ...(searching ? styles.buttonDisabled : {}),
          }}
          onClick={handleSearch}
          disabled={searching || !query.trim()}
        >
          {searching ? 'Searching...' : 'Search'}
        </button>
      </div>

      {error && <div style={styles.error}>{error}</div>}

      {/* Results */}
      {hasSearched && results.length === 0 && !error && (
        <div style={styles.emptyState}>No results found for "{query}"</div>
      )}

      {results.length > 0 && (
        <>
          <div style={styles.resultCount}>
            Showing {results.length} of {resultTotal} results
          </div>
          <div style={styles.resultsList}>
            {results.map((chunk, i) => {
              const scorePercent = Math.round(chunk.score * 100);
              return (
                <div key={i} style={styles.resultCard}>
                  {/* Score bar */}
                  <div style={styles.scoreContainer}>
                    <div style={styles.scoreHeader}>
                      <span style={styles.scoreLabel}>Relevance</span>
                      <span style={styles.scoreValue}>{scorePercent}%</span>
                    </div>
                    <div style={styles.scoreBar}>
                      <div
                        style={{
                          ...styles.scoreFill,
                          width: `${Math.min(scorePercent, 100)}%`,
                        }}
                      />
                    </div>
                  </div>

                  {/* Content preview */}
                  <div style={styles.resultContent}>
                    {truncate(chunk.content, 200)}
                  </div>

                  {/* Metadata tags */}
                  {Object.keys(chunk.metadata).length > 0 && (
                    <div style={styles.metadataRow}>
                      {Object.entries(chunk.metadata).map(([key, val]) => (
                        <span key={key} style={styles.metaTag}>
                          {key}: {String(val)}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}

      {!hasSearched && !stats && (
        <div style={styles.emptyState}>Enter a query to search memory</div>
      )}
    </div>
  );
}
