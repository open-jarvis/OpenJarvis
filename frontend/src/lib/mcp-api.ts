import { apiFetch } from './api';

// ---------------------------------------------------------------------------
// Global MCP servers API (/v1/mcp/servers)
// ---------------------------------------------------------------------------
//
// Tokens are write-only: the server returns `has_token`, never the token.
// On update, omit `token` to keep the stored one and send "" to clear it.

export type McpTransport = 'http' | 'stdio';
export type McpAuthType = 'none' | 'bearer' | 'header';

export interface McpServer {
  id: string;
  name: string;
  transport: McpTransport;
  url: string | null;
  auth_type: McpAuthType;
  auth_header: string | null;
  has_token: boolean;
  command: string | null;
  args: string[];
  include_tools: string[];
  exclude_tools: string[];
  enabled: boolean;
  source: 'gui' | 'config';
  read_only: boolean;
}

export interface McpServerList {
  enabled: boolean;
  servers: McpServer[];
  config_servers: McpServer[];
  config_error: string | null;
  restart_required: boolean;
}

export interface McpServerInput {
  name: string;
  transport: McpTransport;
  url?: string;
  auth_type: McpAuthType;
  auth_header?: string;
  token?: string;
  command?: string;
  args: string[];
  include_tools: string[];
  exclude_tools: string[];
  enabled: boolean;
}

export interface McpTestResult {
  ok: boolean;
  tools?: { name: string; description: string; active: boolean }[];
  error?: string;
}

async function errorMessage(res: Response): Promise<string> {
  const body = await res.json().catch(() => null);
  const detail = body?.detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: { loc?: string[]; msg?: string }) => {
        const field = (d.loc || []).filter((p) => p !== 'body').join('.');
        return field ? `${field}: ${d.msg}` : d.msg;
      })
      .join('; ');
  }
  return typeof detail === 'string' ? detail : `Request failed: ${res.status}`;
}

async function send<T>(path: string, method: string, body?: unknown): Promise<T> {
  const res = await apiFetch(path, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await errorMessage(res));
  return res.json();
}

export function listMcpServers(): Promise<McpServerList> {
  return send('/v1/mcp/servers', 'GET');
}

export function createMcpServer(input: McpServerInput): Promise<{ server: McpServer; restart_required: boolean }> {
  return send('/v1/mcp/servers', 'POST', input);
}

export function updateMcpServer(
  id: string,
  input: McpServerInput,
): Promise<{ server: McpServer; restart_required: boolean }> {
  return send(`/v1/mcp/servers/${encodeURIComponent(id)}`, 'PUT', input);
}

export function deleteMcpServer(id: string): Promise<{ deleted: boolean; restart_required: boolean }> {
  return send(`/v1/mcp/servers/${encodeURIComponent(id)}`, 'DELETE');
}

export function testMcpServer(id: string): Promise<McpTestResult> {
  return send(`/v1/mcp/servers/${encodeURIComponent(id)}/test`, 'POST');
}

/** Test an unsaved draft. `id` lets the server reuse a saved token. */
export function testMcpDraft(input: McpServerInput & { id?: string }): Promise<McpTestResult> {
  return send('/v1/mcp/servers/test', 'POST', input);
}

// -- form helpers -----------------------------------------------------------

export interface McpForm {
  name: string;
  transport: McpTransport;
  url: string;
  auth_type: McpAuthType;
  auth_header: string;
  token: string;
  clearToken: boolean;
  command: string;
  args: string;
  include_tools: string;
  exclude_tools: string;
  enabled: boolean;
}

export const emptyMcpForm: McpForm = {
  name: '',
  transport: 'http',
  url: '',
  auth_type: 'none',
  auth_header: '',
  token: '',
  clearToken: false,
  command: '',
  args: '',
  include_tools: '',
  exclude_tools: '',
  enabled: true,
};

export function formFromServer(server: McpServer): McpForm {
  return {
    ...emptyMcpForm,
    name: server.name,
    transport: server.transport,
    url: server.url || '',
    auth_type: server.auth_type,
    auth_header: server.auth_header || '',
    command: server.command || '',
    args: server.args.join('\n'),
    include_tools: server.include_tools.join(', '),
    exclude_tools: server.exclude_tools.join(', '),
    enabled: server.enabled,
  };
}

const splitList = (value: string) =>
  value
    .split(/[,\n]/)
    .map((s) => s.trim())
    .filter(Boolean);

/** Build the API payload. One argument per line keeps spaces inside args. */
export function formToInput(form: McpForm, { editing }: { editing: boolean }): McpServerInput {
  const input: McpServerInput = {
    name: form.name.trim(),
    transport: form.transport,
    auth_type: form.transport === 'http' ? form.auth_type : 'none',
    args: [],
    include_tools: splitList(form.include_tools),
    exclude_tools: splitList(form.exclude_tools),
    enabled: form.enabled,
  };
  if (form.transport === 'http') {
    input.url = form.url.trim();
    if (form.auth_type === 'header') input.auth_header = form.auth_header.trim();
    if (form.auth_type !== 'none') {
      if (form.token) input.token = form.token;
      else if (editing && form.clearToken) input.token = '';
    }
  } else {
    input.command = form.command.trim();
    input.args = form.args
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean);
  }
  return input;
}

/** Payload for re-saving a server unchanged except `enabled` (token kept). */
export function toggleInput(server: McpServer, enabled: boolean): McpServerInput {
  return { ...formToInput(formFromServer(server), { editing: true }), enabled };
}

/** Same rule as the backend's `filter_server_tools`. */
export function isToolActive(server: Pick<McpServer, 'include_tools' | 'exclude_tools'>, tool: string): boolean {
  if (server.include_tools.length && !server.include_tools.includes(tool)) return false;
  return !server.exclude_tools.includes(tool);
}

/**
 * Payload that turns one tool on or off (token kept). Turning off adds it
 * to `exclude_tools`; turning on removes it there and, when an include
 * list is in use, adds it to that list.
 */
export function toolToggleInput(server: McpServer, tool: string, active: boolean): McpServerInput {
  const input = formToInput(formFromServer(server), { editing: true });
  const exclude = input.exclude_tools.filter((t) => t !== tool);
  const include = [...input.include_tools];
  if (!active) exclude.push(tool);
  else if (include.length && !include.includes(tool)) include.push(tool);
  return { ...input, include_tools: include, exclude_tools: exclude };
}
