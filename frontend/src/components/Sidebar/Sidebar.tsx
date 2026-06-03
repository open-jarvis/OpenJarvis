import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router';
import {
  MessageSquare,
  Plus,
  BarChart3,
  Settings,
  Search,
  PanelLeftClose,
  PanelLeft,
  Cpu,
  Rocket,
  Bot,
  Sun,
  Moon,
  Monitor,
  Loader2,
  ScrollText,
  Database,
  Command,
} from 'lucide-react';
import { ConversationList } from './ConversationList';
import { useAppStore } from '../../lib/store';

export function Sidebar() {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchQuery, setSearchQuery] = useState('');

  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);
  const createConversation = useAppStore((s) => s.createConversation);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const serverInfo = useAppStore((s) => s.serverInfo);
  const setCommandPaletteOpen = useAppStore((s) => s.setCommandPaletteOpen);
  const modelLoading = useAppStore((s) => s.modelLoading);

  const settings = useAppStore((s) => s.settings);
  const updateSettings = useAppStore((s) => s.updateSettings);

  const ThemeIcon = settings.theme === 'light' ? Sun : settings.theme === 'dark' ? Moon : Monitor;
  const nextTheme = settings.theme === 'light' ? 'dark' : settings.theme === 'dark' ? 'system' : 'light';

  const messages = useAppStore((s) => s.messages);
  const handleNewChat = () => {
    // Don't create a new chat if the current one is empty
    if (messages.length === 0) {
      navigate('/');
      return;
    }
    createConversation(selectedModel);
    navigate('/');
  };

  const navItems = [
    { path: '/', icon: MessageSquare, label: 'Chat' },
    { path: '/dashboard', icon: BarChart3, label: 'Dashboard' },
    { path: '/data-sources', icon: Database, label: 'Data Sources' },
    { path: '/agents', icon: Bot, label: 'Agents' },
    { path: '/logs', icon: ScrollText, label: 'Logs' },
    { path: '/settings', icon: Settings, label: 'Settings' },
    { path: '/get-started', icon: Rocket, label: 'Get Started' },
  ];

  return (
    <>
      {/* Collapse button when sidebar is closed */}
      {!sidebarOpen && (
        <button
          onClick={toggleSidebar}
          className="fixed top-3 left-3 z-30 p-2 rounded-lg transition-colors cursor-pointer"
          style={{ color: 'var(--color-text-secondary)', background: 'var(--color-bg-secondary)' }}
          onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
          onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--color-bg-secondary)')}
        >
          <PanelLeft size={18} />
        </button>
      )}

      <aside
        className={`
          flex flex-col h-full shrink-0 transition-all duration-200 ease-in-out overflow-hidden
          fixed md:relative z-30
          ${sidebarOpen ? 'w-[292px]' : 'w-0'}
        `}
        style={{
          background: 'var(--color-sidebar)',
          backdropFilter: 'blur(24px)',
          WebkitBackdropFilter: 'blur(24px)',
          borderRight: sidebarOpen ? '1px solid var(--color-border)' : 'none',
        }}
      >
        <div className="flex flex-col h-full w-[292px]">
          {/* Header */}
          <div className="flex items-center justify-between px-3 pt-3 pb-2">
            <button
              onClick={toggleSidebar}
              className="p-2 rounded-lg transition-colors cursor-pointer"
              style={{ color: 'var(--color-text-secondary)' }}
              onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
            >
              <PanelLeftClose size={18} />
            </button>
            <div className="flex-1 px-2 min-w-0">
              <div className="text-xs font-semibold truncate" style={{ color: 'var(--color-text)' }}>
                Friday Console
              </div>
              <div className="text-[11px] truncate" style={{ color: 'var(--color-text-tertiary)' }}>
                local-first assistant
              </div>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => updateSettings({ theme: nextTheme })}
                className="p-2 rounded-lg transition-colors cursor-pointer"
                style={{ color: 'var(--color-text-secondary)' }}
                onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
                onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                title={`Theme: ${settings.theme} (click for ${nextTheme})`}
              >
                <ThemeIcon size={16} />
              </button>
              <button
                onClick={handleNewChat}
                className="p-2 rounded-lg transition-colors cursor-pointer"
                style={{ color: 'var(--color-text-secondary)' }}
                onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
                onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                title="New chat"
              >
                <Plus size={18} />
              </button>
            </div>
          </div>

          {/* Model badge */}
          <button
            onClick={() => setCommandPaletteOpen(true)}
            className="mx-3 mb-3 flex items-center gap-2 px-3 py-2.5 rounded-lg text-xs transition-colors cursor-pointer"
            style={{
              background: 'color-mix(in srgb, var(--color-surface) 70%, transparent)',
              color: 'var(--color-text-secondary)',
              border: '1px solid var(--color-border)',
              boxShadow: 'var(--shadow-sm)',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
            onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--color-bg-secondary)')}
          >
            {modelLoading ? (
              <Loader2 size={14} className="animate-spin" style={{ color: 'var(--color-accent)' }} />
            ) : (
              <Cpu size={14} />
            )}
            <div className="flex-1 min-w-0">
              <span className="truncate block text-left" style={{ color: 'var(--color-text)' }}>
                {selectedModel || serverInfo?.model || 'Select model'}
              </span>
              {modelLoading && (
                <span className="text-[10px] block text-left" style={{ color: 'var(--color-accent)' }}>
                  Loading model...
                </span>
              )}
            </div>
            {!modelLoading && (
              <Command size={13} style={{ color: 'var(--color-text-tertiary)' }} />
            )}
          </button>

          {/* Search */}
          <div className="px-3 mb-2">
            <div
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm"
              style={{ background: 'color-mix(in srgb, var(--color-surface) 58%, transparent)', border: '1px solid var(--color-border)' }}
            >
              <Search size={14} style={{ color: 'var(--color-text-tertiary)' }} />
              <input
                type="text"
                placeholder="Search chats..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="flex-1 bg-transparent outline-none text-sm"
                style={{ color: 'var(--color-text)' }}
              />
            </div>
          </div>

          {/* Conversation list */}
          <div className="flex-1 overflow-y-auto px-2">
            <ConversationList searchQuery={searchQuery} />
          </div>

          {/* Bottom nav */}
          <nav className="px-2 pb-3 pt-2 flex flex-col gap-1" style={{ borderTop: '1px solid var(--color-border)' }}>
            {navItems.map((item) => {
              const isActive = location.pathname === item.path;
              return (
                <button
                  key={item.path}
                  onClick={() => navigate(item.path)}
                  className="relative flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors w-full text-left cursor-pointer"
                  style={{
                    background: isActive ? 'color-mix(in srgb, var(--color-accent) 13%, transparent)' : 'transparent',
                    color: isActive ? 'var(--color-text)' : 'var(--color-text-secondary)',
                    fontWeight: isActive ? 650 : 450,
                  }}
                  onMouseEnter={(e) => {
                    if (!isActive) e.currentTarget.style.background = 'var(--color-bg-secondary)';
                  }}
                  onMouseLeave={(e) => {
                    if (!isActive) e.currentTarget.style.background = 'transparent';
                  }}
                >
                  {isActive && (
                    <span
                      aria-hidden="true"
                      className="absolute left-0 top-1.5 bottom-1.5 w-[2px] rounded-full"
                      style={{
                        background: 'var(--color-accent)',
                        boxShadow: '0 0 8px var(--color-accent-glow)',
                      }}
                    />
                  )}
                  <item.icon size={16} style={isActive ? { color: 'var(--color-accent)' } : undefined} />
                  {item.label}
                </button>
              );
            })}
          </nav>
        </div>
      </aside>
    </>
  );
}
