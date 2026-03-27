import { useState } from 'react';
import { SourcePicker } from './SourcePicker';
import { SourceConnectFlow } from './SourceConnectFlow';
import { IngestDashboard } from './IngestDashboard';
import { ReadyScreen } from './ReadyScreen';
import type { WizardStep } from '../../types/connectors';

// ---------------------------------------------------------------------------
// SetupWizard
// ---------------------------------------------------------------------------

export function SetupWizard({ onComplete }: { onComplete: (firstQuery?: string) => void }) {
  const [step, setStep] = useState<WizardStep>('pick');
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [connectedIds, setConnectedIds] = useState<string[]>([]);

  const handlePick = (ids: string[]) => {
    setSelectedIds(ids);
    setStep('connect');
  };

  const handleConnectComplete = () => {
    // connectedIds: those actually in selectedIds that were not skipped.
    // We don't track skip state here — IngestDashboard receives all selected
    // (skipped ones will just fail gracefully on sync status fetch).
    setConnectedIds(selectedIds);
    setStep('ingest');
  };

  const handleIngestReady = () => {
    setStep('ready');
  };

  const handleStart = (query?: string) => {
    onComplete(query);
  };

  return (
    <div
      className="fixed inset-0 flex items-center justify-center"
      style={{ background: 'var(--color-bg)' }}
    >
      <div
        className="w-full max-w-2xl mx-6 p-8 rounded-2xl"
        style={{
          background: 'var(--color-bg-secondary)',
          border: '1px solid var(--color-border)',
          maxHeight: '90vh',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        {/* Step indicator */}
        <div className="flex items-center gap-2 mb-8">
          {(['pick', 'connect', 'ingest', 'ready'] as WizardStep[]).map((s, i) => (
            <div key={s} className="flex items-center gap-2">
              <div
                className="flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold transition-all"
                style={{
                  background:
                    s === step
                      ? 'var(--color-accent)'
                      : ['pick', 'connect', 'ingest', 'ready'].indexOf(s) <
                          ['pick', 'connect', 'ingest', 'ready'].indexOf(step)
                        ? 'var(--color-accent-subtle)'
                        : 'var(--color-bg-tertiary)',
                  color:
                    s === step
                      ? 'white'
                      : ['pick', 'connect', 'ingest', 'ready'].indexOf(s) <
                          ['pick', 'connect', 'ingest', 'ready'].indexOf(step)
                        ? 'var(--color-accent)'
                        : 'var(--color-text-tertiary)',
                }}
              >
                {i + 1}
              </div>
              {i < 3 && (
                <div
                  className="w-8 h-0.5 rounded-full"
                  style={{
                    background:
                      ['pick', 'connect', 'ingest', 'ready'].indexOf(s) <
                      ['pick', 'connect', 'ingest', 'ready'].indexOf(step)
                        ? 'var(--color-accent)'
                        : 'var(--color-border)',
                  }}
                />
              )}
            </div>
          ))}
        </div>

        {/* Step content */}
        <div className="flex-1 overflow-hidden">
          {step === 'pick' && <SourcePicker onContinue={handlePick} />}
          {step === 'connect' && (
            <SourceConnectFlow
              selectedIds={selectedIds}
              onComplete={handleConnectComplete}
            />
          )}
          {step === 'ingest' && (
            <IngestDashboard
              connectedIds={connectedIds}
              onReady={handleIngestReady}
            />
          )}
          {step === 'ready' && (
            <ReadyScreen
              connectedSources={connectedIds}
              onStart={handleStart}
            />
          )}
        </div>
      </div>
    </div>
  );
}
