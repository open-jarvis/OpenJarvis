import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { McpServerForm, RestartNotice, TestResultView } from './McpServerParts';
import { McpServerDetail, McpServerListItem } from '../../pages/McpPage';
import {
  emptyMcpForm,
  formFromServer,
  formToInput,
  isToolActive,
  toggleInput,
  toolToggleInput,
  type McpServer,
} from '../../lib/mcp-api';

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

  it('turns single tools off and on', () => {
    const plain = { ...httpServer, include_tools: [], exclude_tools: [] };
    const off = toolToggleInput(plain, 'drop', false);
    expect(off.exclude_tools).toEqual(['drop']);
    expect(off).not.toHaveProperty('token');
    expect(toolToggleInput({ ...plain, exclude_tools: ['drop'] }, 'drop', true).exclude_tools).toEqual([]);
    // With an include list, turning a tool on adds it there.
    const on = toolToggleInput(httpServer, 'other', true);
    expect(on.include_tools).toEqual(['search', 'other']);
    expect(isToolActive(on, 'other')).toBe(true);
    // Turning off the only included tool must not re-enable the rest.
    const lastOff = toolToggleInput(httpServer, 'search', false);
    expect(isToolActive(lastOff, 'search')).toBe(false);
    expect(isToolActive(lastOff, 'other')).toBe(false);
  });

  it('toggles enabled without touching the token', () => {
    const input = toggleInput(httpServer, false);
    expect(input.enabled).toBe(false);
    expect(input).not.toHaveProperty('token');
  });
});

describe('MCP server rendering', () => {
  it('shows config.toml servers as read-only', () => {
    const server = { ...httpServer, source: 'config' as const, read_only: true };
    const html = renderToStaticMarkup(
      <McpServerDetail
        server={server}
        result={{ ok: true, tools: [{ name: 'search', description: '', active: true }] }}
        busy={false}
        onTest={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onToggle={vi.fn()}
        onToggleTool={vi.fn()}
      />,
    );
    expect(html).toContain('config.toml');
    expect(html).toContain('Test');
    expect(html).not.toContain('Delete');
    expect(html).toMatch(/aria-label="Use tool search"[^>]*disabled/);
  });

  it('shows saved-token state and per-tool switches', () => {
    const html = renderToStaticMarkup(
      <McpServerDetail
        server={httpServer}
        result={{ ok: true, tools: [{ name: 'search', description: 'Find', active: true }, { name: 'drop', description: '', active: false }] }}
        busy={false}
        onTest={vi.fn()}
        onEdit={vi.fn()}
        onDelete={vi.fn()}
        onToggle={vi.fn()}
        onToggleTool={vi.fn()}
      />,
    );
    expect(html).toContain('token saved');
    expect(html).toContain('Tools (2)');
    expect(html).toMatch(/aria-checked="false"[^>]*aria-label="Use tool drop"/);
  });

  it('summarises a server in the list', () => {
    const html = renderToStaticMarkup(
      <McpServerListItem
        server={httpServer}
        result={{ ok: true, tools: [{ name: 'a', description: '', active: true }, { name: 'b', description: '', active: false }] }}
        selected
        onSelect={vi.fn()}
      />,
    );
    expect(html).toContain('1/2 tools on');
    expect(renderToStaticMarkup(<McpServerListItem server={{ ...httpServer, enabled: false }} selected={false} onSelect={vi.fn()} />)).toContain('Disabled');
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
