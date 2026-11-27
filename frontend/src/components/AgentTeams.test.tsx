import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';

import { AgentTeamToolbar } from './AgentTeams';

const teams = [{ id: 'team1', name: 'سوفت باك', created_at: 0 }];

function render(filter: string) {
  return renderToStaticMarkup(
    <MemoryRouter>
      <AgentTeamToolbar teams={teams} agents={[]} filter={filter} onFilter={vi.fn()} onUpdated={vi.fn()} unavailable={false} />
    </MemoryRouter>,
  );
}

describe('Agent team toolbar', () => {
  it('links a selected team to its own pages instead of expanding panels', () => {
    const html = render('team1');
    expect(html).toContain('href="/agents/teams/team1"');
    expect(html).toContain('href="/agents/teams/team1/settings"');
    expect(html).not.toContain('aria-expanded');
  });

  it('shows no team links when no team is selected', () => {
    expect(render('all')).not.toContain('/agents/teams/');
  });
});
