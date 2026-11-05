import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { McpServerForm, RestartNotice, TestResultView } from './McpServerParts';
import { McpServerDetail, McpServerListItem } from '../../pages/McpPage';
import { MCP_CATALOG, McpCatalogCard } from './McpCatalog';
import {
  emptyMcpForm,
  formFromServer,
  formFromCatalog,
  formToInput,
  isToolActive,
  searchCatalog,
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
  env_names: [],
  env_set: [],
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

describe('secret environment variables', () => {
  const stdio: McpServer = {
    ...httpServer,
    transport: 'stdio',
    url: null,
    auth_type: 'none',
    auth_header: null,
    has_token: false,
    command: 'npx',
    args: ['-y', 'pkg'],
    env_names: ['API_KEY', 'TEAM'],
    env_set: ['API_KEY'],
  };

  it('sends names always and only the values that were typed', () => {
    const form = formFromServer(stdio);
    expect(form.env).toEqual([
      { name: 'API_KEY', value: '' },
      { name: 'TEAM', value: '' },
    ]);
    expect(formToInput(form, { editing: true })).toMatchObject({ env_names: ['API_KEY', 'TEAM'] });
    expect(formToInput(form, { editing: true })).not.toHaveProperty('env');
    const typed = { ...form, env: [{ name: 'TEAM', value: 't1' }] };
    expect(formToInput(typed, { editing: true })).toMatchObject({ env_names: ['TEAM'], env: { TEAM: 't1' } });
  });

  it('never prefills env values and marks saved ones', () => {
    const html = renderToStaticMarkup(
      <McpServerForm
        initial={formFromServer(stdio)}
        editing
        savedToken={false}
        savedEnv={stdio.env_set}
        onCancel={vi.fn()}
        onSave={vi.fn()}
        onTest={vi.fn()}
      />,
    );
    expect(html).toMatch(/aria-label="Value for API_KEY"[^>]*placeholder="Saved — leave blank to keep"/);
    expect(html).toMatch(/aria-label="Value for TEAM"[^>]*placeholder="Value"/);
    expect(html).not.toMatch(/type="password"[^>]*value="[^"]/);
  });
});

describe('MCP catalog', () => {
  it('has unique ids, a source and a valid server for every entry', () => {
    const ids = MCP_CATALOG.map((e) => e.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const e of MCP_CATALOG) {
      expect(e.source).toMatch(/^https:\/\//);
      expect(['official', 'reference', 'community']).toContain(e.kind);
      if (e.server.transport === 'http') expect(e.server.url).toMatch(/^https?:\/\//);
      else expect(e.server.command).toBeTruthy();
    }
    expect(ids).toContain('gmail');
  });

  it('pre-fills the form without any secret', () => {
    const github = MCP_CATALOG.find((e) => e.id === 'github-local')!;
    const form = formFromCatalog(github);
    expect(form).toMatchObject({ transport: 'stdio', command: 'docker', token: '' });
    expect(form.env).toEqual([{ name: 'GITHUB_PERSONAL_ACCESS_TOKEN', value: '' }]);
    const exa = formFromCatalog(MCP_CATALOG.find((e) => e.id === 'exa')!);
    expect(exa).toMatchObject({ auth_type: 'header', auth_header: 'x-api-key' });
  });

  it('searches by text and category', () => {
    expect(searchCatalog(MCP_CATALOG, 'gmail', null).map((e) => e.id)).toEqual(['gmail']);
    expect(searchCatalog(MCP_CATALOG, '', 'search').every((e) => e.category === 'search')).toBe(true);
  });

  it('does not offer to add OAuth-only servers', () => {
    const gmail = MCP_CATALOG.find((e) => e.id === 'gmail')!;
    const html = renderToStaticMarkup(<McpCatalogCard entry={gmail} onPick={vi.fn()} />);
    expect(html).toContain('Needs OAuth');
    expect(html).not.toContain('Add Gmail');
    expect(html).toContain('Official');
  });
});
