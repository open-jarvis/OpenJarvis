import { useState, useEffect } from 'react';
import { Shield, Search, Clock, BarChart3, Timer } from 'lucide-react';
import { ToolSearch } from '../components/Osint/ToolSearch';
import { WatchdogPanel } from '../components/Osint/WatchdogPanel';
import { HistoryPanel } from '../components/Osint/HistoryPanel';
import { DashboardPanel } from '../components/Osint/DashboardPanel';
import { SchedulePanel } from '../components/Osint/SchedulePanel';
import { fetchAlerts } from '../components/Desktop/lib/api';

const API_URL = (import.meta.env.VITE_API_URL as string) || 'http://127.0.0.1:8000';

export function OsintPage() {
  const [activeTab, setActiveTab] = useState<'dashboard' | 'arsenal' | 'watchdog' | 'history' | 'scheduler'>('dashboard');
  const [alertCount, setAlertCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchAlerts(API_URL, 20)
      .then((res) => {
        if (!cancelled) setAlertCount(res.count);
      })
      .catch(() => {
        if (!cancelled) setAlertCount(0);
      });
    return () => { cancelled = true; };
  }, [activeTab]);

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
            onClick={() => setActiveTab('dashboard')}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs transition-colors cursor-pointer"
            style={{
              background: activeTab === 'dashboard' ? 'var(--color-accent-subtle)' : 'transparent',
              color: activeTab === 'dashboard' ? 'var(--color-accent)' : 'var(--color-text-secondary)',
              border: activeTab === 'dashboard' ? '1px solid var(--color-accent-muted)' : '1px solid transparent',
            }}
          >
            <BarChart3 size={14} />
            Dashboard
          </button>
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
          <button
            onClick={() => setActiveTab('history')}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs transition-colors cursor-pointer relative"
            style={{
              background: activeTab === 'history' ? 'var(--color-accent-subtle)' : 'transparent',
              color: activeTab === 'history' ? 'var(--color-accent)' : 'var(--color-text-secondary)',
              border: activeTab === 'history' ? '1px solid var(--color-accent-muted)' : '1px solid transparent',
            }}
          >
            <Clock size={14} />
            History
            {alertCount > 0 && activeTab !== 'history' && (
              <span
                className="absolute -top-1 -right-1 w-4 h-4 rounded-full flex items-center justify-center text-[9px] font-bold"
                style={{
                  background: 'var(--color-accent)',
                  color: '#fff',
                }}
              >
                {alertCount > 9 ? '9+' : alertCount}
              </span>
            )}
          </button>
          <button
            onClick={() => setActiveTab('scheduler')}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs transition-colors cursor-pointer"
            style={{
              background: activeTab === 'scheduler' ? 'var(--color-accent-subtle)' : 'transparent',
              color: activeTab === 'scheduler' ? 'var(--color-accent)' : 'var(--color-text-secondary)',
              border: activeTab === 'scheduler' ? '1px solid var(--color-accent-muted)' : '1px solid transparent',
            }}
          >
            <Timer size={14} />
            Scheduler
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-auto p-4">
        {activeTab === 'dashboard' && <DashboardPanel />}
        {activeTab === 'arsenal' && <ToolSearch />}
        {activeTab === 'watchdog' && <WatchdogPanel />}
        {activeTab === 'history' && <HistoryPanel />}
        {activeTab === 'scheduler' && <SchedulePanel />}
      </div>
    </div>
  );
}
