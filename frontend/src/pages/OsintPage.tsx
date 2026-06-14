import { useState, useEffect, useCallback } from 'react';
import { Shield, Search, Clock, BarChart3, Timer, Bell } from 'lucide-react';
import { ToolSearch } from '../components/Osint/ToolSearch';
import { WatchdogPanel } from '../components/Osint/WatchdogPanel';
import { HistoryPanel } from '../components/Osint/HistoryPanel';
import { DashboardPanel } from '../components/Osint/DashboardPanel';
import { SchedulePanel } from '../components/Osint/SchedulePanel';
import { AlertsPanel } from '../components/Osint/AlertsPanel';
import { fetchAlerts } from '../components/Desktop/lib/api';
import { useOsintEvents } from '../lib/useOsintEvents';

const API_URL = (import.meta.env.VITE_API_URL as string) || 'http://127.0.0.1:8000';

export function OsintPage() {
  const [activeTab, setActiveTab] = useState<'dashboard' | 'arsenal' | 'watchdog' | 'history' | 'scheduler' | 'alerts'>('dashboard');
  const [alertCount, setAlertCount] = useState(0);

  const refreshAlerts = useCallback(() => {
    fetchAlerts(API_URL, 20)
      .then((res) => {
        setAlertCount(res.count);
      })
      .catch(() => {
        setAlertCount(0);
      });
  }, []);

  useEffect(() => {
    refreshAlerts();
  }, [activeTab, refreshAlerts]);

  useOsintEvents(
    useCallback(
      (event) => {
        if (event.type === 'scheduler_task_end') {
          refreshAlerts();
        }
      },
      [refreshAlerts],
    ),
    ['scheduler_task_end'],
  );

  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (typeof detail === 'string') {
        setActiveTab(detail as typeof activeTab);
      } else if (detail?.tab) {
        setActiveTab(detail.tab as typeof activeTab);
      }
    };
    window.addEventListener('osint-tab-change', handler);
    return () => window.removeEventListener('osint-tab-change', handler);
  }, []);

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
          <button
            onClick={() => setActiveTab('alerts')}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs transition-colors cursor-pointer relative"
            style={{
              background: activeTab === 'alerts' ? 'var(--color-accent-subtle)' : 'transparent',
              color: activeTab === 'alerts' ? 'var(--color-accent)' : 'var(--color-text-secondary)',
              border: activeTab === 'alerts' ? '1px solid var(--color-accent-muted)' : '1px solid transparent',
            }}
          >
            <Bell size={14} />
            Alerts
            {alertCount > 0 && activeTab !== 'alerts' && (
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
        </div>
      </div>

      <div className="flex-1 overflow-auto p-4">
        {activeTab === 'dashboard' && <DashboardPanel />}
        {activeTab === 'arsenal' && <ToolSearch />}
        {activeTab === 'watchdog' && <WatchdogPanel />}
        {activeTab === 'history' && <HistoryPanel />}
        {activeTab === 'scheduler' && <SchedulePanel />}
        {activeTab === 'alerts' && <AlertsPanel />}
      </div>
    </div>
  );
}
