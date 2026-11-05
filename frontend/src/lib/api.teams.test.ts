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
