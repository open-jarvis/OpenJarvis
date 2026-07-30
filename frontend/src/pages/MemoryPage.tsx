import { MemoryVaultPanel } from '../components/MemoryVaultPanel';

export function MemoryPage() {
  return (
    <div className="flex-1 overflow-y-auto px-6 py-10">
      <div className="max-w-5xl mx-auto">
        <header className="mb-6">
          <h1 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>
            Memory
          </h1>
          <p className="text-sm mt-2 max-w-2xl" style={{ color: 'var(--color-text-secondary)' }}>
            Inspect health, evidence, candidates, conflicts, and stable note relationships from the configured Markdown vault.
          </p>
        </header>
        <MemoryVaultPanel />
      </div>
    </div>
  );
}
