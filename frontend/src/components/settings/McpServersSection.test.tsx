import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { McpServerForm, McpServerRow, RestartNotice, TestResultView } from './McpServersSection';
import { emptyMcpForm, formFromServer, formToInput, toggleInput, type McpServer } from '../../lib/mcp-api';

const httpServer: McpServer = {
  id: 'abc',
  name: 'Docs',
  transport: 'http',
  url: 'https://example.test/mcp',
  auth_type: 'header',
  auth_header: 'X-Api-Key',
  has_token: true,
  command: null,
  args: [],
  include_tools: ['search'],
  exclude_tools: [],
  enabled: true,
  source: 'gui',
  read_only: false,
};

describe('MCP server form payloads', () => {
  it('keeps the saved token when editing without a new one', () => {
    const input = formToInput(formFromServer(httpServer), { editing: true });
    expect(input).not.toHaveProperty('token');
    expect(input.auth_header).toBe('X-Api-Key');
    expect(input.include_tools).toEqual(['search']);
  });

  it('clears the token only when asked', () => {
    const input = formToInput({ ...formFromServer(httpServer), clearToken: true }, { editing: true });
    expect(input.token).toBe('');
  });

  it('sends one stdio argument per line and drops http fields', () => {
    const input = formToInput(
      { ...emptyMcpForm, name: 'local', transport: 'stdio', command: 'npx', args: '-y\nsome server\n', url: 'x' },
      { editing: false },
    );
    expect(input).toMatchObject({ transport: 'stdio', command: 'npx', args: ['-y', 'some server'], auth_type: 'none' });
    expect(input).not.toHaveProperty('url');
  });

  it('toggles enabled without touching the token', () => {
    const input = toggleInput(httpServer, false);
    expect(input.enabled).toBe(false);
    expect(input).not.toHaveProperty('token');
  });
});

describe('MCP server rendering', () => {
  it('shows config.toml servers as read-only', () => {
    const html = renderToStaticMarkup(
      <McpServerRow server={{ ...httpServer, source: 'config', read_only: true }} onTest={vi.fn()} />,
    );
    expect(html).toContain('config.toml');
    expect(html).toContain('Test');
    expect(html).not.toContain('Delete Docs');
  });

  it('shows saved-token state without a token value', () => {
    const html = renderToStaticMarkup(<McpServerRow server={httpServer} onTest={vi.fn()} />);
    expect(html).toContain('token saved');
    expect(html).toContain('Delete Docs');
  });

  it('never prefills the token field when editing', () => {
    const html = renderToStaticMarkup(
      <McpServerForm
        initial={formFromServer(httpServer)}
        editing
        savedToken
        onCancel={vi.fn()}
        onSave={vi.fn()}
        onTest={vi.fn()}
      />,
    );
    expect(html).toMatch(/<input type="password"[^>]*value=""/);
    expect(html).toContain('Saved — leave blank to keep');
    expect(html).toContain('Remove saved token');
  });

  it('lists tools from a test and marks filtered ones', () => {
    const html = renderToStaticMarkup(
      <TestResultView
        result={{ ok: true, tools: [{ name: 'search', description: 'Find', active: true }, { name: 'drop', description: '', active: false }] }}
      />,
    );
    expect(html).toContain('2 tools');
    expect(html).toContain('line-through');
  });

  it('explains that a restart is needed', () => {
    expect(renderToStaticMarkup(<RestartNotice />)).toContain('Restart OpenJarvis');
  });
});
