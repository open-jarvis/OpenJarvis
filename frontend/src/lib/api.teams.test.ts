import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  vi.resetModules();
  vi.stubEnv('VITE_API_URL', '');
  vi.stubGlobal('fetch', fetchMock);
  vi.stubGlobal('localStorage', { getItem: () => null });
  fetchMock.mockReset();
});
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

it('preserves Unicode team names and reports server validation errors', async () => {
  const { createAgentTeam, fetchAgentTeams } = await import('./api');
  const team = { id: 'team-a', name: 'شركة التغليف', created_at: 1 };
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(team), { status: 201 }));
  await expect(createAgentTeam(team.name)).resolves.toEqual(team);
  const [url, options] = fetchMock.mock.calls[0];
  expect(url).toBe('/v1/managed-agents/teams');
  expect(JSON.parse(options?.body as string)).toEqual({ name: team.name });
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ teams: [team] })));
  await expect(fetchAgentTeams()).resolves.toEqual([team]);
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'A team with this name already exists' }), { status: 400 }));
  await expect(createAgentTeam(team.name)).rejects.toThrow('already exists');
});

it('sends explicit null to clear membership without replacing config', async () => {
  const { updateManagedAgent } = await import('./api');
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ id: 'agent-a', team_id: null })));
  await updateManagedAgent('agent-a', { team_id: null });
  const [url, options] = fetchMock.mock.calls[0];
  expect(url).toBe('/v1/managed-agents/agent-a');
  expect(options?.method).toBe('PATCH');
  expect(JSON.parse(options?.body as string)).toEqual({ team_id: null });
});

it('sends a company credential only when saving its own connection', async () => {
  const { createTeamConnection, fetchTeamConnections, updateAgentTeamPolicy } = await import('./api');
  const saved = { id: 'connection-a', team_id: 'team-a', provider: 'Gmail', status: 'configured' };
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(saved), { status: 201 }));
  await expect(createTeamConnection('team-a', { name: 'Company mail', provider: 'Gmail', url: 'https://mcp.example.test/mcp', auth_type: 'bearer', token: 'test-company-token' })).resolves.toEqual(saved);
  expect(fetchMock.mock.calls[0][0]).toBe('/v1/managed-agents/teams/team-a/connections');
  expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string).token).toBe('test-company-token');
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ connections: [saved] })));
  await expect(fetchTeamConnections('team-a')).resolves.toEqual([saved]);
  expect(fetchMock.mock.calls[1][1]?.body).toBeUndefined();
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ id: 'team-a', communicate_with: ['team-b'] })));
  await updateAgentTeamPolicy('team-a', ['team-b']);
  expect(fetchMock.mock.calls[2][0]).toBe('/v1/managed-agents/teams/team-a/policy');
  expect(JSON.parse(fetchMock.mock.calls[2][1]?.body as string)).toEqual({ communicate_with: ['team-b'] });
});
