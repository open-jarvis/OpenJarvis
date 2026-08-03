import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

describe('MCP settings', () => {
  it('renders an accessible, desktop-safe server form', async () => {
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: {
        clear: () => {},
        getItem: () => null,
        key: () => null,
        length: 0,
        removeItem: () => {},
        setItem: () => {},
      } satisfies Storage,
    });
    const { McpSettings } = await import('./SettingsPage');
    const html = renderToStaticMarkup(<McpSettings />);

    expect(html).toContain('MCP-Server hinzufügen');
    expect(html).toContain('aria-label="MCP Server-ID"');
    expect(html).toContain('aria-label="MCP Transport"');
    expect(html).toContain('aria-label="MCP Endpunkt"');
    expect(html).toContain('aria-label="MCP Token"');
    expect(html).toContain('type="password"');
    expect(html).toContain('disabled=""');
  });
});
