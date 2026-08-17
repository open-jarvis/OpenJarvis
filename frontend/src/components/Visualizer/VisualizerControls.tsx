import { useState } from 'react';
import { AudioWaveform, Orbit, ChevronLeft, Settings, Languages } from 'lucide-react';
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select';
import { VOICE_UI_TEXT, panelStatusLabel } from '@/hooks/voiceUiText';
import type { UiLanguage } from '@/hooks/useUiLanguage';
import type { VisualizerSettings, VisualizerTheme, VoiceStatus } from './types';

const STATUS_META: Record<VoiceStatus, { color: string }> = {
  idle:      { color: '#6b7280' },
  listening: { color: '#00e87a' },
  thinking:  { color: '#ffb020' },
  speaking:  { color: '#4facfe' },
};

// ── Constants ────────────────────────────────────────────────────────────────

const THEMES: { key: VisualizerTheme; label: string; gradient: string }[] = [
  { key: 'gold',   label: 'Gold',   gradient: 'linear-gradient(135deg,#ffd700,#ff9500)' },
  { key: 'cyan',   label: 'Cyan',   gradient: 'linear-gradient(135deg,#00f2fe,#4facfe)' },
  { key: 'cyber',  label: 'Cyber',  gradient: 'linear-gradient(135deg,#ff007f,#7f00ff)' },
  { key: 'aurora', label: 'Aurora', gradient: 'linear-gradient(135deg,#00ff87,#60efff)' },
  { key: 'sunset', label: 'Sunset', gradient: 'linear-gradient(135deg,#ff0844,#ffb199)' },
];


// ── Sub-components ────────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[10px] font-semibold tracking-widest uppercase mb-2.5" style={{ color: 'var(--color-text-tertiary)' }}>
      {children}
    </div>
  );
}

function PanelButton({
  active,
  activeRed,
  onClick,
  children,
  className,
}: {
  active?: boolean;
  activeRed?: boolean;
  onClick?: () => void;
  children: React.ReactNode;
  className?: string;
}) {
  const base = 'flex flex-1 items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold transition-all cursor-pointer border';
  const style: React.CSSProperties = active
    ? { background: 'var(--color-accent)', color: 'var(--color-on-accent)', borderColor: 'transparent', boxShadow: '0 0 18px var(--color-accent-glow)' }
    : activeRed
    ? { background: 'linear-gradient(135deg,#ff4060,#ff8c69)', color: '#fff', borderColor: 'transparent', boxShadow: '0 0 18px rgba(255,64,96,.35)' }
    : { background: 'rgba(255,255,255,.05)', color: 'var(--color-text)', borderColor: 'var(--color-border)' };
  return (
    <button
      onClick={onClick}
      className={`${base}${className ? ` ${className}` : ''}`}
      style={style}
      onMouseEnter={(e) => { if (!active && !activeRed) e.currentTarget.style.background = 'rgba(255,255,255,.1)'; }}
      onMouseLeave={(e) => { if (!active && !activeRed) e.currentTarget.style.background = 'rgba(255,255,255,.05)'; }}
    >
      {children}
    </button>
  );
}

function Slider({
  label, value, min, max, step = 1,
  format, onChange,
}: {
  label: string;
  value: number;
  min: number; max: number; step?: number;
  format: (v: number) => string;
  onChange: (v: number) => void;
}) {
  return (
    <div className="mb-2.5">
      <div className="flex justify-between text-[11px] mb-1.5" style={{ color: 'var(--color-text-secondary)' }}>
        <span>{label}</span>
        <span style={{ color: 'var(--color-text)', fontWeight: 600 }}>{format(value)}</span>
      </div>
      <input
        type="range"
        min={min} max={max} step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full h-1 rounded-full outline-none cursor-pointer appearance-none"
        style={{ background: `linear-gradient(to right, var(--color-accent) ${((value - min) / (max - min)) * 100}%, var(--color-border) 0%)` }}
      />
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface Props {
  settings: VisualizerSettings;
  onSettingsChange: (s: VisualizerSettings) => void;
  status: VoiceStatus;
  uiLanguage: UiLanguage;
  onUiLanguageChange: (language: UiLanguage) => void;
}

export function VisualizerControls({ settings, onSettingsChange, status, uiLanguage, onUiLanguageChange }: Props) {
  const [collapsed, setCollapsed] = useState(true);

  const set = <K extends keyof VisualizerSettings>(key: K, val: VisualizerSettings[K]) =>
    onSettingsChange({ ...settings, [key]: val });

  const panelStyle: React.CSSProperties = {
    background: 'rgba(10,10,22,0.84)',
    border: '1px solid var(--color-border)',
    backdropFilter: 'blur(28px)',
    WebkitBackdropFilter: 'blur(28px)',
    boxShadow: '0 24px 56px rgba(0,0,0,.65)',
    color: 'var(--color-text)',
  };

  if (collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        className="absolute bottom-6 left-4 z-20 w-10 h-10 rounded-xl flex items-center justify-center transition-all cursor-pointer hover:scale-110"
        style={{ background: 'none', border: 'none', boxShadow: 'none', backdropFilter: 'none', WebkitBackdropFilter: 'none' }}
        title="Open panel"
      >
        <Settings size={16} style={{ color: 'var(--color-text)' }} />
      </button>
    );
  }

  return (
    // top-[54px] lines the panel's top edge up with the sidebar's model badge
    // (sidebar header is 54px tall). Also clears the floating sidebar-toggle
    // button (fixed top-3 left-3, ~46px tall) shown when the sidebar collapses.
    <aside
      className="absolute top-[54px] left-4 z-20 w-72 rounded-2xl flex flex-col gap-4 p-5 overflow-y-auto"
      style={{ ...panelStyle, maxHeight: 'calc(100vh - 70px)' }}
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div
          className="text-base font-bold tracking-tight"
          style={{ background: 'linear-gradient(120deg,var(--color-accent),var(--color-text) 80%)', WebkitBackgroundClip: 'text', backgroundClip: 'text', WebkitTextFillColor: 'transparent' }}
        >
          AI Voice Visualizer
        </div>
        <button
          onClick={() => setCollapsed(true)}
          className="flex items-center gap-1 text-[11px] cursor-pointer transition-colors"
          style={{ background: 'none', border: 'none', color: 'var(--color-text-secondary)' }}
          onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--color-text)')}
          onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--color-text-secondary)')}
        >
          Hide <ChevronLeft size={13} />
        </button>
      </div>

      {/* Voice status */}
      <div className="pb-4" style={{ borderBottom: '1px solid rgba(255,255,255,.06)' }}>
        <SectionLabel>Voice</SectionLabel>
        <div
          className="inline-flex items-center gap-1.5 text-[11px] font-semibold tracking-wider px-2.5 py-1.5 rounded-full"
          style={{ background: 'rgba(255,255,255,.05)' }}
        >
          <span
            className="w-2 h-2 rounded-full"
            style={{
              background: STATUS_META[status].color,
              animation: status === 'listening' || status === 'speaking' ? 'pulse 1.6s ease-in-out infinite' : 'none',
            }}
          />
          {panelStatusLabel(uiLanguage, status)}
        </div>
        <p className="text-[11px] mt-2 leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
          Voice starts automatically after the kiosk greeting.
        </p>
      </div>

      {/* Language */}
      <div className="pb-4" style={{ borderBottom: '1px solid rgba(255,255,255,.06)' }}>
        <SectionLabel>Language</SectionLabel>
        <div className="mt-2">
          <Select
            value={uiLanguage}
            onValueChange={(val) => {
              if (val === 'vi' || val === 'en') onUiLanguageChange(val);
            }}
          >
            <SelectTrigger className="w-full h-9 rounded-lg" style={{ background: 'rgba(255,255,255,.05)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
              <SelectValue placeholder="Language" />
            </SelectTrigger>
            <SelectContent
              className="border border-white/10 rounded-lg overflow-hidden backdrop-blur-xl"
              style={{ background: 'rgba(20,20,32,0.95)', color: 'var(--color-text)' }}
            >
              <SelectItem value="vi" className="cursor-pointer focus:bg-white/10 focus:text-white transition-colors">
                <span className="flex items-center gap-2">🇻🇳 {VOICE_UI_TEXT[uiLanguage].language.vietnamese}</span>
              </SelectItem>
              <SelectItem value="en" className="cursor-pointer focus:bg-white/10 focus:text-white transition-colors">
                <span className="flex items-center gap-2">🇺🇸 {VOICE_UI_TEXT[uiLanguage].language.english}</span>
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
        <p className="text-[11px] mt-2 leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
          {VOICE_UI_TEXT[uiLanguage].languageHelper}
        </p>
      </div>

      {/* Visual style */}
      <div className="pb-4" style={{ borderBottom: '1px solid rgba(255,255,255,.06)' }}>
        <SectionLabel>Display Mode</SectionLabel>
        <div className="flex gap-2">
          <PanelButton active={settings.style === 'wave'} onClick={() => set('style', 'wave')}>
            <AudioWaveform size={13} /> Wave
          </PanelButton>
          <PanelButton active={settings.style === '3d'} onClick={() => set('style', '3d')}>
            <Orbit size={13} /> 3D Sphere
          </PanelButton>
        </div>
        <p className="text-[11px] mt-2 leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
          {settings.style === '3d'
            ? '3D neon sphere reacts to bass & treble.'
            : 'Liquid neon wave ring oscillates with audio.'}
        </p>
      </div>

      {/* Customise */}
      <div className="pb-4" style={{ borderBottom: '1px solid rgba(255,255,255,.06)' }}>
        <SectionLabel>Customize</SectionLabel>

        <div className="flex items-center justify-between mb-4">
          <span className="text-[11px]" style={{ color: 'var(--color-text-secondary)' }}>Show Captions</span>
          <button
            onClick={() => set('showCaptions', !settings.showCaptions)}
            className="relative inline-flex h-5 w-9 items-center rounded-full transition-colors cursor-pointer border-none outline-none"
            style={{ background: settings.showCaptions ? 'var(--color-accent)' : 'rgba(255,255,255,.1)' }}
          >
            <span
              className="inline-block h-4 w-4 transform rounded-full bg-white transition-transform"
              style={{ transform: settings.showCaptions ? 'translateX(18px)' : 'translateX(2px)' }}
            />
          </button>
        </div>

        <div className="flex items-center justify-between mb-4">
          <span className="text-[11px]" style={{ color: 'var(--color-text-secondary)' }}>Show Status Overlay</span>
          <button
            onClick={() => set('showOverlay', !settings.showOverlay)}
            className="relative inline-flex h-5 w-9 items-center rounded-full transition-colors cursor-pointer border-none outline-none"
            style={{ background: settings.showOverlay ? 'var(--color-accent)' : 'rgba(255,255,255,.1)' }}
          >
            <span
              className="inline-block h-4 w-4 transform rounded-full bg-white transition-transform"
              style={{ transform: settings.showOverlay ? 'translateX(18px)' : 'translateX(2px)' }}
            />
          </button>
        </div>
        {/* Theme palette */}
        <div className="mb-3">
          <div className="text-[11px] mb-2" style={{ color: 'var(--color-text-secondary)' }}>Theme</div>
          <div className="flex gap-2">
            {THEMES.map((t) => (
              <button
                key={t.key}
                title={t.label}
                onClick={() => set('theme', t.key)}
                className="w-6 h-6 rounded-full cursor-pointer transition-transform"
                style={{
                  background: t.gradient,
                  border: 'none',
                  opacity: settings.theme === t.key ? 1 : 0.38,
                  transform: settings.theme === t.key ? 'scale(1.2)' : 'scale(1)',
                }}
              />
            ))}
          </div>
        </div>

        <Slider label="Size"  value={settings.size}  min={70}  max={230} format={(v) => `${Math.round(v)}px`} onChange={(v) => set('size', v)} />
        <Slider label="Gain"  value={settings.gain}  min={0.2} max={4}   step={0.1} format={(v) => `${v.toFixed(1)}x`} onChange={(v) => set('gain', v)} />
        <Slider label="Speed" value={settings.speed} min={0.1} max={3.5} step={0.1} format={(v) => `${v.toFixed(1)}x`} onChange={(v) => set('speed', v)} />
        <Slider label="Glow"  value={settings.glow}  min={0}   max={50}  format={(v) => `${Math.round(v)}px`} onChange={(v) => set('glow', v)} />

      </div>

    </aside>
  );
}
