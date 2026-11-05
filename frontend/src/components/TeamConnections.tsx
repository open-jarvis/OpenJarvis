import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import {
  chooseBufferChannel, createTeamConnection, deleteTeamConnection, fetchTeamConnections,
  setTeamConnectionAccess, verifyTeamConnection,
} from '../lib/api';
import type { AgentTeam, BufferChannel, ManagedAgent, TeamConnection, TeamConnectionKind } from '../lib/api';

const field = 'rounded-lg px-3 py-2 text-sm w-full disabled:opacity-40';
const style = { background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' };
const muted = { color: 'var(--color-text-secondary)' };
const card = { border: '1px solid var(--color-border)', borderRadius: 12 };

type AuthType = 'bearer' | 'header' | 'none';
interface Preset {
  id: string; title: string; summary: string; kind: TeamConnectionKind;
  name: string; provider: string; auth?: AuthType;
  tokenLabel: string; help: string;
}

const PRESETS: Preset[] = [
  {
    id: 'buffer', title: 'Buffer', summary: 'جدولة المنشورات بعد موافقتك فقط؛ لا يصل إليه الوكلاء.', kind: 'buffer',
    name: 'Buffer', provider: 'Buffer', tokenLabel: 'مفتاح Buffer API', help: 'من Buffer ← Settings ← API، بصلاحية إنشاء المنشورات.',
  },
  {
    id: 'r2', title: 'Cloudflare R2', summary: 'رابط عام للصورة المعتمدة فقط، يحتاجه Buffer وقت النشر.', kind: 'r2',
    name: 'Cloudflare R2', provider: 'Cloudflare R2', tokenLabel: 'R2 Secret Access Key', help: 'bucket عام خاص بالشركة. تُرفع الصور المعتمدة فقط بأسماء عشوائية.',
  },
  {
    id: 'mcp', title: 'خادم MCP', summary: 'أي خادم MCP عبر HTTP بحساب هذه الشركة (Gmail، Drive، …).', kind: 'mcp',
    name: '', provider: '', auth: 'bearer', tokenLabel: 'مفتاح الوصول', help: 'استخدم عنوان MCP ومفتاحًا خاصين بحساب هذه الشركة، لا حسابك العام.',
  },
];

const STATUS: Record<TeamConnection['status'], { label: string; tone: 'ok' | 'warn' | 'bad' }> = {
  verified: { label: 'متحقق منه', tone: 'ok' },
  configured: { label: 'محفوظ — لم يُختبر بعد', tone: 'warn' },
  error: { label: 'فشل الاختبار', tone: 'bad' },
  needs_authentication: { label: 'يحتاج مفتاحًا', tone: 'bad' },
};
const KIND_LABEL: Record<TeamConnectionKind, string> = { mcp: 'MCP · أدوات للوكلاء', buffer: 'نشر · بعد موافقتك فقط', r2: 'استضافة الصور المعتمدة' };

function StatusChip({ status }: { status: TeamConnection['status'] }) {
  const value = STATUS[status];
  const color = value.tone === 'ok' ? 'var(--color-success, #1f7a4d)' : value.tone === 'bad' ? 'var(--color-error, #b3261e)' : 'var(--color-text-secondary)';
  return <span className="text-xs font-medium px-2 py-0.5 rounded-full" style={{ border: `1px solid ${color}`, color }}>{value.label}</span>;
}

function AddConnection({ team, onAdded, onCancel }: { team: AgentTeam; onAdded: (c: TeamConnection) => void; onCancel: () => void }) {
  const [preset, setPreset] = useState<Preset | null>(null);
  const [name, setName] = useState('');
  const [url, setUrl] = useState('');
  const [auth, setAuth] = useState<AuthType>('bearer');
  const [header, setHeader] = useState('');
  const [token, setToken] = useState('');
  const [settings, setSettings] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  function choose(next: Preset) {
    setPreset(next); setName(next.name); setUrl(''); setAuth(next.auth || 'bearer');
    setHeader(''); setToken(''); setSettings({});
  }
  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!preset) return;
    setBusy(true);
    try {
      const created = await createTeamConnection(team.id, preset.kind === 'mcp'
        ? { name, provider: preset.provider || name, url, auth_type: auth, token, kind: 'mcp', settings: { ...(auth === 'header' ? { header_name: header } : {}), preset: preset.id } }
        : { name, provider: preset.provider, url: '', auth_type: 'bearer', token, kind: preset.kind, settings });
      setToken('');
      onAdded(created);
    } catch (error) { toast.error(error instanceof Error ? error.message : 'تعذّر حفظ الاتصال.'); }
    finally { setBusy(false); }
  }
  if (!preset) {
    return <div className="space-y-2">
      <p className="text-sm font-medium">اختر الخدمة</p>
      <div className="grid gap-2 sm:grid-cols-2">
        {PRESETS.map((p) => <button key={p.id} type="button" onClick={() => choose(p)} className="text-start p-3" style={card}>
          <span className="block text-sm font-semibold" dir="auto">{p.title}</span>
          <span className="block text-xs mt-1" style={muted}>{p.summary}</span>
        </button>)}
      </div>
      <button type="button" onClick={onCancel} className="text-sm underline">إلغاء</button>
    </div>;
  }
  const custom = preset.id === 'mcp';
  return <form onSubmit={save} className="space-y-3 max-w-xl p-4" style={card}>
    <p className="text-sm font-semibold">إضافة {preset.title} لفريق {team.name}</p>
    <label className="block text-sm">اسم الاتصال<input required maxLength={120} dir="auto" className={`${field} mt-1`} style={style} value={name} onChange={(e) => setName(e.target.value)} disabled={busy} placeholder="مثال: Gmail المبيعات" /></label>
    {custom && <>
      <label className="block text-sm">عنوان خادم MCP<input required type="url" dir="ltr" className={`${field} mt-1`} style={style} value={url} onChange={(e) => setUrl(e.target.value)} disabled={busy} placeholder="https://…/mcp" /></label>
      <label className="block text-sm">طريقة المصادقة<select className={`${field} mt-1`} style={style} value={auth} onChange={(e) => setAuth(e.target.value as AuthType)} disabled={busy}>
        <option value="bearer">مفتاح Bearer (Authorization)</option>
        <option value="header">مفتاح في ترويسة مخصصة</option>
        <option value="none">بدون مصادقة</option>
      </select></label>
      {auth === 'header' && <label className="block text-sm">اسم الترويسة<input required dir="ltr" className={`${field} mt-1`} style={style} value={header} onChange={(e) => setHeader(e.target.value)} disabled={busy} placeholder="api_token" /></label>}
    </>}
    {preset.kind === 'r2' && ([['account_id', 'معرّف حساب Cloudflare'], ['bucket', 'اسم الـbucket العام'], ['access_key_id', 'R2 Access Key ID'], ['public_base_url', 'الرابط العام للـbucket (r2.dev أو نطاق خاص)']] as const).map(([key, label]) =>
      <label key={key} className="block text-sm">{label}<input required dir="ltr" className={`${field} mt-1`} style={style} value={settings[key] || ''} onChange={(e) => setSettings((c) => ({ ...c, [key]: e.target.value }))} disabled={busy} /></label>)}
    {auth !== 'none' && <label className="block text-sm">{preset.tokenLabel}<input required={!custom} type="password" autoComplete="off" dir="ltr" className={`${field} mt-1`} style={style} value={token} onChange={(e) => setToken(e.target.value)} disabled={busy} /></label>}
    <p className="text-xs" style={muted}>{preset.help} يُحفظ المفتاح بشكل خاص لهذا الفريق فقط ولا يُعرض مرة أخرى. لا يُستخدم أي حساب عام بديلًا عند الفشل.</p>
    <div className="flex gap-4">
      <button type="submit" disabled={busy} className="text-sm underline font-semibold disabled:opacity-40">{busy ? 'جارٍ الحفظ والاختبار…' : 'حفظ واختبار الاتصال'}</button>
      <button type="button" disabled={busy} onClick={() => setPreset(null)} className="text-sm underline">رجوع</button>
    </div>
  </form>;
}

function ConnectionCard({ team, connection, members, channels, onVerify, onChanged }: {
  team: AgentTeam; connection: TeamConnection; members: ManagedAgent[]; channels: BufferChannel[];
  onVerify: (c: TeamConnection) => Promise<void>; onChanged: () => Promise<void>;
}) {
  const settings = (connection.settings || {}) as Record<string, unknown>;
  const kind = connection.kind || 'mcp';
  const allowed = (settings.agent_ids as string[] | undefined) || [];
  const tools = (settings.tools as { name: string; description: string }[] | undefined) || [];
  const [scope, setScope] = useState<'all' | 'some'>(allowed.length ? 'some' : 'all');
  const [picked, setPicked] = useState<string[]>(allowed);
  const [paid, setPaid] = useState(Boolean(settings.paid));
  const [busy, setBusy] = useState(false);
  async function run(action: () => Promise<unknown>, success?: string) {
    setBusy(true);
    try { await action(); if (success) toast.success(success); await onChanged(); }
    catch (error) { toast.error(error instanceof Error ? error.message : 'تعذّر التنفيذ.'); }
    finally { setBusy(false); }
  }
  const dirty = paid !== Boolean(settings.paid) || (scope === 'all' ? allowed.length > 0 : picked.slice().sort().join() !== allowed.slice().sort().join());
  return <li className="p-4 space-y-3" style={card}>
    <div className="flex flex-wrap items-center gap-2 justify-between">
      <div className="min-w-0">
        <p className="text-sm font-semibold" dir="auto">{connection.name}</p>
        <p className="text-xs" style={muted}>{KIND_LABEL[kind]}{kind === 'mcp' && <> · <span dir="ltr">{connection.url}</span></>}</p>
      </div>
      <StatusChip status={connection.status} />
    </div>
    {typeof settings.last_error === 'string' && settings.last_error && <p role="alert" className="text-sm">{settings.last_error}</p>}
    {kind === 'buffer' && <div className="text-sm space-y-1">
      <p>القناة: {String(settings.channel_name || 'لم تُختر بعد')}</p>
      {channels.length > 0 && <select aria-label="قناة Buffer" className={field} style={style} disabled={busy} value={String(settings.channel_id || '')} onChange={(e) => e.target.value && run(() => chooseBufferChannel(team.id, connection.id, e.target.value), 'حُفظت القناة.')}>
        <option value="">اختر صفحة الشركة في Buffer…</option>
        {channels.map((c) => <option key={c.id} value={c.id}>{c.displayName || c.name} · {c.service} · {c.timezone}</option>)}
      </select>}
    </div>}
    {kind === 'mcp' && <>
      {tools.length > 0 ? <details className="text-sm"><summary>الأدوات المتاحة ({tools.length})</summary>
        <ul className="mt-2 space-y-1">{tools.map((t) => <li key={t.name}><span className="font-medium" dir="ltr">{t.name}</span> <span className="text-xs" style={muted} dir="auto">{t.description}</span></li>)}</ul>
      </details> : <p className="text-xs" style={muted}>اختبر الاتصال لعرض الأدوات التي يوفرها.</p>}
      <fieldset className="space-y-2 text-sm">
        <legend className="font-medium">من يستخدم هذا الاتصال؟</legend>
        <label className="flex items-center gap-2"><input type="radio" checked={scope === 'all'} onChange={() => setScope('all')} disabled={busy} />كل وكلاء الفريق</label>
        <label className="flex items-center gap-2"><input type="radio" checked={scope === 'some'} onChange={() => setScope('some')} disabled={busy} />وكلاء محددون فقط</label>
        {scope === 'some' && <div className="ps-6 space-y-1">{members.map((m) => <label key={m.id} className="flex items-center gap-2"><input type="checkbox" checked={picked.includes(m.id)} disabled={busy} onChange={(e) => setPicked((c) => e.target.checked ? [...c, m.id] : c.filter((x) => x !== m.id))} /><span dir="auto">{m.name}</span></label>)}</div>}
        <label className="flex items-center gap-2"><input type="checkbox" checked={paid} onChange={(e) => setPaid(e.target.checked)} disabled={busy} />خدمة مدفوعة — لا تُستخدم إلا إذا سمح بها الطلب</label>
        {dirty && <button type="button" disabled={busy || (scope === 'some' && picked.length === 0)} className="underline disabled:opacity-40" onClick={() => run(() => setTeamConnectionAccess(team.id, connection.id, scope === 'all' ? [] : picked, paid), 'حُفظت الصلاحيات.')}>حفظ الصلاحيات</button>}
      </fieldset>
    </>}
    <div className="flex flex-wrap gap-4 text-sm">
      <button type="button" disabled={busy} className="underline disabled:opacity-40" onClick={() => run(() => onVerify(connection))}>{kind === 'buffer' ? 'اختبار وتحميل القنوات' : 'اختبار الاتصال'}</button>
      <button type="button" disabled={busy} className="underline disabled:opacity-40" onClick={() => window.confirm(`حذف «${connection.name}» من ${team.name}؟ سيُحذف مفتاحه المحفوظ، ولن تتأثر الفرق الأخرى.`) && run(() => deleteTeamConnection(team.id, connection.id), 'حُذف الاتصال.')}>حذف</button>
    </div>
    <p className="text-xs" style={muted}>لتغيير المفتاح احذف الاتصال وأضفه من جديد.</p>
  </li>;
}

export function TeamConnections({ team, agents }: { team: AgentTeam; agents: ManagedAgent[] }) {
  const members = agents.filter((a) => a.team_id === team.id && a.status !== 'archived');
  const [connections, setConnections] = useState<TeamConnection[]>([]);
  const [channels, setChannels] = useState<Record<string, BufferChannel[]>>({});
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
      const result = await verifyTeamConnection(team.id, connection.id);
      if (result.channels) setChannels((c) => ({ ...c, [connection.id]: result.channels || [] }));
      toast.success(`نجح اختبار «${connection.name}».`);
    } finally { await load(); }
  }
  return <section aria-labelledby="team-connections-title" className="space-y-3">
    <div>
      <h3 id="team-connections-title" className="font-semibold text-sm">اتصالات الفريق</h3>
      <p className="text-sm max-w-2xl" style={muted}>حسابات هذه الشركة فقط. اتصالات MCP تظهر كأدوات للوكلاء المسموح لهم، وBuffer وR2 يستخدمهما الخادم بعد موافقتك فقط. لا يُستخدم أي حساب عام بديلًا عند الفشل.</p>
    </div>
    {loading ? <p role="status" className="text-sm">جارٍ التحميل…</p> : error ? <p role="alert" className="text-sm">{error} <button type="button" onClick={load} className="underline">إعادة المحاولة</button></p> : <>
      {connections.length === 0 && !adding && <p className="text-sm">لا توجد اتصالات بعد.</p>}
      <ul className="space-y-3">{connections.map((c) => <ConnectionCard key={c.id} team={team} connection={c} members={members} channels={channels[c.id] || []} onVerify={verify} onChanged={load} />)}</ul>
    </>}
    {adding ? <AddConnection team={team} onCancel={() => setAdding(false)} onAdded={async (created) => {
      setAdding(false); await load();
      try { await verify(created); } catch (e) { toast.error(e instanceof Error ? e.message : 'فشل اختبار الاتصال.'); }
    }} /> : <button type="button" onClick={() => setAdding(true)} className="text-sm underline font-semibold">+ إضافة اتصال</button>}
  </section>;
}
