import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, NavLink, useNavigate, useParams } from 'react-router';
import { toast } from 'sonner';
import { Plus } from 'lucide-react';
import { deleteAgentTeam, fetchAgentTeams, fetchManagedAgents, renameAgentTeam } from '../lib/api';
import type { AgentTeam, ManagedAgent } from '../lib/api';
import { useAppStore } from '../lib/store';
import { AgentTeamSettings } from '../components/AgentTeamSettings';
import { CampaignDetail, CampaignList, NewRequestForm } from '../components/TeamRequests';

const field = 'rounded-lg px-3 py-2 text-sm disabled:opacity-40';
const style = { background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' };
const muted = { color: 'var(--color-text-secondary)' };
const card = { border: '1px solid var(--color-border)', borderRadius: 12 };

const AGENT_STATUS: Record<ManagedAgent['status'], string> = {
  idle: 'جاهز', running: 'يعمل الآن', paused: 'موقوف', error: 'خطأ', archived: 'مؤرشف',
  needs_attention: 'يحتاج تدخّلك', budget_exceeded: 'تجاوز الميزانية', stalled: 'متعطّل',
};

interface TeamContext { team: AgentTeam; teams: AgentTeam[]; agents: ManagedAgent[]; reload: () => void }

function useTeam(teamId: string) {
  const agents = useAppStore((s) => s.managedAgents);
  const setManagedAgents = useAppStore((s) => s.setManagedAgents);
  const [teams, setTeams] = useState<AgentTeam[] | null>(null);
  const [error, setError] = useState('');
  const reload = useCallback(async () => {
    try {
      const [nextTeams, nextAgents] = await Promise.all([fetchAgentTeams(), fetchManagedAgents()]);
      setTeams(nextTeams); setManagedAgents(nextAgents); setError('');
    } catch { setError('تعذّر تحميل الفريق.'); }
  }, [setManagedAgents]);
  useEffect(() => { reload(); }, [reload]);
  return { team: teams?.find((t) => t.id === teamId), teams: teams || [], agents, loaded: teams !== null, error, reload };
}

/** Shared frame for every team page: breadcrumb, title and page tabs. */
function TeamShell({ title, children }: { title?: string; children: (ctx: TeamContext) => ReactNode }) {
  const { teamId = '' } = useParams();
  const { team, teams, agents, loaded, error, reload } = useTeam(teamId);
  const tab = ({ isActive }: { isActive: boolean }) => `px-3 py-2 text-sm -mb-px ${isActive ? 'font-semibold' : ''}`;
  const tabStyle = ({ isActive }: { isActive: boolean }) => ({ borderBottom: `2px solid ${isActive ? 'var(--color-text)' : 'transparent'}`, color: isActive ? 'var(--color-text)' : 'var(--color-text-secondary)' });
  let body: ReactNode;
  if (error) body = <p role="alert" className="text-sm">{error} <button type="button" onClick={reload} className="underline">إعادة المحاولة</button></p>;
  else if (!loaded) body = <p role="status" className="text-sm" style={muted}>جارٍ التحميل…</p>;
  else if (!team) body = <p role="alert" className="text-sm">هذا الفريق غير موجود أو حُذف. <Link to="/agents" className="underline">العودة إلى الوكلاء</Link></p>;
  else body = children({ team, teams, agents, reload });
  return <div dir="rtl" lang="ar" className="h-full overflow-y-auto" style={{ color: 'var(--color-text)' }}>
    <div className="max-w-4xl mx-auto px-4 sm:px-6 pt-12 pb-8 space-y-6">
      <nav aria-label="مسار التنقل" className="text-sm" style={muted}>
        <Link to="/agents" className="underline">الوكلاء</Link>
        {team && <> / <Link to={`/agents/teams/${team.id}`} className="underline" dir="auto">{team.name}</Link></>}
        {title && <> / <span>{title}</span></>}
      </nav>
      {team && <header className="space-y-3">
        <h1 className="text-xl font-semibold" dir="auto">فريق {team.name}</h1>
        <nav aria-label="صفحات الفريق" className="flex gap-2" style={{ borderBottom: '1px solid var(--color-border)' }}>
          <NavLink end to={`/agents/teams/${team.id}`} className={tab} style={tabStyle}>الفريق والطلبات</NavLink>
          <NavLink to={`/agents/teams/${team.id}/settings`} className={tab} style={tabStyle}>الإعدادات والاتصالات</NavLink>
        </nav>
      </header>}
      {body}
    </div>
  </div>;
}

export function TeamPage() {
  const navigate = useNavigate();
  const setSelectedAgentId = useAppStore((s) => s.setSelectedAgentId);
  return <TeamShell>{({ team, agents }) => {
    const members = agents.filter((a) => a.team_id === team.id && a.status !== 'archived');
    const lead = members.find((a) => a.id === team.lead_agent_id);
    return <>
      <section aria-labelledby="team-talk" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="team-talk" className="font-semibold">الطلبات</h2>
          {lead && <Link to={`/agents/teams/${team.id}/requests/new`} className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm" style={style}><Plus size={15} />طلب جديد للفريق</Link>}
        </div>
        <p className="text-sm max-w-2xl" style={muted}>{lead
          ? `طلبك يصل إلى المنسّق «${lead.name}»، فيوزّع المهام على الفريق، وتجد الصورة النهائية في صفحة الطلب لتراجعها وتنزّلها.`
          : <>حدّد منسّق الفريق أولًا من <Link to={`/agents/teams/${team.id}/settings`} className="underline">الإعدادات والاتصالات</Link> حتى تستطيع مخاطبة الفريق.</>}</p>
        <CampaignList team={team} />
      </section>
      <section aria-labelledby="team-members" className="space-y-2">
        <h2 id="team-members" className="font-semibold">أعضاء الفريق ({members.length})</h2>
        {members.length ? <ul className="grid gap-2 sm:grid-cols-2">{members.map((agent) => <li key={agent.id}>
          <button type="button" onClick={() => { setSelectedAgentId(agent.id); navigate('/agents'); }} className="w-full text-start p-3 rounded-lg" style={card}>
            <span className="block text-sm font-medium" dir="auto">{agent.name}{agent.id === team.lead_agent_id && ' · المنسّق'}</span>
            <span className="block text-xs" style={muted}>{AGENT_STATUS[agent.status] || agent.status}</span>
          </button>
        </li>)}</ul> : <p className="text-sm" style={muted}>لا يوجد وكلاء في هذا الفريق بعد. أضفهم من صفحة الوكلاء باختيار الفريق في إعدادات الوكيل.</p>}
      </section>
    </>;
  }}</TeamShell>;
}

export function NewTeamRequestPage() {
  const navigate = useNavigate();
  return <TeamShell title="طلب جديد">{({ team, agents }) => {
    const lead = agents.find((a) => a.id === team.lead_agent_id && a.team_id === team.id);
    return <section aria-labelledby="new-request" className="space-y-3">
      <h2 id="new-request" className="font-semibold">طلب جديد للفريق</h2>
      {lead ? <p className="text-sm" style={muted}>يستلمه المنسّق «{lead.name}».</p>
        : <p role="alert" className="text-sm">حدّد منسّق الفريق أولًا من <Link to={`/agents/teams/${team.id}/settings`} className="underline">الإعدادات والاتصالات</Link>.</p>}
      <NewRequestForm team={team} disabled={!lead} onCreated={(c) => navigate(`/agents/teams/${team.id}/requests/${c.id}`, { replace: true })} />
    </section>;
  }}</TeamShell>;
}

export function TeamRequestPage() {
  const { requestId = '' } = useParams();
  return <TeamShell title="الطلب">{({ team }) => <CampaignDetail key={requestId} campaignId={requestId} backTo={`/agents/teams/${team.id}`} />}</TeamShell>;
}

function RenameTeam({ team, onUpdated }: { team: AgentTeam; onUpdated: () => void }) {
  const [name, setName] = useState(team.name);
  const [busy, setBusy] = useState(false);
  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || name.trim() === team.name) return;
    setBusy(true);
    try { await renameAgentTeam(team.id, name.trim()); onUpdated(); toast.success('حُفظ اسم الفريق.'); }
    catch (error) { toast.error(error instanceof Error ? error.message : 'تعذّر حفظ الاسم.'); }
    finally { setBusy(false); }
  }
  return <form onSubmit={save} aria-labelledby="team-name-title" className="space-y-2">
    <h3 id="team-name-title" className="text-sm font-semibold">اسم الفريق</h3>
    <div className="flex flex-wrap gap-2">
      <input aria-label="اسم الفريق" dir="auto" required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} disabled={busy} className={`${field} flex-1 min-w-48 max-w-sm`} style={style} />
      <button type="submit" disabled={busy || !name.trim() || name.trim() === team.name} className={field} style={style}>حفظ الاسم</button>
    </div>
  </form>;
}

function DeleteTeam({ team }: { team: AgentTeam }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  async function remove() {
    if (!window.confirm(`حذف فريق «${team.name}»؟ يصبح وكلاؤه بلا فريق، وتُحذف اتصالاته. الوكلاء وأعمالهم تبقى.`)) return;
    setBusy(true);
    try { await deleteAgentTeam(team.id); toast.success('حُذف الفريق.'); navigate('/agents'); }
    catch { toast.error('تعذّر حذف الفريق. حاول مرة أخرى.'); setBusy(false); }
  }
  return <section aria-labelledby="team-delete-title" className="space-y-2 p-4" style={card}>
    <h3 id="team-delete-title" className="text-sm font-semibold">حذف الفريق</h3>
    <p className="text-sm" style={muted}>يصبح وكلاء الفريق بلا فريق، وتُحذف اتصالات الفريق وحساباته. الوكلاء وأعمالهم تبقى.</p>
    <button type="button" disabled={busy} onClick={remove} className="text-sm underline disabled:opacity-40">حذف الفريق</button>
  </section>;
}

export function TeamSettingsPage() {
  return <TeamShell title="الإعدادات والاتصالات">{({ team, teams, agents, reload }) => <div className="space-y-8">
    <RenameTeam key={team.name} team={team} onUpdated={reload} />
    <AgentTeamSettings team={team} teams={teams} agents={agents} onUpdated={reload} />
    <DeleteTeam team={team} />
  </div>}</TeamShell>;
}
