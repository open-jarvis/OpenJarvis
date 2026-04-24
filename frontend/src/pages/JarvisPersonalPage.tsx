import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Copy,
  Clock3,
  Loader2,
  Mail,
  Mic,
  MoveRight,
  Radio,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Waves,
} from 'lucide-react';
import { toast } from 'sonner';
import { fetchPersonalCockpit } from '../lib/api';
import type { PersonalCockpitRecord, PersonalCockpitSnapshot } from '../types';

function fmtDate(value?: string) {
  if (!value) return 'n/a';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

function fmtAgo(seconds?: number | null) {
  if (seconds == null) return 'n/a';
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min`;
  return `${Math.floor(seconds / 3600)} h`;
}

function toneFromText(value: string) {
  const text = value.toLowerCase();
  if (text.includes('ok') || text.includes('active') || text.includes('recent') || text.includes('executed')) {
    return {
      color: 'var(--color-success)',
      bg: 'color-mix(in srgb, var(--color-success) 12%, transparent)',
      border: 'color-mix(in srgb, var(--color-success) 30%, transparent)',
    };
  }
  if (
    text.includes('pending') ||
    text.includes('pause') ||
    text.includes('warning') ||
    text.includes('idle') ||
    text.includes('info')
  ) {
    return {
      color: 'var(--color-warning)',
      bg: 'color-mix(in srgb, var(--color-warning) 12%, transparent)',
      border: 'color-mix(in srgb, var(--color-warning) 30%, transparent)',
    };
  }
  return {
    color: 'var(--color-error)',
    bg: 'color-mix(in srgb, var(--color-error) 12%, transparent)',
    border: 'color-mix(in srgb, var(--color-error) 30%, transparent)',
  };
}

function Badge({ value }: { value: string }) {
  const tone = toneFromText(value);
  return (
    <span
      className="px-2.5 py-1 rounded-full text-xs font-medium"
      style={{ color: tone.color, background: tone.bg, border: `1px solid ${tone.border}` }}
    >
      {value}
    </span>
  );
}

function Section({
  title,
  subtitle,
  icon: Icon,
  action,
  id,
  children,
}: {
  title: string;
  subtitle?: string;
  icon: typeof Mic;
  action?: React.ReactNode;
  id?: string;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="hud-panel p-5 scroll-mt-6">
      <div className="hud-panel-head flex items-start gap-3 mb-5">
        <div
          className="w-8 h-8 rounded-xl flex items-center justify-center shrink-0"
          style={{
            background: 'color-mix(in srgb, var(--color-accent) 10%, transparent)',
            border: '1px solid color-mix(in srgb, var(--color-accent) 22%, transparent)',
          }}
        >
          <Icon size={15} style={{ color: 'var(--color-accent)' }} />
        </div>
        <div className="min-w-0">
          <h2 className="text-sm font-semibold tracking-[0.14em] uppercase" style={{ color: 'var(--color-text)' }}>
            {title}
          </h2>
          {subtitle && (
            <p className="text-sm mt-1" style={{ color: 'var(--color-text-secondary)' }}>
              {subtitle}
            </p>
          )}
        </div>
        {action && <div className="ml-auto">{action}</div>}
      </div>
      {children}
    </section>
  );
}

function SummaryCard({
  title,
  value,
  note,
  badge,
  accent = 'var(--color-accent)',
}: {
  title: string;
  value: React.ReactNode;
  note?: React.ReactNode;
  badge?: React.ReactNode;
  accent?: string;
}) {
  return (
    <div
      className="hud-panel p-4"
      style={{
        background: `linear-gradient(180deg, color-mix(in srgb, ${accent} 8%, var(--color-surface)), var(--color-surface))`,
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--color-text-tertiary)' }}>
          {title}
        </div>
        {badge}
      </div>
      <div className="mt-3 text-2xl font-semibold leading-tight" style={{ color: 'var(--color-text)' }}>
        {value}
      </div>
      {note && (
        <div className="mt-2 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
          {note}
        </div>
      )}
    </div>
  );
}

function MessageCard({
  title,
  icon: Icon,
  content,
  compact = false,
}: {
  title: string;
  icon: typeof Mic;
  content: string;
  compact?: boolean;
}) {
  return (
    <Section title={title} icon={Icon}>
      <div
        className={`rounded-2xl px-4 py-4 ${compact ? 'min-h-[112px]' : 'min-h-[148px]'}`}
        style={{
          background: 'var(--color-bg-secondary)',
          border: '1px solid var(--color-border)',
          color: 'var(--color-text)',
        }}
      >
        <ExpandableText text={content} emptyLabel="Aucun contenu récent." maxChars={260} />
      </div>
    </Section>
  );
}

function AttentionCard({
  title,
  detail,
  level,
}: {
  title: string;
  detail: string;
  level: 'warning' | 'info' | 'ok';
}) {
  const tone =
    level === 'ok'
      ? toneFromText('ok')
      : level === 'info'
      ? toneFromText('warning')
      : toneFromText('error');

  return (
    <div
      className="rounded-2xl px-4 py-4"
      style={{
        background: tone.bg,
        border: `1px solid ${tone.border}`,
      }}
    >
      <div className="text-sm font-semibold" style={{ color: tone.color }}>
        {title}
      </div>
      <div className="text-sm mt-2" style={{ color: 'var(--color-text)' }}>
        {detail}
      </div>
    </div>
  );
}

function GuidanceCard({
  title,
  detail,
  hint,
}: {
  title: string;
  detail: string;
  hint?: string;
}) {
  return (
    <div
      className="rounded-2xl px-4 py-4"
      style={{
        background: 'var(--color-bg-secondary)',
        border: '1px solid var(--color-border)',
      }}
    >
      <div className="text-xs uppercase tracking-[0.15em]" style={{ color: 'var(--color-text-tertiary)' }}>
        {title}
      </div>
      <div className="text-sm font-medium mt-2" style={{ color: 'var(--color-text)' }}>
        {detail}
      </div>
      {hint && (
        <div className="text-sm mt-2" style={{ color: 'var(--color-text-secondary)' }}>
          {hint}
        </div>
      )}
    </div>
  );
}

function InfoChip({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div
      className="rounded-full px-3 py-1.5 text-xs"
      style={{
        background: 'var(--color-bg-secondary)',
        border: '1px solid var(--color-border)',
        color: 'var(--color-text-secondary)',
      }}
    >
      <span style={{ color: 'var(--color-text-tertiary)' }}>{label}:</span>{' '}
      <span style={{ color: 'var(--color-text)' }}>{value}</span>
    </div>
  );
}

function MetricRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2.5" style={{ borderBottom: '1px solid var(--color-border-subtle)' }}>
      <div className="text-xs uppercase tracking-[0.14em]" style={{ color: 'var(--color-text-tertiary)' }}>
        {label}
      </div>
      <div className="text-sm text-right max-w-[70%]" style={{ color: 'var(--color-text)' }}>
        {value}
      </div>
    </div>
  );
}

function ExpandableText({
  text,
  emptyLabel,
  maxChars = 220,
}: {
  text: string;
  emptyLabel: string;
  maxChars?: number;
}) {
  if (!text) {
    return <div className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>{emptyLabel}</div>;
  }
  if (text.length <= maxChars) {
    return (
      <div className="text-sm whitespace-pre-wrap" style={{ color: 'var(--color-text)' }}>
        {text}
      </div>
    );
  }
  return (
    <details className="group">
      <summary className="list-none cursor-pointer">
        <div className="text-sm whitespace-pre-wrap" style={{ color: 'var(--color-text)' }}>
          {text.slice(0, maxChars).trim()}…
        </div>
        <div className="text-xs mt-2" style={{ color: 'var(--color-accent)' }}>
          Voir tout
        </div>
      </summary>
      <div className="text-sm whitespace-pre-wrap mt-3" style={{ color: 'var(--color-text)' }}>
        {text}
      </div>
    </details>
  );
}

function CompactRecord({
  record,
  labels,
}: {
  record?: PersonalCockpitRecord | null;
  labels: Array<{ key: string; label: string }>;
}) {
  if (!record) {
    return <div className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>Aucun état disponible.</div>;
  }

  return (
    <div className="space-y-1">
      {labels.map(({ key, label }) => {
        const value = record[key];
        if (value == null || value === '') return null;
        return <MetricRow key={key} label={label} value={String(value)} />;
      })}
    </div>
  );
}

function PendingValidationCard({
  pending,
}: {
  pending?: PersonalCockpitRecord | null;
}) {
  if (!pending) {
    return (
      <div
        className="rounded-2xl px-4 py-4"
        style={{
          background: 'color-mix(in srgb, var(--color-success) 10%, transparent)',
          border: '1px solid color-mix(in srgb, var(--color-success) 24%, transparent)',
        }}
      >
        <div className="flex items-center gap-2">
          <CheckCircle2 size={16} style={{ color: 'var(--color-success)' }} />
          <div className="font-semibold" style={{ color: 'var(--color-text)' }}>
            Aucune validation en attente
          </div>
        </div>
        <div className="text-sm mt-2" style={{ color: 'var(--color-text-secondary)' }}>
          Ruth n’a rien à confirmer vocalement au moment du snapshot.
        </div>
      </div>
    );
  }

  const action = String(pending.action || 'Action réelle en attente');
  const executable = String(pending.executable || 'n/a');
  const requestedAt = String(pending.requested_at || '');

  return (
    <div
      className="rounded-2xl px-4 py-4"
      style={{
        background: 'color-mix(in srgb, var(--color-warning) 12%, transparent)',
        border: '1px solid color-mix(in srgb, var(--color-warning) 30%, transparent)',
      }}
    >
      <div className="flex items-center gap-2">
        <AlertTriangle size={16} style={{ color: 'var(--color-warning)' }} />
        <div className="font-semibold" style={{ color: 'var(--color-text)' }}>
          Validation attendue maintenant
        </div>
      </div>
      <div className="text-base font-medium mt-3" style={{ color: 'var(--color-text)' }}>
        {action}
      </div>
      <div className="text-sm mt-2" style={{ color: 'var(--color-text-secondary)' }}>
        Jarvis attend un `oui/non` explicite avant toute exécution réelle.
      </div>
      <div className="flex flex-wrap gap-2 mt-4">
        <InfoChip label="Executable" value={executable} />
        <InfoChip label="Demandée" value={fmtDate(requestedAt)} />
      </div>
    </div>
  );
}

function MailList({
  title,
  items,
}: {
  title: string;
  items: Array<Record<string, unknown>>;
}) {
  if (items.length === 0) return null;
  return (
    <div className="space-y-2">
      <div className="text-xs uppercase tracking-[0.14em]" style={{ color: 'var(--color-text-tertiary)' }}>
        {title}
      </div>
      {items.slice(0, 4).map((item, index) => (
        <div key={`${String(item.message_id || item.subject || index)}`} className="rounded-xl px-3 py-3" style={{ background: 'var(--color-bg-secondary)' }}>
          <div className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
            {String(item.subject || 'Sans sujet')}
          </div>
          <div className="text-xs mt-1" style={{ color: 'var(--color-text-secondary)' }}>
            {String(item.sender || '')}
          </div>
          <div className="text-xs mt-2" style={{ color: 'var(--color-text-tertiary)' }}>
            {String(item.source_folder || '')} → {String(item.target_folder || '')}
          </div>
        </div>
      ))}
    </div>
  );
}

function OperationResultCard({
  title,
  summary,
  status,
  chips,
  children,
}: {
  title: string;
  summary: string;
  status: string;
  chips: Array<{ label: string; value: React.ReactNode }>;
  children?: React.ReactNode;
}) {
  return (
    <div
      className="rounded-2xl px-4 py-4"
      style={{
        background: 'var(--color-bg-secondary)',
        border: '1px solid var(--color-border)',
      }}
    >
      <div className="flex items-center gap-3">
        <div className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
          {title}
        </div>
        <Badge value={status} />
      </div>
      <div className="text-sm mt-3" style={{ color: 'var(--color-text)' }}>
        {summary}
      </div>
      <div className="flex flex-wrap gap-2 mt-4">
        {chips.map((chip) => (
          <InfoChip key={chip.label} label={chip.label} value={chip.value} />
        ))}
      </div>
      {children && <div className="mt-4">{children}</div>}
    </div>
  );
}

function ActionSummary({
  title,
  subtitle,
  record,
  labels,
  compact = false,
}: {
  title: string;
  subtitle: string;
  record?: PersonalCockpitRecord | null;
  labels: Array<{ key: string; label: string }>;
  compact?: boolean;
}) {
  const items = Array.isArray(record?.items) ? (record?.items as Array<Record<string, unknown>>) : [];
  const results = Array.isArray(record?.results) ? (record?.results as Array<Record<string, unknown>>) : [];

  return (
    <Section title={title} subtitle={subtitle} icon={Mail}>
      <CompactRecord record={record} labels={labels} />
      {!compact && (
        <div className="mt-4">
          <MailList title="Messages" items={items.length ? items : results} />
        </div>
      )}
    </Section>
  );
}

function ContinuityCard({
  heading,
  summary,
  isLatest = false,
}: {
  heading: string;
  summary: string;
  isLatest?: boolean;
}) {
  return (
    <div
      className="rounded-2xl px-4 py-4"
      style={{
        background: isLatest ? 'color-mix(in srgb, var(--color-accent) 7%, var(--color-bg-secondary))' : 'var(--color-bg-secondary)',
        border: isLatest
          ? '1px solid color-mix(in srgb, var(--color-accent) 24%, transparent)'
          : '1px solid var(--color-border)',
      }}
    >
      <div className="flex items-center gap-2">
        {isLatest && <Badge value="à reprendre" />}
        <div className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
          {heading}
        </div>
      </div>
      <div className="text-sm mt-3" style={{ color: 'var(--color-text-secondary)' }}>
        {summary || '—'}
      </div>
    </div>
  );
}

function SecondaryDetails({
  title,
  subtitle,
  children,
  defaultOpen = false,
  id,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
  id?: string;
}) {
  return (
    <details
      id={id}
      className="hud-panel px-5 py-4 group"
      open={defaultOpen}
    >
      <summary className="list-none cursor-pointer flex items-center gap-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
            {title}
          </div>
          {subtitle && (
            <div className="text-sm mt-1" style={{ color: 'var(--color-text-secondary)' }}>
              {subtitle}
            </div>
          )}
        </div>
        <ChevronDown
          size={16}
          className="ml-auto transition-transform group-open:rotate-180"
          style={{ color: 'var(--color-text-tertiary)' }}
        />
      </summary>
      <div className="mt-4 pt-4" style={{ borderTop: '1px solid var(--color-border-subtle)' }}>
        {children}
      </div>
    </details>
  );
}

function MiniAttentionRow({
  items,
}: {
  items: Array<{ title: string; detail: string; level: 'warning' | 'info' | 'ok' }>;
}) {
  return (
    <div className="grid grid-cols-1 xl:grid-cols-3 gap-2.5">
      {items.map((item) => {
        const tone =
          item.level === 'ok'
            ? toneFromText('ok')
            : item.level === 'info'
            ? toneFromText('warning')
            : toneFromText('error');
        return (
          <div
            key={item.title}
            className="rounded-xl px-3.5 py-3"
            style={{
              background: tone.bg,
              border: `1px solid ${tone.border}`,
            }}
          >
            <div className="text-xs uppercase tracking-[0.14em]" style={{ color: tone.color }}>
              {item.title}
            </div>
            <div className="text-sm mt-1.5" style={{ color: 'var(--color-text)' }}>
              {item.detail}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ActionButton({
  label,
  icon: Icon,
  onClick,
  disabled = false,
}: {
  label: string;
  icon: typeof RefreshCw;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center gap-2 px-3 py-2 rounded-full text-sm cursor-pointer disabled:cursor-not-allowed"
      style={{
        background: disabled ? 'var(--color-bg-tertiary)' : 'var(--color-bg-secondary)',
        border: '1px solid var(--color-border)',
        color: disabled ? 'var(--color-text-tertiary)' : 'var(--color-text)',
        opacity: disabled ? 0.7 : 1,
      }}
    >
      <Icon size={14} />
      {label}
    </button>
  );
}

export function JarvisPersonalPage() {
  const [data, setData] = useState<PersonalCockpitSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = await fetchPersonalCockpit();
      setData(next);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Cockpit indisponible');
    } finally {
      setLoading(false);
    }
  }, []);

  const scrollToId = useCallback((id: string) => {
    const node = document.getElementById(id);
    if (!node) return;
    const details = node.tagName.toLowerCase() === 'details' ? (node as HTMLDetailsElement) : null;
    if (details) details.open = true;
    node.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, []);

  const copyText = useCallback(async (value: string, successLabel: string) => {
    try {
      await navigator.clipboard.writeText(value);
      toast.success(successLabel);
    } catch {
      toast.error('Impossible de copier cette information');
    }
  }, []);

  useEffect(() => {
    refresh();
    let timer: number | null = null;

    const schedule = () => {
      if (timer != null) window.clearTimeout(timer);
      if (document.visibilityState !== 'visible') return;
      timer = window.setTimeout(() => {
        refresh();
        schedule();
      }, 12000);
    };

    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        refresh();
      }
      schedule();
    };

    schedule();
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      if (timer != null) window.clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [refresh]);

  const derived = useMemo(() => {
    if (!data) {
      return {
        attentionCards: [] as Array<{ title: string; detail: string; level: 'warning' | 'info' | 'ok' }>,
        connectorSummary: '',
        continuityLead: '',
        latestOperationalSummary: '',
        nextMove: {
          title: '',
          detail: '',
          actionLabel: '',
          targetId: '',
        },
      };
    }

    const attentionCards: Array<{ title: string; detail: string; level: 'warning' | 'info' | 'ok' }> = [];

    if (data.pending_validation) {
      attentionCards.push({
        title: 'Validation en attente',
        detail: String(data.pending_validation.action || 'Une action réelle attend une validation.'),
        level: 'warning',
      });
    } else {
      attentionCards.push({
        title: 'Aucune validation bloquante',
        detail: 'Aucune action réelle n’attend une confirmation vocale maintenant.',
        level: 'ok',
      });
    }

    if (data.alerts.length > 0) {
      const first = data.alerts[0];
      attentionCards.push({
        title: first.title,
        detail: first.detail,
        level: first.level === 'warning' ? 'warning' : first.level === 'info' ? 'info' : 'warning',
      });
    } else {
      attentionCards.push({
        title: 'Alerte récente',
        detail: 'Aucune alerte notable sur les dernières traces du cockpit.',
        level: 'ok',
      });
    }

    const lastDynamicSummary =
      String(data.yahoo_dynamic_result?.voice_summary || data.yahoo_dynamic_result?.action || '').trim() ||
      'Pas de résultat Yahoo dynamique récent.';
    attentionCards.push({
      title: 'Dernier mouvement Yahoo',
      detail: lastDynamicSummary,
      level: 'info',
    });

    const connectorSummary = data.connectors
      .map((connector) => `${connector.name}: ${connector.status}`)
      .join(' · ');

    const continuityLead = data.continuity[0]?.summary || 'Aucun extrait de continuité récent.';
    const latestOperationalSummary =
      String(
        data.yahoo_dynamic_result?.voice_summary ||
          data.yahoo_targeted_move?.voice_summary ||
          data.last_live_brief?.voice_summary ||
          '',
      ).trim() || 'Aucun résultat opérationnel récent.';

    let nextMove = {
      title: 'Rafraîchir ou relire l’état',
      detail: 'Le cockpit ne voit pas de blocage immédiat. Le geste le plus utile est de vérifier le dernier résultat ou la continuité récente.',
      actionLabel: 'Aller au dernier résultat',
      targetId: 'yahoo-result',
    };

    if (data.pending_validation) {
      nextMove = {
        title: 'Traiter la validation en attente',
        detail: 'Le prochain geste sûr est de relire exactement l’action en attente, puis de décider si Ruth veut répondre vocalement oui ou non.',
        actionLabel: 'Ouvrir la validation',
        targetId: 'pending-validation',
      };
    } else if (data.continuity.length > 0) {
      nextMove = {
        title: 'Reprendre le prochain contexte utile',
        detail: 'Aucun blocage immédiat n’est en attente. Le geste le plus utile est de relire l’artefact de continuité le plus récent avant de reprendre.',
        actionLabel: 'Ouvrir la continuité',
        targetId: 'continuity-details',
      };
    } else if (latestOperationalSummary) {
      nextMove = {
        title: 'Relire le dernier résultat confirmé',
        detail: 'Le geste le plus sûr est de repartir du dernier résultat opérationnel réellement observé par le cockpit.',
        actionLabel: 'Ouvrir le résultat',
        targetId: 'yahoo-result',
      };
    }

    return { attentionCards, connectorSummary, continuityLead, latestOperationalSummary, nextMove };
  }, [data]);

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="hud-panel px-6 py-5 flex items-center gap-3">
          <Loader2 size={18} className="animate-spin" style={{ color: 'var(--color-accent)' }} />
          <span style={{ color: 'var(--color-text)' }}>Chargement du cockpit Jarvis personnel…</span>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex-1 overflow-y-auto px-6 py-10">
        <div className="max-w-5xl mx-auto">
          <Section title="Cockpit indisponible" icon={AlertTriangle}>
            <div className="text-sm" style={{ color: 'var(--color-error)' }}>
              {error || 'Impossible de charger les données du cockpit.'}
            </div>
          </Section>
        </div>
      </div>
    );
  }

  const general = data.general_state;
  const liveSummary = data.last_live_brief;
  const targeted = data.yahoo_targeted_move;
  const candidate = data.yahoo_dynamic_candidate;
  const finalBatch = data.yahoo_dynamic_result;
  const handoffPath = data.file_health.session_handoffs?.path || '';
  const latestYahooSummary = String(finalBatch?.voice_summary || targeted?.voice_summary || '').trim();

  return (
    <div className="flex-1 overflow-y-auto px-6 py-8">
      <div className="max-w-7xl mx-auto space-y-4">
        <header
          className="hud-panel p-6"
          style={{
            background:
              'linear-gradient(135deg, color-mix(in srgb, var(--color-accent) 10%, var(--color-surface)) 0%, var(--color-surface) 48%, color-mix(in srgb, var(--color-accent-purple) 8%, var(--color-surface)) 100%)',
          }}
        >
          <div className="flex flex-col xl:flex-row xl:items-end gap-4">
            <div className="min-w-0">
              <div className="flex items-center gap-2 mb-2">
                <span className="hud-heartbeat" />
                <span className="hud-label uppercase tracking-[0.22em]">Jarvis Personal Cockpit</span>
              </div>
              <h1 className="text-3xl md:text-4xl font-semibold leading-tight" style={{ color: 'var(--color-text)' }}>
                Cockpit personnel Ruth
              </h1>
              <p className="text-sm md:text-base mt-3 max-w-3xl" style={{ color: 'var(--color-text-secondary)' }}>
                Vue locale séparée d’Obsidian, centrée sur l’état Jarvis, la voix, les validations en attente et les mouvements Yahoo réellement suivis.
              </p>
            </div>

            <div className="xl:ml-auto flex flex-col sm:flex-row sm:items-center gap-3">
              <div
                className="rounded-2xl px-4 py-3"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
              >
                <div className="text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--color-text-tertiary)' }}>
                  Dernier snapshot
                </div>
                <div className="text-sm hud-mono mt-1" style={{ color: 'var(--color-text)' }}>
                  {fmtDate(data.meta.generated_at)}
                </div>
              </div>
              <button
                onClick={refresh}
                className="inline-flex items-center justify-center gap-2 px-4 py-3 rounded-2xl cursor-pointer"
                style={{
                  background: 'var(--color-bg-secondary)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text)',
                }}
              >
                <RefreshCw size={15} />
                Rafraîchir
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3 mt-5">
            <SummaryCard
              title="Jarvis"
              value={general.live_status === 'recently_active' ? 'Actif récemment' : general.live_status}
              note={general.status}
              badge={<Badge value={general.live_status || 'idle'} />}
            />
            <SummaryCard
              title="Voix"
              value={data.voice_live.wake_word || 'Jarvis'}
              note={`${data.voice_live.stt} · ${data.voice_live.tts}`}
              badge={<Badge value={data.voice_live.vad || 'n/a'} />}
              accent="var(--color-accent-purple)"
            />
            <SummaryCard
              title="Validation"
              value={data.pending_validation ? 'En attente' : 'Rien à valider'}
              note={
                data.pending_validation
                  ? String(data.pending_validation.action || 'Action réelle en attente')
                  : 'Aucune action réelle bloquée'
              }
              badge={<Badge value={data.pending_validation ? 'pending' : 'ok'} />}
              accent={data.pending_validation ? 'var(--color-warning)' : 'var(--color-success)'}
            />
            <SummaryCard
              title="Dernière activité"
              value={fmtAgo(general.age_seconds)}
              note={`Mémoire courte : ${general.turn_count} tours`}
              badge={<Clock3 size={15} style={{ color: 'var(--color-text-tertiary)' }} />}
              accent="var(--color-accent-amber)"
            />
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-[1.15fr_1fr] gap-3 mt-5">
            <GuidanceCard
              title={derived.nextMove.title}
              detail={derived.nextMove.detail}
              hint="Ce cadrage reste descriptif : aucune action réelle n’est lancée depuis ce panneau."
            />
            <div
              className="rounded-2xl px-4 py-4"
              style={{
                background: 'color-mix(in srgb, var(--color-accent) 8%, var(--color-surface))',
                border: '1px solid color-mix(in srgb, var(--color-accent) 22%, transparent)',
              }}
            >
              <div className="text-xs uppercase tracking-[0.15em]" style={{ color: 'var(--color-text-tertiary)' }}>
                Actions disponibles
              </div>
              <div className="flex flex-wrap gap-2 mt-3">
                <ActionButton
                  label={derived.nextMove.actionLabel}
                  icon={MoveRight}
                  onClick={() => scrollToId(derived.nextMove.targetId)}
                  disabled={!derived.nextMove.targetId}
                />
                <ActionButton label="Rafraîchir l’état" icon={RefreshCw} onClick={refresh} />
                <ActionButton label="Aller à la validation" icon={AlertTriangle} onClick={() => scrollToId('pending-validation')} />
                <ActionButton label="Aller au résultat" icon={Mail} onClick={() => scrollToId('yahoo-result')} />
                <ActionButton label="Aller à la continuité" icon={Clock3} onClick={() => scrollToId('continuity-details')} />
                <ActionButton
                  label="Copier le chemin du handoff"
                  icon={Copy}
                  onClick={() => copyText(handoffPath, 'Chemin du handoff copié')}
                  disabled={!handoffPath}
                />
                <ActionButton
                  label="Copier le résumé Yahoo"
                  icon={Copy}
                  onClick={() => copyText(latestYahooSummary, 'Résumé Yahoo copié')}
                  disabled={!latestYahooSummary}
                />
              </div>
            </div>
          </div>
        </header>

        <Section
          id="attention-now"
          title="Ce Qui Compte Maintenant"
          subtitle="Le signal prioritaire, avant les détails."
          icon={Sparkles}
        >
          <MiniAttentionRow items={derived.attentionCards} />
        </Section>

        <Section
          title="Derniers Échanges Vocaux"
          subtitle="Ce que Ruth vient de dire, puis la dernière réponse utile de Jarvis."
          icon={Mic}
        >
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
            <div>
              <div className="text-xs uppercase tracking-[0.14em] mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
                Dernière transcription
              </div>
              <div
                className="rounded-2xl px-4 py-4 min-h-[112px]"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
              >
                <ExpandableText text={data.latest_transcription} emptyLabel="Aucune transcription récente." maxChars={220} />
              </div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-[0.14em] mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
                Dernière réponse Jarvis
              </div>
              <div
                className="rounded-2xl px-4 py-4 min-h-[112px]"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
              >
                <ExpandableText text={data.latest_response} emptyLabel="Aucune réponse récente." maxChars={220} />
              </div>
            </div>
          </div>
        </Section>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
          <Section
            id="pending-validation"
            title="Validation et état voix"
            subtitle="Le centre de décision immédiat."
            icon={ShieldCheck}
          >
            <div className="mb-4">
              <PendingValidationCard pending={data.pending_validation} />
            </div>

            <div className="space-y-1">
              <MetricRow label="Mode voix" value={<Badge value={general.status || 'unknown'} />} />
              <MetricRow label="Voix live" value={<Badge value={general.live_status || 'idle'} />} />
              <MetricRow label="Wake word" value={data.voice_live.wake_word || 'n/a'} />
              <MetricRow label="Chaîne voix" value={`${data.voice_live.stt || 'n/a'} → ${data.voice_live.tts || 'n/a'}`} />
            </div>
          </Section>

          <Section
            id="alerts-section"
            title="Alertes récentes"
            subtitle="Incidents, validations ou signaux faibles à traiter."
            icon={AlertTriangle}
          >
            <div className="space-y-3">
              {data.alerts.length === 0 && (
                <div className="rounded-2xl px-4 py-4" style={{ background: 'var(--color-bg-secondary)' }}>
                  <div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                    Aucune alerte récente remontée par le cockpit.
                  </div>
                </div>
              )}
              {data.alerts.map((alert, index) => (
                <div key={`${alert.title}-${index}`} className="rounded-2xl px-4 py-4" style={{ background: 'var(--color-bg-secondary)' }}>
                  <div className="flex items-center gap-2">
                    <Badge value={alert.level} />
                    <div className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                      {alert.title}
                    </div>
                  </div>
                  <div className="text-sm mt-2" style={{ color: 'var(--color-text-secondary)' }}>
                    {alert.detail}
                  </div>
                </div>
              ))}
            </div>
          </Section>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-[1.25fr_0.75fr] gap-3">
          <Section
            id="yahoo-result"
            title="Dernier résultat opérationnel"
            subtitle="Ce qui vient réellement de se produire ou de rester en place."
            icon={Mail}
          >
            <OperationResultCard
              title="Synthèse opérationnelle"
              summary={derived.latestOperationalSummary}
              status={finalBatch ? 'yahoo dynamique' : targeted ? 'yahoo ciblé' : 'brief live'}
              chips={[
                {
                  label: 'Messages demandés',
                  value: String(finalBatch?.messages_requested ?? targeted?.messages_requested ?? 'n/a'),
                },
                {
                  label: 'Déplacés maintenant',
                  value: String(finalBatch?.messages_moved_now ?? targeted?.messages_moved_now ?? 'n/a'),
                },
                {
                  label: 'Déjà en cible',
                  value: String(finalBatch?.messages_already_in_target ?? targeted?.messages_already_in_target ?? 'n/a'),
                },
              ]}
            >
              <div className="grid grid-cols-1 gap-3">
                <details className="rounded-xl px-3 py-3" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
                  <summary className="cursor-pointer text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                    Voir le résultat Yahoo dynamique
                  </summary>
                  <div className="mt-3">
                    <CompactRecord
                      record={finalBatch}
                      labels={[
                        { key: 'action', label: 'action' },
                        { key: 'voice_summary', label: 'résumé' },
                        { key: 'messages_requested', label: 'messages demandés' },
                        { key: 'messages_moved_now', label: 'déplacés maintenant' },
                        { key: 'messages_already_in_target', label: 'déjà dans la cible' },
                      ]}
                    />
                    <div className="mt-4">
                      <MailList
                        title="Messages concernés"
                        items={Array.isArray(finalBatch?.results) ? (finalBatch?.results as Array<Record<string, unknown>>) : []}
                      />
                    </div>
                  </div>
                </details>

                <details className="rounded-xl px-3 py-3" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
                  <summary className="cursor-pointer text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                    Voir le résultat Yahoo ciblé
                  </summary>
                  <div className="mt-3">
                    <CompactRecord
                      record={targeted}
                      labels={[
                        { key: 'action', label: 'action' },
                        { key: 'voice_summary', label: 'résumé' },
                        { key: 'messages_requested', label: 'messages demandés' },
                        { key: 'messages_moved_now', label: 'déplacés maintenant' },
                        { key: 'messages_already_in_target', label: 'déjà dans la cible' },
                      ]}
                    />
                  </div>
                </details>
              </div>
            </OperationResultCard>
          </Section>

          <ActionSummary
            title="Dernier brief live"
            subtitle="Contexte multi-source le plus récent."
            record={liveSummary}
            labels={[
              { key: 'action', label: 'action' },
              { key: 'voice_summary', label: 'résumé' },
              { key: 'generated_at', label: 'généré' },
            ]}
            compact
          />
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
          <Section
            title="Historique court de session"
            subtitle="Les derniers échanges utiles sans bruit inutile."
            icon={Mic}
          >
            <div className="space-y-3">
              {data.session_history.length === 0 && (
                <div className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                  Aucun historique de session disponible.
                </div>
              )}
              {data.session_history.map((entry, index) => (
                <div key={`${entry.timestamp}-${index}`} className="rounded-2xl px-4 py-4" style={{ background: 'var(--color-bg-secondary)' }}>
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-xs uppercase tracking-[0.14em]" style={{ color: 'var(--color-text-tertiary)' }}>
                      {entry.intent || 'intent inconnu'}
                    </div>
                    <div className="text-xs hud-mono" style={{ color: 'var(--color-text-tertiary)' }}>
                      {fmtDate(entry.timestamp)}
                    </div>
                  </div>
                  <div className="text-sm mt-3" style={{ color: 'var(--color-text)' }}>
                    <strong>Ruth :</strong> {entry.user || '—'}
                  </div>
                  <div className="text-sm mt-2" style={{ color: 'var(--color-text-secondary)' }}>
                    <strong>Jarvis :</strong> {entry.assistant || '—'}
                  </div>
                </div>
              ))}
            </div>
          </Section>

          <Section
            title="Vue connecteurs"
            subtitle="Résumé rapide avant les détails techniques."
            icon={ShieldCheck}
          >
            <div
              className="rounded-2xl px-4 py-4 mb-4"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <div className="text-xs uppercase tracking-[0.15em]" style={{ color: 'var(--color-text-tertiary)' }}>
                Résumé
              </div>
              <div className="text-sm mt-2" style={{ color: 'var(--color-text)' }}>
                {derived.connectorSummary}
              </div>
            </div>
            <div className="space-y-3">
              {data.connectors.map((connector) => (
                <div key={connector.name} className="rounded-2xl px-4 py-4" style={{ background: 'var(--color-bg-secondary)' }}>
                  <div className="flex items-center justify-between gap-3">
                    <div className="font-semibold" style={{ color: 'var(--color-text)' }}>
                      {connector.name}
                    </div>
                    <Badge value={connector.status || 'unknown'} />
                  </div>
                  <div className="text-xs mt-2" style={{ color: 'var(--color-text-secondary)' }}>
                    Mis à jour : {fmtDate(connector.updated_at)}
                  </div>
                  <div className="flex flex-wrap gap-2 mt-3">
                    {Object.entries(connector.services || {}).map(([name, value]) => (
                      <span
                        key={name}
                        className="px-2.5 py-1 rounded-full text-xs"
                        style={{
                          background: 'var(--color-surface)',
                          border: '1px solid var(--color-border)',
                          color: 'var(--color-text-secondary)',
                        }}
                      >
                        {name}: {value}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </Section>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
          <SecondaryDetails
            title="Yahoo dynamique candidat"
            subtitle="Le batch préparé avant exécution reste visible mais secondaire."
          >
            <CompactRecord
              record={candidate}
              labels={[
                { key: 'action', label: 'action' },
                { key: 'source_name', label: 'source revue' },
                { key: 'batch_size', label: 'taille' },
                { key: 'batch_revision', label: 'révision' },
                { key: 'voice_summary', label: 'résumé' },
              ]}
            />
            <div className="mt-4">
              <MailList
                title="Messages candidats"
                items={Array.isArray(candidate?.items) ? (candidate?.items as Array<Record<string, unknown>>) : []}
              />
            </div>
          </SecondaryDetails>

          <SecondaryDetails
            id="continuity-details"
            title="Continuité récente"
            subtitle={derived.continuityLead}
            defaultOpen
          >
            {data.continuity.length > 0 && (
              <div className="space-y-3">
                <ContinuityCard
                  heading={data.continuity[0].heading}
                  summary={data.continuity[0].summary}
                  isLatest
                />
                {data.continuity.length > 1 && (
                  <details className="rounded-xl px-3 py-3" style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
                    <summary className="cursor-pointer text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                      Voir les autres extraits de continuité
                    </summary>
                    <div className="space-y-3 mt-3">
                      {data.continuity.slice(1).map((entry, index) => (
                        <ContinuityCard
                          key={`${entry.heading}-${index + 1}`}
                          heading={entry.heading}
                          summary={entry.summary}
                        />
                      ))}
                    </div>
                  </details>
                )}
              </div>
            )}
          </SecondaryDetails>

          <SecondaryDetails
            title="Santé des fichiers runtime"
            subtitle="Détails techniques utiles, mais hors du premier regard."
          >
            <div className="space-y-2">
              {Object.entries(data.file_health).map(([name, file]) => (
                <div key={name} className="rounded-xl px-3 py-3" style={{ background: 'var(--color-bg-secondary)' }}>
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                      {name}
                    </div>
                    <Badge value={file.exists ? 'ok' : 'missing'} />
                  </div>
                  <div className="text-xs mt-2 break-all" style={{ color: 'var(--color-text-secondary)' }}>
                    {file.path}
                  </div>
                  <div className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
                    Modifié : {fmtDate(file.modified_at)}
                  </div>
                </div>
              ))}
            </div>
          </SecondaryDetails>
        </div>
      </div>
    </div>
  );
}
