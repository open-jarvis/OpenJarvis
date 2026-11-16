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

  it('keeps code left-to-right inside a right-to-left blockquote', () => {
    const html = render({
      role: 'assistant',
      content: '> فقرة عربية\n>\n> ```js\n> const value = 1;\n> ```',
    });

    expect(html).toMatch(/<blockquote dir="auto">/);
    expect(html).toMatch(/<blockquote dir="auto">[\s\S]*<div[^>]*dir="ltr"/);
    expect(html.replace(/<[^>]*>/g, '')).toContain('const value = 1;');
  });

  it('lets mixed-language table cells choose their direction independently', () => {
    const html = render({
      role: 'assistant',
      content: '| العنوان | Name |\n| --- | --- |\n| محتوى | English |',
    });

    expect(html).toContain('<th dir="auto">العنوان</th>');
    expect(html).toContain('<th dir="auto">Name</th>');
    expect(html).toContain('<td dir="auto">محتوى</td>');
    expect(html).toContain('<td dir="auto">English</td>');
  });
});
