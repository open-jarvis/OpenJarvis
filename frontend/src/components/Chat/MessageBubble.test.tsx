import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

vi.mock('./SpeakMessageButton', () => ({ SpeakMessageButton: () => null }));
vi.mock('./XRayFooter', () => ({ XRayFooter: () => null }));

import { MessageBubble } from './MessageBubble';
import type { ChatMessage } from '../../types';

function render(message: Partial<ChatMessage>) {
  return renderToStaticMarkup(
    <MessageBubble message={{ id: 'm1', timestamp: 0, ...message } as ChatMessage} />,
  );
}

describe('message text direction', () => {
  it('lets each assistant block pick its own direction', () => {
    const html = render({
      role: 'assistant',
      content: 'آخر إيميل من **Meta for Business**.\n\n- **المحتوى:** إيصال\n\n```\ncode\n```',
    });

    expect(html).toMatch(/<p dir="auto">آخر إيميل/);
    expect(html).toMatch(/<ul dir="auto">/);
    expect(html).toMatch(/<li dir="auto">/);
    expect(html).not.toMatch(/<pre[^>]*dir=/);
  });

  it('lets the user bubble pick its direction', () => {
    expect(render({ role: 'user', content: 'إيه آخر إيميل عندي؟' })).toContain('dir="auto"');
  });
});
