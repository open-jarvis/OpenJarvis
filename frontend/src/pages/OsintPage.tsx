import { useState } from 'react';
import { Shield, Search } from 'lucide-react';
import { ToolSearch } from '../components/Osint/ToolSearch';
import { WatchdogPanel } from '../components/Osint/WatchdogPanel';

export function OsintPage() {
  const [activeTab, setActiveTab] = useState<'arsenal' | 'watchdog'>('arsenal');

  return (
    <div className="flex flex-col h-full w-full overflow-hidden">
      <div className="shrink-0 px-4 py-3" style={{ borderBottom: '1px solid var(--color-border)' }}>
        <div className="flex items-center gap-3">
          <Shield size={18} style={{ color: 'var(--color-accent)' }} />
          <h1 className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
            OSINT Center
          </h1>
        </div>
        <div className="flex gap-1 mt-3">
          <button
            onClick={() => setActiveTab('arsenal')}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs transition-colors cursor-pointer"
            style={{
              background: activeTab === 'arsenal' ? 'var(--color-accent-subtle)' : 'transparent',
              color: activeTab === 'arsenal' ? 'var(--color-accent)' : 'var(--color-text-secondary)',
              border: activeTab === 'arsenal' ? '1px solid var(--color-accent-muted)' : '1px solid transparent',
            }}
          >
            <Search size={14} />
            Tool Arsenal
          </button>
          <button
            onClick={() => setActiveTab('watchdog')}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs transition-colors cursor-pointer"
            style={{
              background: activeTab === 'watchdog' ? 'var(--color-accent-subtle)' : 'transparent',
              color: activeTab === 'watchdog' ? 'var(--color-accent)' : 'var(--color-text-secondary)',
              border: activeTab === 'watchdog' ? '1px solid var(--color-accent-muted)' : '1px solid transparent',
            }}
          >
            <Shield size={14} />
            FBI Watchdog
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-auto p-4">
        {activeTab === 'arsenal' && <ToolSearch />}
        {activeTab === 'watchdog' && <WatchdogPanel />}
      </div>
    </div>
  );
}
