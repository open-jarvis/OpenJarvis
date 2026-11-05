import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { setTeamLead, updateAgentTeamPolicy } from '../lib/api';
import type { AgentTeam, ManagedAgent } from '../lib/api';
import { TeamConnections } from './TeamConnections';

const field = 'rounded-lg px-3 py-2 text-sm w-full disabled:opacity-40';
const style = { background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' };
const muted = { color: 'var(--color-text-secondary)' };

export function AgentTeamSettings({ team, teams, agents, onUpdated }: {
  team: AgentTeam; teams: AgentTeam[]; agents: ManagedAgent[]; onUpdated: () => void;
}) {
  const members = agents.filter((agent) => agent.team_id === team.id && agent.status !== 'archived');
  const [busy, setBusy] = useState(false);
  const [peers, setPeers] = useState(team.communicate_with || []);
  useEffect(() => { setPeers(team.communicate_with || []); }, [team.communicate_with]);

  async function chooseLead(agentId: string) {
    setBusy(true);
    try { await setTeamLead(team.id, agentId || null); onUpdated(); toast.success('حُفظ منسّق الفريق.'); }
    catch (error) { toast.error(error instanceof Error ? error.message : 'تعذّر حفظ المنسّق.'); }
    finally { setBusy(false); }
  }
  async function saveCommunication() {
    setBusy(true);
    try { await updateAgentTeamPolicy(team.id, peers); onUpdated(); toast.success('حُفظت إعدادات التواصل.'); }
    catch (error) { toast.error(error instanceof Error ? error.message : 'تعذّر حفظ الإعدادات.'); }
    finally { setBusy(false); }
  }

  return <div className="space-y-8">
    <section aria-labelledby="team-lead-title" className="space-y-2">
      <h3 id="team-lead-title" className="font-semibold text-sm">منسّق الفريق</h3>
      <label className="block text-sm max-w-xl" style={muted}>يستلم ما ترسله في «كلّم الفريق» ويوزّع المهام على الأعضاء.
        <select className={`${field} mt-1`} style={style} value={team.lead_agent_id || ''} disabled={busy} onChange={(e) => chooseLead(e.target.value)}>
          <option value="">بدون منسّق</option>
          {members.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
        </select>
      </label>
    </section>

    <TeamConnections team={team} agents={agents} />

    <section aria-labelledby="team-communication-title" className="space-y-3">
      <h3 id="team-communication-title" className="text-sm font-semibold">التواصل مع الفرق الأخرى</h3>
      <p className="text-sm max-w-2xl" style={muted}>وكلاء هذا الفريق يتواصلون مع بعضهم. التواصل مع فريق آخر ممنوع إلا إذا اختار كل فريق الآخر. الرسائل لا تشارك الحسابات أو الأدوات أو الذاكرة.</p>
      {teams.filter((peer) => peer.id !== team.id).map((peer) => <label key={peer.id} className="flex items-center gap-2 text-sm">
        <input type="checkbox" aria-label={`السماح بالتواصل مع ${peer.name}`} checked={peers.includes(peer.id)} disabled={busy} onChange={(e) => setPeers((current) => e.target.checked ? [...current, peer.id] : current.filter((id) => id !== peer.id))} />
        <span dir="auto">{peer.name}</span>
        <span className="text-xs" style={muted}>{peer.communicate_with?.includes(team.id) ? 'الفريق الآخر سمح بذلك' : 'الفريق الآخر لم يسمح بعد'}</span>
      </label>)}
      {teams.length < 2 && <p className="text-sm">أنشئ فريقًا آخر لاختيار شريك تواصل.</p>}
      <button type="button" disabled={busy} onClick={saveCommunication} className="text-sm underline disabled:opacity-40">حفظ إعدادات التواصل</button>
    </section>
  </div>;
}
