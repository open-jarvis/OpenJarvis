import { useEffect, useState, useCallback } from 'react';
import { FolderOpen, RefreshCw } from 'lucide-react';
import { fetchScienceLabProjects, type ScienceProject } from '../../lib/api';

interface ProjectListProps {
  onSelect: (project: ScienceProject) => void;
  refreshKey?: number;
}

export function ProjectList({ onSelect, refreshKey }: ProjectListProps) {
  const [projects, setProjects] = useState<ScienceProject[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    fetchScienceLabProjects()
      .then(setProjects)
      .catch(() => setProjects([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  return (
    <div className="hud-panel p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="hud-label flex items-center gap-2">
          <FolderOpen size={12} style={{ color: 'var(--color-accent)' }} />
          PROJETOS SALVOS
        </div>
        <button
          onClick={load}
          className="p-1 rounded cursor-pointer"
          style={{ color: 'var(--color-text-tertiary)' }}
          title="Refresh"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>
      {projects.length === 0 ? (
        <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
          {loading ? 'Carregando...' : 'Nenhum projeto salvo ainda.'}
        </div>
      ) : (
        <div className="flex flex-col gap-1">
          {projects.map((p) => (
            <button
              key={p.name}
              onClick={() => onSelect(p)}
              className="text-left px-2 py-1.5 rounded-lg text-sm cursor-pointer transition-colors"
              style={{ color: 'var(--color-text-secondary)' }}
              onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-secondary)')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
            >
              <div className="font-medium" style={{ color: 'var(--color-text)' }}>{p.name}</div>
              <div className="text-xs truncate" style={{ color: 'var(--color-text-tertiary)' }}>{p.objective}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
