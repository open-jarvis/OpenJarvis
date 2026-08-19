import { useState, useCallback } from 'react';
import { FlaskConical } from 'lucide-react';
import { ObjectiveInput } from '../components/ScienceLab/ObjectiveInput';
import { ReasoningStages } from '../components/ScienceLab/ReasoningStages';
import { HypothesisCards } from '../components/ScienceLab/HypothesisCards';
import { ComparisonTable, SimulationList } from '../components/ScienceLab/ComparisonTable';
import { ConfidenceBar } from '../components/ScienceLab/ConfidenceBar';
import { ProjectList } from '../components/ScienceLab/ProjectList';
import {
  analyzeScienceLabObjective,
  type ScienceLabResult,
  type ScienceProject,
} from '../lib/api';

export function ScienceLabPage() {
  const now = new Date();
  const stamp = now.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';

  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ScienceLabResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [projectsRefreshKey, setProjectsRefreshKey] = useState(0);

  const handleSubmit = useCallback((description: string, projectName: string) => {
    setLoading(true);
    setError(null);
    setResult(null);
    analyzeScienceLabObjective(description, projectName || undefined)
      .then((res) => {
        setResult(res);
        if (projectName) setProjectsRefreshKey((k) => k + 1);
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, []);

  const handleSelectProject = useCallback((project: ScienceProject) => {
    setResult({
      content: project.notes,
      metadata: {
        refused: false,
        reasoning_summary: [
          ['OBJETIVO', project.objective],
          ['RESULTADO', project.notes || '(sem observações)'],
        ],
        confidence: project.confidence,
        hypotheses: project.hypotheses,
        simulations: project.simulations,
        comparison: project.comparison,
      },
    });
  }, []);

  const metadata = result?.metadata;

  return (
    <div className="flex-1 overflow-y-auto px-6 py-10">
      <div className="max-w-5xl mx-auto">
        <header className="mb-6">
          <div className="flex items-center justify-between">
            <h1 className="text-lg font-semibold flex items-center gap-2" style={{ color: 'var(--color-text)' }}>
              <FlaskConical size={18} style={{ color: 'var(--color-accent)' }} />
              Science Lab
            </h1>
            <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
              {stamp}
            </div>
          </div>
          <p className="text-sm mt-2 max-w-2xl" style={{ color: 'var(--color-text-secondary)' }}>
            Análise científica de materiais e substâncias — descreva o que você quer criar
            e o J.A.R.V.I.S. identificará propriedades, gerará hipóteses e simulará resultados teóricos.
          </p>
        </header>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 flex flex-col gap-4">
            <ObjectiveInput onSubmit={handleSubmit} loading={loading} />

            {error && (
              <div
                className="text-sm px-4 py-3 rounded-lg"
                style={{
                  background: 'color-mix(in srgb, var(--color-error) 10%, transparent)',
                  border: '1px solid color-mix(in srgb, var(--color-error) 20%, transparent)',
                  color: 'var(--color-error)',
                }}
              >
                {error}
              </div>
            )}

            <ReasoningStages loading={loading} stages={metadata?.reasoning_summary ?? null} />

            {metadata?.refused && (
              <div
                className="text-sm px-4 py-3 rounded-lg whitespace-pre-wrap"
                style={{
                  background: 'color-mix(in srgb, var(--color-warning) 10%, transparent)',
                  border: '1px solid color-mix(in srgb, var(--color-warning) 20%, transparent)',
                  color: 'var(--color-text)',
                }}
              >
                {result?.content}
              </div>
            )}

            {metadata && !metadata.refused && (
              <>
                {metadata.hypotheses && <HypothesisCards hypotheses={metadata.hypotheses} />}
                {metadata.simulations && <SimulationList simulations={metadata.simulations} />}
                {metadata.comparison && metadata.comparison.length > 0 && (
                  <ComparisonTable rows={metadata.comparison} />
                )}
              </>
            )}
          </div>

          <div className="flex flex-col gap-4">
            {metadata?.confidence && <ConfidenceBar confidence={metadata.confidence} />}
            <ProjectList onSelect={handleSelectProject} refreshKey={projectsRefreshKey} />
          </div>
        </div>
      </div>
    </div>
  );
}
