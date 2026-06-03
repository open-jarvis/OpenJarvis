import { useEffect, useMemo, useState } from 'react';
import { Outlet, useNavigate } from 'react-router';
import { Sidebar } from './Sidebar/Sidebar';
import { useAppStore } from '../lib/store';
import { checkHealth } from '../lib/api';
import { Activity, Cpu, MapPin, Mic2 } from 'lucide-react';

export function Layout() {
  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const serverInfo = useAppStore((s) => s.serverInfo);
  const settings = useAppStore((s) => s.settings);
  const [apiReachable, setApiReachable] = useState<boolean | null>(null);
  const modelLabel = useMemo(
    () => selectedModel || serverInfo?.model || 'local model',
    [selectedModel, serverInfo?.model],
  );

  useEffect(() => {
    const check = () => checkHealth().then(setApiReachable);
    check();
    const interval = setInterval(check, 30000);
    const onFocus = () => check();
    window.addEventListener('focus', onFocus);
    return () => {
      clearInterval(interval);
      window.removeEventListener('focus', onFocus);
    };
  }, []);

  const navigate = useNavigate();

  return (
    <div className="flex flex-col h-full w-full overflow-hidden relative">
      <div className="hud-backdrop" aria-hidden="true" />
      <header className="app-topbar relative z-20">
        <div className="app-shell-title">OpenJarvis Friday</div>
        <div className="status-pill">
          <span
            className="status-dot"
            style={{
              background: apiReachable === false ? 'var(--color-error)' : 'var(--color-success)',
              boxShadow: apiReachable === false
                ? '0 0 0 3px color-mix(in srgb, var(--color-error) 14%, transparent)'
                : undefined,
            }}
          />
          {apiReachable === false ? 'offline' : 'local'}
        </div>
        <div className="status-pill hidden sm:inline-flex">
          <Cpu size={13} />
          {modelLabel}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <div className="status-pill hidden md:inline-flex">
            <Mic2 size={13} />
            {settings.wakeAlwaysOn ? 'wake on' : 'wake off'}
          </div>
          <div className="status-pill hidden md:inline-flex">
            <MapPin size={13} />
            {settings.locationAlwaysOn ? 'location on' : 'location off'}
          </div>
          <div className="status-pill">
            <Activity size={13} />
            {serverInfo?.engine || 'engine'}
          </div>
        </div>
      </header>

      {/* Health check banner */}
      {apiReachable === false && (
        <div
          className="flex items-center gap-3 px-4 py-2 text-sm shrink-0"
          style={{
            background: 'color-mix(in srgb, var(--color-error) 8%, transparent)',
            borderBottom: '1px solid color-mix(in srgb, var(--color-error) 15%, transparent)',
            color: 'var(--color-text)',
          }}
        >
          <span
            className="w-1.5 h-1.5 rounded-full shrink-0"
            style={{ background: 'var(--color-error)' }}
          />
          <span>Cannot reach OpenJarvis backend</span>
          <button
            onClick={() => navigate('/settings')}
            className="text-sm underline cursor-pointer ml-auto shrink-0"
            style={{ color: 'var(--color-accent)' }}
          >
            Change URL
          </button>
        </div>
      )}

      <div className="flex flex-1 min-h-0 relative z-10">
        <Sidebar />
        {sidebarOpen && (
          <div
            className="fixed inset-0 z-20 bg-black/40 md:hidden"
            onClick={() => useAppStore.getState().setSidebarOpen(false)}
          />
        )}
        <main className="flex-1 flex flex-col min-w-0 h-full relative overflow-hidden" style={{ background: 'transparent' }}>
          <div className="flex-1 flex flex-col min-w-0 min-h-0 relative z-[2]">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
