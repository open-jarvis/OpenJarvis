import { useState } from 'react';
import { Link } from 'react-router';
import { toast } from 'sonner';
import { Plus, MessagesSquare, Settings } from 'lucide-react';
import { createAgentTeam, updateManagedAgent } from '../lib/api';
import type { AgentTeam, ManagedAgent } from '../lib/api';

const style = { background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' };
const control = 'px-3 py-2 rounded-lg text-sm focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-40';

export function TeamSelect({ teams, value, onChange, disabled, id }: {
  teams: AgentTeam[]; value: string; onChange: (value: string) => void; disabled?: boolean; id: string;
}) {
  return <div>
    <label htmlFor={id} className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>Team</label>
    <select id={id} value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} className={`${control} w-full`} style={style}>
      <option value="">Unassigned</option>
      {teams.map((team) => <option key={team.id} value={team.id}>{team.name}</option>)}
    </select>
  </div>;
}

export function AgentTeamAssignment({ teams, agent, onUpdated }: {
  teams: AgentTeam[]; agent: ManagedAgent; onUpdated: () => void;
}) {
  const [saving, setSaving] = useState(false);
  async function assign(teamId: string) {
    setSaving(true);
    try {
      await updateManagedAgent(agent.id, { team_id: teamId || null });
      onUpdated(); toast.success('Team updated');
    } catch { toast.error('Could not update team. Please try again.'); }
    finally { setSaving(false); }
  }
  async function enableConnections(enabled: boolean) {
    setSaving(true);
    try { await updateManagedAgent(agent.id, { config: { ...agent.config, mcp_tools: enabled } }); onUpdated(); }
    catch { toast.error('Could not update connection access.'); }
    finally { setSaving(false); }
  }
  return <div className="space-y-2">
    <TeamSelect id="agent-team" teams={teams} value={agent.team_id || ''} onChange={assign} disabled={saving} />
    {!agent.team_id && agent.team_scoped && <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Assign a team to restore company connections. Global accounts remain unavailable.</p>}
    {agent.team_id && <label className="flex gap-2 items-center text-sm" style={{ color: 'var(--color-text-secondary)' }}><input type="checkbox" disabled={saving} checked={agent.config.mcp_tools !== false} onChange={(e) => enableConnections(e.target.checked)} />Enable this team's connections for this agent</label>}
  </div>;
}

export function AgentTeamToolbar({ teams, agents, filter, onFilter, onUpdated, unavailable }: {
  teams: AgentTeam[]; agents: ManagedAgent[]; filter: string; onFilter: (value: string) => void; onUpdated: () => void; unavailable: boolean;
}) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const selected = teams.find((team) => team.id === filter);
  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    try {
      const team = await createAgentTeam(name.trim());
      setCreating(false); setName(''); onUpdated(); onFilter(team.id);
      toast.success('Team created');
    } catch (error) { toast.error(error instanceof Error ? error.message : 'Could not save team.'); }
    finally { setBusy(false); }
  }
  return <section aria-label="Agent teams" className="mb-6 space-y-3">
    <div className="flex flex-wrap items-end gap-2">
      <div className="flex-1 min-w-48 max-w-sm">
        <label htmlFor="team-filter" className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>Team</label>
        <select id="team-filter" value={filter} onChange={(e) => { onFilter(e.target.value); setCreating(false); }} disabled={unavailable || busy} className={`${control} w-full`} style={style}>
          <option value="all">All teams · {agents.length} agents</option>
          <option value="unassigned">Unassigned agents ({agents.filter((agent) => !agent.team_id).length})</option>
          {teams.map((team) => <option key={team.id} value={team.id}>{team.name} ({agents.filter((agent) => agent.team_id === team.id).length})</option>)}
        </select>
      </div>
      <button type="button" disabled={unavailable || busy} onClick={() => { setCreating(true); setName(''); }} className={`${control} inline-flex items-center gap-2`} style={style}><Plus size={15} />New team</button>
      {selected && <>
        <Link to={`/agents/teams/${selected.id}`} className={`${control} inline-flex items-center gap-2`} style={style}><MessagesSquare size={15} />صفحة الفريق والطلبات</Link>
        <Link to={`/agents/teams/${selected.id}/settings`} className={`${control} inline-flex items-center gap-2`} style={style}><Settings size={15} />الإعدادات والاتصالات</Link>
      </>}
    </div>
    {creating && <form onSubmit={save} className="flex flex-wrap items-end gap-2">
      <div className="flex-1 min-w-48 max-w-sm">
        <label htmlFor="team-name" className="block text-sm mb-1" style={{ color: 'var(--color-text-secondary)' }}>Team name</label>
        <input id="team-name" autoFocus dir="auto" required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} disabled={busy} placeholder="Company or project name" className={`${control} w-full`} style={style} />
      </div>
      <button type="submit" disabled={busy || !name.trim()} className={control} style={style}>{busy ? 'Saving…' : 'Save team'}</button>
      <button type="button" disabled={busy} onClick={() => setCreating(false)} className={control} style={style}>Cancel</button>
    </form>}
    {unavailable && <p role="status" className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Teams could not be loaded. <button type="button" onClick={onUpdated} className="underline">Try again</button></p>}
  </section>;
}
