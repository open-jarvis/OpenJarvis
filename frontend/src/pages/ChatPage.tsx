import { ChatArea } from '../components/Chat/ChatArea';
import { SystemPanel } from '../components/Chat/SystemPanel';
import { useAppStore } from '../lib/store';

export function ChatPage() {
  const systemPanelOpen = useAppStore((s) => s.systemPanelOpen);

  return (
    <div className="oj-chat-page flex h-full overflow-hidden">
      <div className="flex-1 min-w-0">
        <ChatArea />
      </div>
      {systemPanelOpen && <SystemPanel />}
    </div>
  );
}
