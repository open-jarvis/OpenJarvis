import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router';
import { toast } from 'sonner';
import {
  cancelTeamCampaign, createTeamCampaign, fetchCampaignFileBlob, fetchTeamCampaign,
  fetchTeamCampaigns, retryTeamHandoff, sendTeamFollowUp, setTeamCampaignMaxRuns,
} from '../lib/api';
import type { AgentTeam, TeamCampaign, TeamHandoff } from '../lib/api';

const field = 'rounded-lg px-3 py-2 text-sm w-full disabled:opacity-40';
const style = { background: 'var(--color-bg-secondary)', color: 'var(--color-text)', border: '1px solid var(--color-border)' };
const muted = { color: 'var(--color-text-secondary)' };
const card = { border: '1px solid var(--color-border)', borderRadius: 12 };

const CAMPAIGN_STATUS: Record<string, string> = {
  active: 'الفريق يعمل', waiting_for_you: 'بانتظار ردك', needs_attention: 'يحتاج تدخّلك',
  cancelled: 'أُوقف', failed: 'تعذّر البدء', completed: 'اكتمل',
};
const HANDOFF_STATUS: Record<TeamHandoff['status'], string> = {
  pending: 'في الانتظار', running: 'قيد التنفيذ', completed: 'اكتمل', failed: 'فشل', blocked: 'متوقف',
  waiting_paused: 'الوكيل موقوف', cancelled: 'أُلغي',
};
const KIND: Record<TeamHandoff['kind'], string> = { request: 'طلب', task: 'مهمة', report: 'تقرير' };

function useCampaignFile(campaignId: string, path: string) {
  const [src, setSrc] = useState('');
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let url = ''; let alive = true;
    fetchCampaignFileBlob(campaignId, path)
      .then((blob) => { if (alive) { url = URL.createObjectURL(blob); setSrc(url); } })
      .catch(() => alive && setFailed(true));
    return () => { alive = false; if (url) URL.revokeObjectURL(url); };
  }, [campaignId, path]);
  return { src, failed };
}

function AuthedImage({ campaignId, path, alt, className }: { campaignId: string; path: string; alt: string; className?: string }) {
  const { src, failed } = useCampaignFile(campaignId, path);
  if (failed) return <p className="text-xs" style={muted}>تعذّر تحميل الصورة.</p>;
  return src ? <img src={src} alt={alt} className={className} /> : <p className="text-xs" style={muted}>جارٍ التحميل…</p>;
}

function FinalImage({ campaignId, path }: { campaignId: string; path: string }) {
  const { src, failed } = useCampaignFile(campaignId, path);
  const name = path.split('/').pop() || 'final.png';
  return <figure className="space-y-2">
    {failed ? <p className="text-sm" role="alert">تعذّر تحميل الصورة.</p>
      : src ? <img src={src} alt={`الصورة النهائية ${name}`} className="w-full max-w-md aspect-square object-contain rounded-lg" style={{ background: 'var(--color-bg-secondary)' }} />
        : <p role="status" className="text-sm" style={muted}>جارٍ التحميل…</p>}
    <figcaption className="flex flex-wrap items-center gap-3 text-sm">
      <span className="text-xs break-all" dir="ltr" style={muted}>{path}</span>
      {src && <a href={src} download={name} className="underline font-semibold">تنزيل PNG</a>}
    </figcaption>
  </figure>;
}

export function NewRequestForm({ team, onCreated, disabled }: { team: AgentTeam; onCreated: (c: TeamCampaign) => void; disabled: boolean }) {
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    try {
      const campaign = await createTeamCampaign(team.id, form);
      (e.target as HTMLFormElement).reset();
      toast.success('أُرسل الطلب للفريق؛ بدأ المنسّق العمل.');
      onCreated(campaign);
    } catch (error) { toast.error(error instanceof Error ? error.message : 'تعذّر إرسال الطلب.'); }
    finally { setBusy(false); }
  }
  return <form onSubmit={submit} className="space-y-3 p-4 max-w-2xl" style={card}>
    <label className="block text-sm">العنوان<input name="title" required maxLength={120} className={`${field} mt-1`} style={style} placeholder="منشورات نوفمبر" disabled={busy || disabled} /></label>
    <label className="block text-sm">ماذا تريد من الفريق؟<textarea name="brief" required rows={4} maxLength={20000} className={`${field} mt-1`} style={style} placeholder="منشور واحد لعبوات الكرتون المموج مع موعد مقترح…" disabled={busy || disabled} /></label>
    <label className="block text-sm">صور المنتجات الأصلية<input name="photos" type="file" multiple accept="image/png,image/jpeg,image/webp" className="block mt-1 text-sm" disabled={busy || disabled} /></label>
    <label className="block text-sm">الشعار المعتمد<input name="logo" type="file" accept="image/png,image/jpeg,image/webp" className="block mt-1 text-sm" disabled={busy || disabled} /></label>
    <label className="block text-sm">بيانات التواصل المعتمدة (تُكتب حرفيًا على التصميم)<input name="contact" maxLength={160} className={`${field} mt-1`} style={style} dir="auto" disabled={busy || disabled} /></label>
    <label className="block text-sm max-w-40">حد التشغيل لهذا الطلب<input name="max_runs" type="number" min={1} max={60} defaultValue={16} className={`${field} mt-1`} style={style} disabled={busy || disabled} /></label>
    <button type="submit" disabled={busy || disabled} className="text-sm underline disabled:opacity-40">{busy ? 'جارٍ الإرسال…' : 'أرسل للفريق'}</button>
  </form>;
}

function HandoffRow({ handoff, onRetry }: { handoff: TeamHandoff; onRetry: (id: string) => void }) {
  const attention = handoff.status === 'blocked' || handoff.status === 'failed' || handoff.status === 'waiting_paused';
  return <li className="py-3 space-y-1" style={{ borderTop: '1px solid var(--color-border)' }}>
    <p className="text-sm"><span className="font-medium">{KIND[handoff.kind]}</span> · {handoff.source_name || 'أنت'} ← {handoff.target_name} · <span className={attention ? 'font-semibold' : ''}>{HANDOFF_STATUS[handoff.status]}</span></p>
    <p className="text-sm" dir="auto">{handoff.title}</p>
    {handoff.status_reason && <p role={attention ? 'alert' : undefined} className="text-sm" style={attention ? undefined : muted}>{handoff.status_reason}</p>}
    {handoff.files.length > 0 && <p className="text-xs" style={muted} dir="ltr">{handoff.files.join(' · ')}</p>}
    {handoff.result && <details className="text-sm"><summary>النتيجة</summary><p className="whitespace-pre-wrap mt-1" dir="auto">{handoff.result}</p></details>}
    {(handoff.status === 'blocked' || handoff.status === 'failed') && <button type="button" onClick={() => onRetry(handoff.id)} className="text-sm underline">إعادة المحاولة</button>}
  </li>;
}

export function CampaignDetail({ campaignId, backTo }: { campaignId: string; backTo: string }) {
  const [campaign, setCampaign] = useState<TeamCampaign | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try { setCampaign(await fetchTeamCampaign(campaignId)); setError(''); }
    catch (e) { setError(e instanceof Error ? e.message : 'تعذّر تحميل الطلب.'); }
  }, [campaignId]);
  useEffect(() => { load(); }, [load]);
  const live = !!campaign && campaign.open_handoffs > 0;
  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(load, 4000);
    return () => window.clearInterval(timer);
  }, [live, load]);
  async function act(action: () => Promise<TeamCampaign>, success: string) {
    setBusy(true);
    try { setCampaign(await action()); toast.success(success); }
    catch (e) { toast.error(e instanceof Error ? e.message : 'تعذّر التنفيذ.'); }
    finally { setBusy(false); }
  }
  if (error) return <p role="alert" className="text-sm">{error} <button type="button" onClick={load} className="underline">إعادة المحاولة</button></p>;
  if (!campaign) return <p role="status" className="text-sm">جارٍ التحميل…</p>;
  const images = (campaign.files || []).filter((f) => /^originals\/.*\.(png|jpe?g|webp)$/i.test(f.path));
  // Newest final export first: this is what the operator reviews and downloads.
  const finals = (campaign.files || []).filter((f) => /^final\/.*\.png$/i.test(f.path)).sort((a, b) => b.modified_at - a.modified_at);
  return <div className="space-y-4">
    <Link to={backTo} className="text-sm underline">→ كل طلبات الفريق</Link>
    <header className="space-y-1">
      <h2 className="text-lg font-semibold" dir="auto">{campaign.title}</h2>
      <p className="text-sm"><strong>{CAMPAIGN_STATUS[campaign.display_status] || campaign.display_status}</strong>{live && ' · يتحدث تلقائيًا'}</p>
      {campaign.status_reason && <p className="text-sm" style={muted}>{campaign.status_reason}</p>}
      <p className="text-xs" style={muted}>التشغيلات المستخدمة {campaign.runs_used} من {campaign.max_runs}{' '}
        {campaign.runs_used >= campaign.max_runs - 2 && campaign.max_runs < 60 && <button type="button" disabled={busy} className="underline disabled:opacity-40" onClick={() => act(() => setTeamCampaignMaxRuns(campaign.id, Math.min(60, campaign.max_runs + 8)), 'رُفع حد التشغيل.')}>رفع الحد بـ 8</button>}
      </p>
    </header>
    <section aria-labelledby="final-images-title" className="p-4 space-y-3" style={card}>
      <h3 id="final-images-title" className="text-sm font-semibold">الصور النهائية</h3>
      {finals.length ? <>
        <p className="text-xs" style={muted}>راجع الصورة بنفسك قبل استخدامها، وقارنها بالأصل إن كانت خدمة خارجية قد عدّلتها. لطلب تعديل اكتب للفريق بالأسفل.</p>
        <div className="grid gap-4 sm:grid-cols-2">{finals.map((f) => <FinalImage key={f.path} campaignId={campaign.id} path={f.path} />)}</div>
      </> : <p className="text-sm" style={muted}>لم يُصدِّر الفريق صورة نهائية بعد.</p>}
    </section>
    <section aria-label="سير العمل">
      <h4 className="text-sm font-semibold mb-1">سير العمل</h4>
      <ul>{(campaign.handoffs || []).map((h) => <HandoffRow key={h.id} handoff={h} onRetry={(id) => act(() => retryTeamHandoff(id), 'أُعيدت المحاولة.')} />)}</ul>
    </section>
    {images.length > 0 && <section aria-label="الملفات">
      <h4 className="text-sm font-semibold mb-2">الصور الأصلية</h4>
      <div className="flex flex-wrap gap-3">{images.map((f) => <figure key={f.path} className="w-32">
        <AuthedImage campaignId={campaign.id} path={f.path} alt={f.path} className="w-32 h-32 object-contain rounded" />
        <figcaption className="text-xs break-all" dir="ltr" style={muted}>{f.path}</figcaption>
      </figure>)}</div>
    </section>}
    {!['cancelled', 'failed'].includes(campaign.status) && <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); if (message.trim()) act(() => sendTeamFollowUp(campaign.id, message.trim()), 'أُرسلت رسالتك للمنسّق.').then(() => setMessage('')); }}>
      <label className="block text-sm">رسالة للفريق (ملاحظات، معلومات ناقصة، تعديلات)<textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={3} maxLength={20000} className={`${field} mt-1`} style={style} dir="auto" disabled={busy} /></label>
      <div className="flex gap-4">
        <button type="submit" disabled={busy || !message.trim()} className="text-sm underline disabled:opacity-40">أرسل للمنسّق</button>
        <button type="button" disabled={busy} className="text-sm underline disabled:opacity-40" onClick={() => window.confirm('إيقاف هذا الطلب؟ لن تُنفذ مهامه المنتظرة.') && act(() => cancelTeamCampaign(campaign.id), 'أُوقف الطلب.')}>إيقاف الطلب</button>
      </div>
    </form>}
  </div>;
}

export function CampaignList({ team }: { team: AgentTeam }) {
  const [campaigns, setCampaigns] = useState<TeamCampaign[] | null>(null);
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    try { setCampaigns(await fetchTeamCampaigns(team.id)); setError(''); }
    catch (e) { setError(e instanceof Error ? e.message : 'تعذّر تحميل الطلبات.'); }
  }, [team.id]);
  useEffect(() => { load(); }, [load]);
  if (error) return <p role="alert" className="text-sm">{error} <button type="button" onClick={load} className="underline">إعادة المحاولة</button></p>;
  if (!campaigns) return <p role="status" className="text-sm" style={muted}>جارٍ التحميل…</p>;
  if (!campaigns.length) return <p className="text-sm" style={muted}>لا توجد طلبات بعد.</p>;
  return <ul className="space-y-2">{campaigns.map((c) => <li key={c.id}>
    <Link to={`/agents/teams/${team.id}/requests/${c.id}`} className="block p-3 rounded-lg" style={card}>
      <span className="block text-sm font-medium" dir="auto">{c.title}</span>
      <span className="block text-xs" style={muted}>{CAMPAIGN_STATUS[c.display_status] || c.display_status}{c.attention_count > 0 && ` · ${c.attention_count} يحتاج تدخّلك`}</span>
    </Link>
  </li>)}</ul>;
}
