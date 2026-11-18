import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { getMemoryStats } from '../../lib/api';
import { useAppStore } from '../../lib/store';
import type { ActivityEntry, InferenceStats } from '../../hooks/useHudSession';
import type { MicStatus } from '../../hooks/useVoiceActivity';

const MEMORY_POLL_MS = 30000;
const UNKNOWN = '—';

/** Marco común de los paneles: título, etiqueta opcional y contenido. */
export function HudPanel({
  title,
  tag,
  className = '',
  children,
}: {
  title: string;
  tag?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={`hud-panel ${className}`} aria-label={title}>
      <header className="hud-panel-header">
        <span>{title}</span>
        {tag && <span className="hud-panel-tag">{tag}</span>}
      </header>
      <div className="hud-panel-body">{children}</div>
    </section>
  );
}

function Readout({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div className="hud-readout">
      <span className="hud-readout-label">{label}</span>
      <span className="hud-readout-value">
        {value}
        {unit && value !== UNKNOWN && <small>{unit}</small>}
      </span>
    </div>
  );
}

const compactNumber = new Intl.NumberFormat('es', { notation: 'compact', maximumFractionDigits: 1 });
const fixed = (value: number | undefined, digits: number) =>
  value === undefined ? UNKNOWN : value.toFixed(digits);

const MIC_LABELS: Record<MicStatus, string> = {
  off: 'APAGADO',
  starting: 'INICIANDO',
  listening: 'ABIERTO',
  denied: 'SIN PERMISO',
  unsupported: 'NO COMPATIBLE',
};

interface SystemPanelProps {
  model: string;
  stats: InferenceStats;
  micStatus: MicStatus;
  /** Voz activa ("NAVEGADOR · nombre"); vacía si Jarvis solo escribe. */
  voiceOutput: string;
  /** Quién transcribe lo que dice el usuario; vacío si el micrófono está apagado. */
  recognizer: string;
  active: boolean;
}

/** Estado del sistema: modelo, rendimiento de la última inferencia, sesión y voz. */
export function SystemPanel({
  model,
  stats,
  micStatus,
  voiceOutput,
  recognizer,
  active,
}: SystemPanelProps) {
  const serverInfo = useAppStore((s) => s.serverInfo);
  const savings = useAppStore((s) => s.savings);
  const [memoryEntries, setMemoryEntries] = useState<number | undefined>();

  useEffect(() => {
    let cancelled = false;
    const refresh = () =>
      getMemoryStats()
        .then((memory) => !cancelled && setMemoryEntries(memory.entries))
        // Sin memoria configurada el panel simplemente muestra el dato vacío.
        .catch(() => !cancelled && setMemoryEntries(undefined));
    void refresh();
    const timer = setInterval(refresh, MEMORY_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  // Sin GPU ni medidor de energía el servidor reporta 0: se muestra como dato ausente.
  const power = stats.powerW && stats.powerW > 0 ? stats.powerW : undefined;

  return (
    <>
      <HudPanel title="Sistema" tag={serverInfo?.engine?.toUpperCase()}>
        <Readout label="Modelo" value={model || UNKNOWN} />
        <Readout label="Agente" value={serverInfo?.agent ?? UNKNOWN} />
        <Readout label="Latencia" value={fixed(stats.latencyS, 1)} unit="s" />
        <Readout label="Primer token" value={fixed(stats.ttftS, 1)} unit="s" />
        <Readout label="Velocidad" value={fixed(stats.tokensPerSec, 1)} unit="tok/s" />
        <Readout label="Potencia" value={fixed(power, 1)} unit="W" />
      </HudPanel>
      <HudPanel title="Sesión">
        <Readout label="Consultas" value={savings ? String(savings.total_calls) : UNKNOWN} />
        <Readout
          label="Tokens"
          value={savings ? compactNumber.format(savings.total_tokens) : UNKNOWN}
        />
        <Readout
          label="Memoria"
          value={memoryEntries === undefined ? UNKNOWN : String(memoryEntries)}
          unit="recuerdos"
        />
      </HudPanel>
      <HudPanel title="Voz">
        <Readout label="Micrófono" value={MIC_LABELS[micStatus]} />
        <Readout label="Oído" value={recognizer || UNKNOWN} />
        <Readout label="Síntesis" value={!active ? UNKNOWN : voiceOutput || 'SOLO TEXTO'} />
      </HudPanel>
    </>
  );
}

const STATUS_GLYPHS: Record<ActivityEntry['status'], string> = {
  running: '▸',
  ok: '✓',
  error: '✕',
};

const clockTime = new Intl.DateTimeFormat('es', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

/** Registro en vivo de lo que hace el agente, lo más reciente arriba. */
export function ActivityFeed({ entries }: { entries: ActivityEntry[] }) {
  return (
    <HudPanel title="Actividad" tag={entries.length > 0 ? String(entries.length) : undefined} className="hud-activity">
      {entries.length === 0 ? (
        <p className="hud-empty">Sin actividad todavía.</p>
      ) : (
        <ul className="hud-activity-list">
          {entries.map((entry) => (
            <li key={entry.id} className={`hud-activity-item is-${entry.status} is-${entry.kind}`}>
              <span className="hud-activity-glyph" aria-label={entry.status}>
                {STATUS_GLYPHS[entry.status]}
              </span>
              <span className="hud-activity-label">{entry.label}</span>
              <span className="hud-activity-meta">
                {entry.latency !== undefined
                  ? `${entry.latency.toFixed(entry.latency < 1 ? 2 : 1)}s`
                  : clockTime.format(entry.timestamp)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </HudPanel>
  );
}
