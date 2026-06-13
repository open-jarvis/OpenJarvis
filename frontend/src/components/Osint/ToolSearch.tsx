import { useState, useEffect, useCallback } from 'react';
import { Search, ExternalLink, Tag, Package, Play, Copy, Globe, CheckCircle } from 'lucide-react';
import { searchOsintTools, fetchOsintCategories, type OsintToolResult } from '../Desktop/lib/api';
import { ToolRunner } from './ToolRunner';

const API_URL = (import.meta.env.VITE_API_URL as string) || 'http://127.0.0.1:8000';

export function ToolSearch() {
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('');
  const [categories, setCategories] = useState<string[]>([]);
  const [categoriesLoading, setCategoriesLoading] = useState(true);
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<OsintToolResult[] | null>(null);
  const [total, setTotal] = useState(0);
  const [searchedQuery, setSearchedQuery] = useState('');
  const [error, setError] = useState('');
  const [expandedTool, setExpandedTool] = useState<string | null>(null);
  const [copiedTool, setCopiedTool] = useState<string | null>(null);

  // Load categories on mount
  useEffect(() => {
    fetchOsintCategories(API_URL)
      .then((cats) => {
        setCategories(cats);
      })
      .catch(() => setCategories([]))
      .finally(() => setCategoriesLoading(false));
  }, []);

  const handleSearch = useCallback(async (catOverride?: string) => {
    const activeCategory = catOverride !== undefined ? catOverride : category;
    if (!query.trim() && !activeCategory) return;

    setLoading(true);
    setError('');
    try {
      const data = await searchOsintTools(API_URL, query, 20, activeCategory);
      setResults(data.results);
      setTotal(data.count);
      setSearchedQuery(data.query || activeCategory || 'all');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Search failed');
    } finally {
      setLoading(false);
    }
  }, [query, category]);

  // Auto-search when category changes (always search if a category is picked)
  const handleCategoryChange = (newCat: string) => {
    setCategory(newCat);
    if (newCat || query.trim() || results !== null) {
      handleSearch(newCat);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSearch();
  };

  return (
    <div className="flex flex-col gap-4 max-w-4xl mx-auto">
      <div className="flex flex-col gap-3">
        <div className="flex gap-2">
          <div className="flex-1 relative">
            <Search
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2"
              style={{ color: 'var(--color-text-tertiary)' }}
            />
            <input
              type="text"
              placeholder="Search OSINT tools..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={handleKeyDown}
              className="w-full pl-9 pr-4 py-2 rounded-lg text-sm outline-none"
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text)',
              }}
            />
          </div>
          <button
            onClick={() => handleSearch()}
            disabled={loading || (!query.trim() && !category)}
            className="px-4 py-2 rounded-lg text-sm font-medium transition-colors cursor-pointer disabled:opacity-50"
            style={{
              background: 'var(--color-accent)',
              color: 'var(--color-on-accent)',
            }}
          >
            {loading ? 'Searching...' : 'Search'}
          </button>
        </div>

        <div className="flex flex-wrap gap-1.5">
          <button
            onClick={() => handleCategoryChange('')}
            className="px-2 py-1 rounded-md text-[10px] transition-colors cursor-pointer"
            style={{
              background: !category ? 'var(--color-accent-subtle)' : 'var(--color-bg-secondary)',
              color: !category ? 'var(--color-accent)' : 'var(--color-text-secondary)',
              border: '1px solid var(--color-border)',
            }}
          >
            All
          </button>
          {categoriesLoading && (
            <span className="text-[10px] px-2 py-1" style={{ color: 'var(--color-text-tertiary)' }}>
              Loading categories...
            </span>
          )}
          {categories.map((cat) => {
            const isActive = category === cat;
            return (
              <button
                key={cat}
                onClick={() => handleCategoryChange(cat)}
                className="px-2 py-1 rounded-md text-[10px] transition-colors cursor-pointer"
                style={{
                  background: isActive ? 'var(--color-accent-subtle)' : 'var(--color-bg-secondary)',
                  color: isActive ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                  border: '1px solid var(--color-border)',
                }}
                title={cat}
              >
                {cat.length > 22 ? cat.slice(0, 20) + '…' : cat}
              </button>
            );
          })}
        </div>
      </div>

      {error && (
        <div
          className="px-4 py-3 rounded-lg text-sm"
          style={{
            background: 'color-mix(in srgb, var(--color-error) 8%, transparent)',
            border: '1px solid color-mix(in srgb, var(--color-error) 15%, transparent)',
            color: 'var(--color-error)',
          }}
        >
          {error}
        </div>
      )}

      {results && (
        <div className="flex flex-col gap-2">
          <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
            Found {total} results for &quot;{searchedQuery}&quot;
            {category && (
              <span> in <span style={{ color: 'var(--color-accent)' }}>{category}</span></span>
            )}
          </div>
          {results.length === 0 && (
            <div
              className="text-sm py-8 text-center"
              style={{ color: 'var(--color-text-tertiary)' }}
            >
              No tools found. Try a different query or category.
            </div>
          )}
          {results.map((tool, idx) => (
            <div
              key={idx}
              className="rounded-lg p-4 transition-colors"
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
              }}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2">
                  <Package size={14} style={{ color: 'var(--color-accent)' }} />
                  <span className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                    {tool.name}
                  </span>
                  <span
                    className="text-[10px] px-1.5 py-0.5 rounded-full"
                    style={{
                      background: 'var(--color-bg-tertiary)',
                      color: 'var(--color-text-tertiary)',
                    }}
                  >
                    {tool.category}
                  </span>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  {tool.url && (
                    <a
                      href={tool.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="p-1.5 rounded-md transition-colors"
                      style={{ color: 'var(--color-text-tertiary)' }}
                      title="Open website"
                    >
                      <Globe size={14} />
                    </a>
                  )}
                  {tool.install_command && tool.install_command !== 'N/A' && (
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(tool.install_command!);
                        setCopiedTool(tool.name);
                        setTimeout(() => setCopiedTool(null), 1500);
                      }}
                      className="p-1.5 rounded-md transition-colors cursor-pointer"
                      style={{ color: copiedTool === tool.name ? 'var(--color-success)' : 'var(--color-text-tertiary)' }}
                      title="Copy install command"
                    >
                      {copiedTool === tool.name ? <CheckCircle size={14} /> : <Copy size={14} />}
                    </button>
                  )}
                  <button
                    onClick={() =>
                      setExpandedTool(expandedTool === tool.name ? null : tool.name)
                    }
                    className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium transition-colors cursor-pointer"
                    style={{
                      background: expandedTool === tool.name ? 'var(--color-accent-subtle)' : 'var(--color-bg-tertiary)',
                      color: expandedTool === tool.name ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                    }}
                    title="Run tool"
                  >
                    <Play size={12} />
                    Run
                  </button>
                </div>
              </div>
              <p className="text-xs mt-2 leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
                {tool.description}
              </p>
              {tool.tags.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2">
                  {tool.tags.map((tag, tidx) => (
                    <span
                      key={tidx}
                      className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded"
                      style={{
                        background: 'var(--color-bg-tertiary)',
                        color: 'var(--color-text-tertiary)',
                      }}
                    >
                      <Tag size={8} />
                      {tag}
                    </span>
                  ))}
                </div>
              )}
              {tool.install_command && tool.install_command !== 'N/A' && (
                <div
                  className="mt-2 text-[10px] font-mono px-2 py-1 rounded"
                  style={{
                    background: 'var(--color-bg-tertiary)',
                    color: 'var(--color-text-tertiary)',
                  }}
                >
                  {tool.install_command}
                </div>
              )}
              {expandedTool === tool.name && (
                <ToolRunner toolName={tool.name} target={query.trim() || 'example.com'} />
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
