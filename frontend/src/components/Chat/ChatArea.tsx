import { useRef, useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router';
import { MessageBubble } from './MessageBubble';
import { InputArea } from './InputArea';
import { StreamingDots } from './StreamingDots';
import { useAppStore } from '../../lib/store';
import { ArrowRight, Database, MessageSquare, Navigation, X } from 'lucide-react';
import { listConnectors } from '../../lib/connectors-api';

function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

export function ChatArea() {
  const messages = useAppStore((s) => s.messages);
  const streamState = useAppStore((s) => s.streamState);
  const navigate = useNavigate();
  const listRef = useRef<HTMLDivElement>(null);
  const shouldAutoScroll = useRef(true);

  // Check if any data sources are connected
  const [hasConnectedSources, setHasConnectedSources] = useState<boolean | null>(null);
  const [bannerDismissed, setBannerDismissed] = useState(false);

  useEffect(() => {
    listConnectors()
      .then((list) => setHasConnectedSources(list.some((c) => c.connected)))
      .catch(() => setHasConnectedSources(null));
  }, []);

  useEffect(() => {
    if (shouldAutoScroll.current && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, streamState.content]);

  const handleScroll = () => {
    if (!listRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = listRef.current;
    shouldAutoScroll.current = scrollHeight - scrollTop - clientHeight < 100;
  };

  const isEmpty = messages.length === 0 && !streamState.isStreaming;

  return (
    <div className="flex flex-col h-full">
      {/* Data sources banner */}
      {hasConnectedSources === false && !bannerDismissed && (
        <div
          className="mx-4 mt-3 mb-2 flex items-center gap-3 px-4 py-3 rounded-lg text-sm shrink-0 quiet-panel"
          style={{
            background: 'color-mix(in srgb, var(--color-accent) 8%, var(--color-surface))',
          }}
        >
          <Database size={16} style={{ color: 'var(--color-accent)', flexShrink: 0 }} />
          <span style={{ color: 'var(--color-text-secondary)', flex: 1 }}>
            Data sources are not connected.
          </span>
          <button
            onClick={() => navigate('/data-sources')}
            className="px-3 py-1 rounded text-xs font-medium cursor-pointer"
            style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)', border: 'none' }}
          >
            Connect
          </button>
          <button
            onClick={() => setBannerDismissed(true)}
            className="p-1 rounded cursor-pointer"
            style={{ color: 'var(--color-text-tertiary)', background: 'transparent', border: 'none' }}
          >
            <X size={14} />
          </button>
        </div>
      )}
      <div
        ref={listRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto"
      >
        {isEmpty ? (
          <div className="h-full px-5 py-5 md:px-8 md:py-8">
            <div className="mx-auto flex h-full max-w-[var(--chat-max-width)] flex-col justify-end">
              <div className="mb-6">
                <div className="text-xs mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
                  {getGreeting()}
                </div>
                <h1 className="text-2xl md:text-3xl font-semibold leading-tight" style={{ color: 'var(--color-text)' }}>
                  Friday
                </h1>
              </div>
              <div className="grid gap-2 sm:grid-cols-3">
                <button
                  onClick={() => navigate('/settings')}
                  className="quiet-panel flex items-center justify-between gap-3 rounded-lg px-4 py-3 text-left text-sm cursor-pointer transition-colors"
                  style={{ color: 'var(--color-text)' }}
                >
                  <span>음성 설정</span>
                  <ArrowRight size={15} style={{ color: 'var(--color-text-tertiary)' }} />
                </button>
                <button
                  onClick={() => navigate('/settings')}
                  className="quiet-panel flex items-center justify-between gap-3 rounded-lg px-4 py-3 text-left text-sm cursor-pointer transition-colors"
                  style={{ color: 'var(--color-text)' }}
                >
                  <span>TMAP 설정</span>
                  <Navigation size={15} style={{ color: 'var(--color-text-tertiary)' }} />
                </button>
              <button
                onClick={() => navigate('/data-sources')}
                className="quiet-panel flex items-center justify-between gap-3 rounded-lg px-4 py-3 text-left text-sm cursor-pointer transition-colors"
                style={{ color: 'var(--color-text)' }}
              >
                  <span>데이터 연결</span>
                  <Database size={15} style={{ color: 'var(--color-text-tertiary)' }} />
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="max-w-[var(--chat-max-width)] mx-auto px-4 py-7 md:px-6">
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))}
            {streamState.isStreaming && streamState.content === '' && (
              <div className="flex justify-start mb-4">
                <StreamingDots phase={streamState.phase} />
              </div>
            )}
          </div>
        )}
      </div>
      <InputArea />
    </div>
  );
}
