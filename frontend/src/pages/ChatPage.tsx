import { ChatArea } from '../components/Chat/ChatArea';

export function ChatPage() {
  return (
    <div className="flex h-full overflow-hidden">
      <div className="flex-1 min-w-0">
        <ChatArea />
      </div>
    </div>
  );
}
