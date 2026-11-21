import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import {
  createTeamConnection, deleteTeamConnection, fetchTeamConnections,
  setTeamConnectionAccess, verifyTeamConnection,
} from '../lib/api';
import type { AgentTeam, ManagedAgent, TeamConnection } from '../lib/api';

const field = 'rounded-lg px-3 py-2 text-sm w-full disabled:opacity-40';
const style = { background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' };
const muted = { color: 'var(--color-text-secondary)' };
const card = { border: '1px solid var(--color-border)', borderRadius: 12 };

type AuthType = 'bearer' | 'header' | 'none';

const STATUS: Record<TeamConnection['status'], { label: string; tone: 'ok' | 'warn' | 'bad' }> = {
  verified: { label: 'متحقق منه', tone: 'ok' },
  configured: { label: 'محفوظ — لم يُختبر بعد', tone: 'warn' },
  error: { label: 'فشل الاختبار', tone: 'bad' },
  needs_authentication: { label: 'يحتاج مفتاحًا', tone: 'bad' },
};

function StatusChip({ status }: { status: TeamConnection['status'] }) {
  const value = STATUS[status];
  const color = value.tone === 'ok' ? 'var(--color-success, #1f7a4d)' : value.tone === 'bad' ? 'var(--color-error, #b3261e)' : 'var(--color-text-secondary)';
  return <span className="text-xs font-medium px-2 py-0.5 rounded-full" style={{ border: `1px solid ${color}`, color }}>{value.label}</span>;
}

function AddConnection({ team, onAdded, onCancel }: { team: AgentTeam; onAdded: (c: TeamConnection) => void; onCancel: () => void }) {
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [auth, setAuth] = useState<AuthType>('bearer');
  const [header, setHeader] = useState('');
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const created = await createTeamConnection(team.id, {
        name, provider: name, url, auth_type: auth, token,
        settings: auth === 'header' ? { header_name: header } : {},
      });
      setToken('');
      onAdded(created);
    } catch (error) { toast.error(error instanceof Error ? error.message : 'تعذّر حفظ الاتصال.'); }
    finally { setBusy(false); }
  }
  return <form onSubmit={save} className="space-y-3 max-w-xl p-4" style={card}>
    <p className="text-sm font-semibold">إضافة خادم MCP لفريق {team.name}</p>
    <label className="block text-sm">اسم الاتصال<input required maxLength={120} dir="auto" className={`${field} mt-1`} style={style} value={name} onChange={(e) => setName(e.target.value)} disabled={busy} placeholder="مثال: Gmail المبيعات" /></label>
    <label className="block text-sm">عنوان خادم MCP<input required type="url" dir="ltr" className={`${field} mt-1`} style={style} value={url} onChange={(e) => setUrl(e.target.value)} disabled={busy} placeholder="https://…/mcp" /></label>
    <label className="block text-sm">طريقة المصادقة<select className={`${field} mt-1`} style={style} value={auth} onChange={(e) => setAuth(e.target.value as AuthType)} disabled={busy}>
      <option value="bearer">مفتاح Bearer (Authorization)</option>
      <option value="header">مفتاح في ترويسة مخصصة</option>
      <option value="none">بدون مصادقة</option>
    </select></label>
    {auth === 'header' && <label className="block text-sm">اسم الترويسة<input required dir="ltr" className={`${field} mt-1`} style={style} value={header} onChange={(e) => setHeader(e.target.value)} disabled={busy} placeholder="api_token" /></label>}
    {auth !== 'none' && <label className="block text-sm">مفتاح الوصول<input type="password" autoComplete="off" dir="ltr" className={`${field} mt-1`} style={style} value={token} onChange={(e) => setToken(e.target.value)} disabled={busy} /></label>}
    <p className="text-xs" style={muted}>استخدم عنوان MCP ومفتاحًا خاصين بحساب هذه الشركة، لا حسابك العام. يُحفظ المفتاح بشكل خاص لهذا الفريق فقط ولا يُعرض مرة أخرى. لا يُستخدم أي حساب عام بديلًا عند الفشل.</p>
    <div className="flex gap-4">
      <button type="submit" disabled={busy} className="text-sm underline font-semibold disabled:opacity-40">{busy ? 'جارٍ الحفظ والاختبار…' : 'حفظ واختبار الاتصال'}</button>
      <button type="button" disabled={busy} onClick={onCancel} className="text-sm underline">إلغاء</button>
    </div>
  </form>;
}

function ConnectionCard({ team, connection, members, onVerify, onChanged }: {
  team: AgentTeam; connection: TeamConnection; members: ManagedAgent[];
  onVerify: (c: TeamConnection) => Promise<void>; onChanged: () => Promise<void>;
}) {
  const settings = connection.settings || {};
  const allowed = settings.agent_ids || [];
  const tools = settings.tools || [];
  const [scope, setScope] = useState<'all' | 'some'>(allowed.length ? 'some' : 'all');
  const [picked, setPicked] = useState<string[]>(allowed);
  const [busy, setBusy] = useState(false);
  async function run(action: () => Promise<unknown>, success?: string) {
    setBusy(true);
    try { await action(); if (success) toast.success(success); await onChanged(); }
    catch (error) { toast.error(error instanceof Error ? error.message : 'تعذّر التنفيذ.'); }
    finally { setBusy(false); }
  }
  const dirty = scope === 'all' ? allowed.length > 0 : picked.slice().sort().join() !== allowed.slice().sort().join();
  return <li className="p-4 space-y-3" style={card}>
    <div className="flex flex-wrap items-center gap-2 justify-between">
      <div className="min-w-0">
        <p className="text-sm font-semibold" dir="auto">{connection.name}</p>
        <p className="text-xs" style={muted}>MCP · <span dir="ltr">{connection.url}</span></p>
      </div>
      <StatusChip status={connection.status} />
    </div>
    {settings.last_error && <p role="alert" className="text-sm">{settings.last_error}</p>}
    {tools.length > 0 ? <details className="text-sm"><summary>الأدوات المتاحة ({tools.length})</summary>
      <ul className="mt-2 space-y-1">{tools.map((t) => <li key={t.name}><span className="font-medium" dir="ltr">{t.name}</span> <span className="text-xs" style={muted} dir="auto">{t.description}</span></li>)}</ul>
    </details> : <p className="text-xs" style={muted}>اختبر الاتصال لعرض الأدوات التي يوفرها.</p>}
    <fieldset className="space-y-2 text-sm">
      <legend className="font-medium">من يستخدم هذا الاتصال؟</legend>
      <label className="flex items-center gap-2"><input type="radio" checked={scope === 'all'} onChange={() => setScope('all')} disabled={busy} />كل وكلاء الفريق</label>
      <label className="flex items-center gap-2"><input type="radio" checked={scope === 'some'} onChange={() => setScope('some')} disabled={busy} />وكلاء محددون فقط</label>
      {scope === 'some' && <div className="ps-6 space-y-1">{members.map((m) => <label key={m.id} className="flex items-center gap-2"><input type="checkbox" checked={picked.includes(m.id)} disabled={busy} onChange={(e) => setPicked((c) => e.target.checked ? [...c, m.id] : c.filter((x) => x !== m.id))} /><span dir="auto">{m.name}</span></label>)}</div>}
      {dirty && <button type="button" disabled={busy || (scope === 'some' && picked.length === 0)} className="underline disabled:opacity-40" onClick={() => run(() => setTeamConnectionAccess(team.id, connection.id, scope === 'all' ? [] : picked), 'حُفظت الصلاحيات.')}>حفظ الصلاحيات</button>}
    </fieldset>
    <div className="flex flex-wrap gap-4 text-sm">
      <button type="button" disabled={busy} className="underline disabled:opacity-40" onClick={() => run(() => onVerify(connection))}>اختبار الاتصال</button>
      <button type="button" disabled={busy} className="underline disabled:opacity-40" onClick={() => window.confirm(`حذف «${connection.name}» من ${team.name}؟ سيُحذف مفتاحه المحفوظ، ولن تتأثر الفرق الأخرى.`) && run(() => deleteTeamConnection(team.id, connection.id), 'حُذف الاتصال.')}>حذف</button>
    </div>
    <p className="text-xs" style={muted}>لتغيير المفتاح احذف الاتصال وأضفه من جديد.</p>
  </li>;
}

export function TeamConnections({ team, agents }: { team: AgentTeam; agents: ManagedAgent[] }) {
  const members = agents.filter((a) => a.team_id === team.id && a.status !== 'archived');
  const [connections, setConnections] = useState<TeamConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [adding, setAdding] = useState(false);
  const load = useCallback(async () => {
    try { setConnections(await fetchTeamConnections(team.id)); setError(''); }
    catch { setError('تعذّر تحميل الاتصالات.'); }
    finally { setLoading(false); }
  }, [team.id]);
  useEffect(() => { load(); }, [load]);
  async function verify(connection: TeamConnection) {
    try {
      await verifyTeamConnection(team.id, connection.id);
      toast.success(`نجح اختبار «${connection.name}».`);
    } finally { await load(); }
  }
  return <section aria-labelledby="team-connections-title" className="space-y-3">
    <div>
      <h3 id="team-connections-title" className="font-semibold text-sm">اتصالات الفريق</h3>
      <p className="text-sm max-w-2xl" style={muted}>حسابات هذه الشركة فقط. كل اتصال خادم MCP تظهر أدواته للوكلاء المسموح لهم فقط. لا يُستخدم أي حساب عام بديلًا عند الفشل.</p>
    </div>
    {loading ? <p role="status" className="text-sm">جارٍ التحميل…</p> : error ? <p role="alert" className="text-sm">{error} <button type="button" onClick={load} className="underline">إعادة المحاولة</button></p> : <>
      {connections.length === 0 && !adding && <p className="text-sm">لا توجد اتصالات بعد.</p>}
      <ul className="space-y-3">{connections.map((c) => <ConnectionCard key={c.id} team={team} connection={c} members={members} onVerify={verify} onChanged={load} />)}</ul>
    </>}
    {adding ? <AddConnection team={team} onCancel={() => setAdding(false)} onAdded={async (created) => {
      setAdding(false); await load();
      try { await verify(created); } catch (e) { toast.error(e instanceof Error ? e.message : 'فشل اختبار الاتصال.'); }
    }} /> : <button type="button" onClick={() => setAdding(true)} className="text-sm underline font-semibold">+ إضافة اتصال</button>}
  </section>;
}
