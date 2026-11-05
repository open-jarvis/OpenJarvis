import { useState } from 'react';
import { toast } from 'sonner';
import { Plus, Pencil, Trash2 } from 'lucide-react';
import { createAgentTeam, renameAgentTeam, deleteAgentTeam, updateManagedAgent } from '../lib/api';
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
  return <TeamSelect id="agent-team" teams={teams} value={agent.team_id || ''} onChange={assign} disabled={saving} />;
}

export function AgentTeamToolbar({ teams, agents, filter, onFilter, onUpdated, unavailable }: {
  teams: AgentTeam[]; agents: ManagedAgent[]; filter: string; onFilter: (value: string) => void; onUpdated: () => void; unavailable: boolean;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const selected = teams.find((team) => team.id === filter);
  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || editing === null) return;
    setBusy(true);
    try {
      if (editing) await renameAgentTeam(editing, name.trim());
      else await createAgentTeam(name.trim());
      setEditing(null); setName(''); onUpdated();
      toast.success(editing ? 'Team renamed' : 'Team created');
    } catch (error) { toast.error(error instanceof Error ? error.message : 'Could not save team.'); }
    finally { setBusy(false); }
  }
  async function remove() {
    if (!selected || !window.confirm(`Delete team “${selected.name}”? Its agents will become unassigned. Agents and their work will be kept.`)) return;
    setBusy(true);
    try {
      await deleteAgentTeam(selected.id);
      onFilter('all'); setEditing(null); onUpdated();
      toast.success('Team deleted. Its agents are now unassigned.');
    } catch { toast.error('Could not delete team. Please try again.'); }
    finally { setBusy(false); }
  }
  return <section aria-label="Agent teams" className="mb-6 space-y-3">
    <div className="flex flex-wrap items-end gap-2">
      <div className="flex-1 min-w-48 max-w-sm">
        <label htmlFor="team-filter" className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>Team</label>
        <select id="team-filter" value={filter} onChange={(e) => { onFilter(e.target.value); setEditing(null); }} disabled={unavailable || busy} className={`${control} w-full`} style={style}>
          <option value="all">All teams ({agents.length})</option>
          <option value="unassigned">Unassigned ({agents.filter((agent) => !agent.team_id).length})</option>
          {teams.map((team) => <option key={team.id} value={team.id}>{team.name} ({agents.filter((agent) => agent.team_id === team.id).length})</option>)}
        </select>
      </div>
      <button type="button" disabled={unavailable || busy} onClick={() => { setEditing(''); setName(''); }} className={`${control} inline-flex items-center gap-2`} style={style}><Plus size={15} />New team</button>
      {selected && <>
        <button type="button" disabled={busy} onClick={() => { setEditing(selected.id); setName(selected.name); }} className={`${control} inline-flex items-center gap-2`} style={style}><Pencil size={15} />Rename</button>
        <button type="button" disabled={busy} onClick={remove} className={`${control} inline-flex items-center gap-2`} style={style}><Trash2 size={15} />Delete team</button>
      </>}
    </div>
    {editing !== null && <form onSubmit={save} className="flex flex-wrap items-end gap-2">
      <div className="flex-1 min-w-48 max-w-sm">
        <label htmlFor="team-name" className="block text-sm mb-1" style={{ color: 'var(--color-text-secondary)' }}>Team name</label>
        <input id="team-name" autoFocus dir="auto" required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} disabled={busy} placeholder="Company or project name" className={`${control} w-full`} style={style} />
      </div>
      <button type="submit" disabled={busy || !name.trim()} className={control} style={style}>{busy ? 'Saving…' : 'Save team'}</button>
      <button type="button" disabled={busy} onClick={() => setEditing(null)} className={control} style={style}>Cancel</button>
    </form>}
    {unavailable && <p role="status" className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Teams could not be loaded. <button type="button" onClick={onUpdated} className="underline">Try again</button></p>}
  </section>;
}
