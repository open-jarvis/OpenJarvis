import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { createTeamConnection, deleteTeamConnection, fetchTeamConnections, updateAgentTeamPolicy } from '../lib/api';
import type { AgentTeam, TeamConnection } from '../lib/api';

const field = 'rounded-lg px-3 py-2 text-sm w-full disabled:opacity-40';
const style = { background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' };

export function AgentTeamSettings({ team, teams, onUpdated }: {
  team: AgentTeam; teams: AgentTeam[]; onUpdated: () => void;
}) {
  const [connections, setConnections] = useState<TeamConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [peers, setPeers] = useState(team.communicate_with || []);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState('');
  const [provider, setProvider] = useState('');
  const [url, setUrl] = useState('');
  const [auth, setAuth] = useState<'bearer' | 'none'>('bearer');
  const [token, setToken] = useState('');
  async function load() {
    setLoading(true); setError('');
    try { setConnections(await fetchTeamConnections(team.id)); }
    catch { setError('Could not load connections. Try again.'); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, [team.id]);
  useEffect(() => { setPeers(team.communicate_with || []); }, [team.communicate_with]);
  async function saveCommunication() {
    setBusy(true);
    try { await updateAgentTeamPolicy(team.id, peers); onUpdated(); toast.success('Communication settings saved'); }
    catch (error) { toast.error(error instanceof Error ? error.message : 'Could not save settings.'); }
    finally { setBusy(false); }
  }
  async function addConnection(e: React.FormEvent) {
    e.preventDefault(); setBusy(true);
    try {
      await createTeamConnection(team.id, { name, provider, url, auth_type: auth, token });
      setToken(''); setName(''); setProvider(''); setUrl(''); setAdding(false);
      await load(); toast.success('Connection saved. Account access will be verified when used.');
    } catch (error) { toast.error(error instanceof Error ? error.message : 'Could not save connection.'); }
    finally { setBusy(false); }
  }
  async function remove(connection: TeamConnection) {
    if (!window.confirm(`Remove “${connection.name}” from ${team.name}? Its saved credential will be removed. Other teams are unaffected.`)) return;
    setBusy(true);
    try { await deleteTeamConnection(team.id, connection.id); await load(); }
    catch { toast.error('Could not remove connection.'); }
    finally { setBusy(false); }
  }
  return <div className="mt-4 pt-4 space-y-5" style={{ borderTop: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
    <section aria-labelledby="team-connections-title" className="space-y-3">
      <h2 id="team-connections-title" className="font-semibold text-sm">Connections for {team.name}</h2>
      <p className="text-sm max-w-2xl" style={{ color: 'var(--color-text-secondary)' }}>These connections use this company's accounts. Global accounts are never used as a fallback. Agents must have team connections enabled in Overview.</p>
      {loading ? <p role="status" className="text-sm">Loading connections…</p> : error ? <p role="alert" className="text-sm">{error} <button type="button" onClick={load} className="underline">Retry</button></p> : connections.length === 0 ? <p className="text-sm">No company connections yet. Its agents cannot use global MCP accounts.</p> : <ul className="space-y-2">
        {connections.map((connection) => <li key={connection.id} className="flex flex-wrap justify-between items-center gap-2 py-2">
          <div className="min-w-0"><p className="text-sm font-medium" dir="auto">{connection.name} · {connection.provider}</p><p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>{connection.status === 'configured' ? 'Configured · account access not yet verified' : 'Needs authentication'}</p></div>
          <button type="button" disabled={busy} onClick={() => remove(connection)} className="text-sm underline disabled:opacity-40">Remove connection</button>
        </li>)}
      </ul>}
      {!adding && <button type="button" disabled={busy} onClick={() => setAdding(true)} className="text-sm underline">Add company connection</button>}
      {adding && <form onSubmit={addConnection} className="space-y-3 max-w-xl">
        <label className="block text-sm">Connection name<input className={`${field} mt-1`} style={style} required maxLength={120} dir="auto" placeholder="Gmail · Soft Pack" value={name} onChange={(e) => setName(e.target.value)} disabled={busy} /></label>
        <label className="block text-sm">Service<input className={`${field} mt-1`} style={style} required maxLength={120} placeholder="Gmail" value={provider} onChange={(e) => setProvider(e.target.value)} disabled={busy} /></label>
        <label className="block text-sm">MCP server address<input className={`${field} mt-1`} style={style} required type="url" placeholder="https://your-provider.example/mcp" value={url} onChange={(e) => setUrl(e.target.value)} disabled={busy} /></label>
        <label className="block text-sm">Authentication<select className={`${field} mt-1`} style={style} value={auth} onChange={(e) => { setAuth(e.target.value as 'bearer' | 'none'); setToken(''); }} disabled={busy}><option value="bearer">Access token for this company</option><option value="none">Server requires no authentication</option></select></label>
        {auth === 'bearer' && <label className="block text-sm">Company access token<input className={`${field} mt-1`} style={style} type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} disabled={busy} /><span className="block text-xs mt-1">Saved privately for this connection. Leave empty to configure authentication later.</span></label>}
        <p className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>Use an account-specific MCP endpoint or token supplied by your provider. Google sign-in and automatic OAuth renewal are not included here. One connection per service in each team.</p>
        <div className="flex gap-3"><button type="submit" disabled={busy} className="text-sm underline disabled:opacity-40">{busy ? 'Saving…' : 'Save connection'}</button><button type="button" disabled={busy} onClick={() => { setAdding(false); setToken(''); }} className="text-sm underline">Cancel</button></div>
      </form>}
    </section>
    <section aria-labelledby="team-communication-title" className="space-y-3">
      <h2 id="team-communication-title" className="text-sm font-semibold">Communication with other teams</h2>
      <p className="text-sm max-w-2xl" style={{ color: 'var(--color-text-secondary)' }}>Agents in this team can message each other. Communication across teams is blocked unless both teams select each other. Messages do not share accounts, tools or private conversation history.</p>
      {teams.filter((peer) => peer.id !== team.id).map((peer) => <label key={peer.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={peers.includes(peer.id)} disabled={busy} onChange={(e) => setPeers((current) => e.target.checked ? [...current, peer.id] : current.filter((id) => id !== peer.id))} /><span dir="auto">{peer.name}</span><span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>{peer.communicate_with?.includes(team.id) ? 'Other team allows this' : 'Other team has not allowed this'}</span></label>)}
      {teams.length < 2 && <p className="text-sm">Create another team to choose a communication partner.</p>}
      <button type="button" disabled={busy} onClick={saveCommunication} className="text-sm underline disabled:opacity-40">Save communication settings</button>
    </section>
  </div>;
}
