import { useState } from 'react';
import { ScreenShare, AudioLines, Settings, X } from 'lucide-react';
import { VOICE_UI_TEXT } from '@/hooks/voiceUiText';
import type { UiLanguage } from '@/hooks/useUiLanguage';
import type { VisualizerSettings, VisualizerStyle, VisualizerTheme, VoiceStatus } from './types';

// ── Constants ────────────────────────────────────────────────────────────────

const THEMES: { key: VisualizerTheme; label: string; gradient: string }[] = [
  { key: 'gold',   label: 'Gold',   gradient: 'linear-gradient(135deg,#ffd700,#ff9500)' },
  { key: 'cyan',   label: 'Cyan',   gradient: 'linear-gradient(135deg,#00f2fe,#4facfe)' },
  { key: 'cyber',  label: 'Cyber',  gradient: 'linear-gradient(135deg,#ff007f,#7f00ff)' },
  { key: 'aurora', label: 'Aurora', gradient: 'linear-gradient(135deg,#00ff87,#60efff)' },
  { key: 'sunset', label: 'Sunset', gradient: 'linear-gradient(135deg,#ff0844,#ffb199)' },
];

const displayOptions: { value: VisualizerStyle; label: string; icon: typeof ScreenShare }[] = [
  { value: 'screen', label: 'Screen Share', icon: ScreenShare },
  { value: '3d', label: '3D Sphere', icon: AudioLines },
];

// ── Card & Row Components (matching SettingsPage card template) ─────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div
      className="rounded-xl p-3.5 sm:p-4 flex flex-col"
      style={{
        background: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
      }}
    >
      <h3 className="text-xs sm:text-sm font-semibold mb-1" style={{ color: 'var(--color-text)' }}>
        {title}
      </h3>
      <div className="flex flex-col">
        {children}
      </div>
    </div>
  );
}

function SettingRow({
  label,
  description,
  children,
  last = false,
  vertical = false,
}: {
  label: string;
  description?: React.ReactNode;
  children: React.ReactNode;
  last?: boolean;
  vertical?: boolean;
}) {
  if (vertical) {
    return (
      <div
        className="py-2.5 flex flex-col gap-2"
        style={{ borderBottom: last ? 'none' : '1px solid var(--color-border-subtle)' }}
      >
        <div>
          <div className="text-xs sm:text-sm font-medium leading-snug" style={{ color: 'var(--color-text)' }}>
            {label}
          </div>
          {description && (
            <div className="text-[11px] mt-0.5 leading-normal" style={{ color: 'var(--color-text-tertiary)' }}>
              {description}
            </div>
          )}
        </div>
        <div>{children}</div>
      </div>
    );
  }

  return (
    <div
      className="flex items-center justify-between py-2.5 gap-3"
      style={{ borderBottom: last ? 'none' : '1px solid var(--color-border-subtle)' }}
    >
      <div className="min-w-0 flex-1">
        <div className="text-xs sm:text-sm font-medium leading-snug" style={{ color: 'var(--color-text)' }}>
          {label}
        </div>
        {description && (
          <div className="text-[11px] mt-0.5 leading-normal" style={{ color: 'var(--color-text-tertiary)' }}>
            {description}
          </div>
        )}
      </div>
      <div className="shrink-0 flex items-center">
        {children}
      </div>
    </div>
  );
}

function SettingToggle({
  checked,
  onChange,
  ariaLabel,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  ariaLabel?: string;
}) {
  return (
    <button
      onClick={() => onChange(!checked)}
      className="relative w-11 h-6 rounded-full transition-colors cursor-pointer shrink-0 border-none outline-none"
      style={{
        background: checked ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
      }}
      aria-label={ariaLabel}
    >
      <span
        className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full transition-transform bg-white"
        style={{
          transform: checked ? 'translateX(20px)' : 'translateX(0)',
          boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
        }}
      />
    </button>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface Props {
  settings: VisualizerSettings;
  onSettingsChange: (s: VisualizerSettings) => void;
  status: VoiceStatus;
  uiLanguage: UiLanguage;
  onUiLanguageChange: (language: UiLanguage) => void;
  initialCollapsed?: boolean;
}

export function VisualizerControls({
  settings,
  onSettingsChange,
  status: _status,
  uiLanguage,
  onUiLanguageChange,
  initialCollapsed = true,
}: Props) {
  const [collapsed, setCollapsed] = useState(initialCollapsed);

  const set = <K extends keyof VisualizerSettings>(key: K, val: VisualizerSettings[K]) =>
    onSettingsChange({ ...settings, [key]: val });

  const panelStyle: React.CSSProperties = {
    background: 'var(--color-bg)',
    border: '1px solid var(--color-border)',
    boxShadow: '0 24px 56px rgba(0,0,0,.22)',
    color: 'var(--color-text)',
  };

  if (collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        className="absolute bottom-6 left-4 z-20 w-9 h-9 flex items-center justify-center transition-all cursor-pointer hover:scale-110 opacity-70 hover:opacity-100"
        style={{
          background: 'none',
          border: 'none',
          boxShadow: 'none',
        }}
        title="Open panel"
        aria-label="Open AI Voice Visualizer controls"
      >
        <Settings size={20} style={{ color: 'var(--color-text-secondary)' }} />
      </button>
    );
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 dark:bg-black/60 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) setCollapsed(true);
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="voice-visualizer-title"
        className="relative w-full max-w-lg max-h-[88vh] rounded-2xl flex flex-col gap-3.5 p-5 overflow-y-auto shadow-2xl"
        style={panelStyle}
      >
        {/* Header */}
        <div className="flex items-center justify-between pb-1">
          <div
            id="voice-visualizer-title"
            className="text-base font-bold tracking-tight"
            style={{
              background: 'linear-gradient(120deg,var(--color-accent),var(--color-text) 80%)',
              WebkitBackgroundClip: 'text',
              backgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
            }}
          >
            AI Voice Visualizer
          </div>
          <button
            onClick={() => setCollapsed(true)}
            className="w-8 h-8 rounded-lg flex items-center justify-center transition-colors cursor-pointer hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text)]"
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--color-text-secondary)',
            }}
            title="Close"
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

      {/* Card 1: Language */}
      <Section title="Language">
        <SettingRow
          label="Language"
          description={VOICE_UI_TEXT[uiLanguage].languageHelper}
          last
        >
          <select
            value={uiLanguage}
            onChange={(e) => {
              const val = e.target.value;
              if (val === 'vi' || val === 'en') onUiLanguageChange(val);
            }}
            className="text-sm px-3 py-1.5 rounded-lg outline-none cursor-pointer"
            style={{
              background: 'var(--color-bg-secondary)',
              color: 'var(--color-text)',
              border: '1px solid var(--color-border)',
            }}
          >
            <option value="vi">{VOICE_UI_TEXT[uiLanguage].language.vietnamese}</option>
            <option value="en">{VOICE_UI_TEXT[uiLanguage].language.english}</option>
          </select>
        </SettingRow>
      </Section>

      {/* Card 2: Visualizer & Display */}
      <Section title="Visualizer & Display">
        <SettingRow
          label="Display mode"
          description={
            settings.style === '3d'
              ? '3D neon sphere reacts to audio'
              : 'Center screen share display'
          }
        >
          <div className="flex gap-1 p-0.5 rounded-lg shrink-0" style={{ background: 'var(--color-bg-secondary)' }}>
            {displayOptions.map((opt) => {
              const isActive = settings.style === opt.value;
              return (
                <button
                  key={opt.value}
                  onClick={() => set('style', opt.value)}
                  className="flex items-center gap-1.5 px-2.5 sm:px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer"
                  style={{
                    background: isActive ? 'var(--color-surface)' : 'transparent',
                    color: isActive ? 'var(--color-text)' : 'var(--color-text-tertiary)',
                    boxShadow: isActive ? 'var(--shadow-sm)' : 'none',
                  }}
                >
                  <opt.icon size={13} />
                  {opt.label}
                </button>
              );
            })}
          </div>
        </SettingRow>

        <SettingRow
          label="Theme"
          description={THEMES.find((t) => t.key === settings.theme)?.label ?? 'Theme'}
        >
          <div className="flex items-center gap-2">
            {THEMES.map((t) => {
              const isSelected = settings.theme === t.key;
              return (
                <button
                  key={t.key}
                  title={t.label}
                  onClick={() => set('theme', t.key)}
                  className="w-5 h-5 rounded-full cursor-pointer transition-transform"
                  style={{
                    background: t.gradient,
                    border: 'none',
                    opacity: isSelected ? 1 : 0.4,
                    transform: isSelected ? 'scale(1.3)' : 'scale(1)',
                  }}
                />
              );
            })}
          </div>
        </SettingRow>

        <SettingRow label="Size" description={`${Math.round(settings.size)}px`}>
          <input
            type="range"
            min={70}
            max={230}
            step={1}
            value={settings.size}
            onChange={(e) => set('size', parseFloat(e.target.value))}
            className="w-28 sm:w-32 cursor-pointer accent-[var(--color-accent)]"
            style={{ accentColor: 'var(--color-accent)' }}
          />
        </SettingRow>

        <SettingRow label="Gain" description={`${settings.gain.toFixed(1)}x`}>
          <input
            type="range"
            min={0.2}
            max={4}
            step={0.1}
            value={settings.gain}
            onChange={(e) => set('gain', parseFloat(e.target.value))}
            className="w-28 sm:w-32 cursor-pointer accent-[var(--color-accent)]"
            style={{ accentColor: 'var(--color-accent)' }}
          />
        </SettingRow>

        <SettingRow label="Speed" description={`${settings.speed.toFixed(1)}x`}>
          <input
            type="range"
            min={0.1}
            max={3.5}
            step={0.1}
            value={settings.speed}
            onChange={(e) => set('speed', parseFloat(e.target.value))}
            className="w-28 sm:w-32 cursor-pointer accent-[var(--color-accent)]"
            style={{ accentColor: 'var(--color-accent)' }}
          />
        </SettingRow>

        <SettingRow label="Glow" description={`${Math.round(settings.glow)}px`} last>
          <input
            type="range"
            min={0}
            max={50}
            step={1}
            value={settings.glow}
            onChange={(e) => set('glow', parseFloat(e.target.value))}
            className="w-28 sm:w-32 cursor-pointer accent-[var(--color-accent)]"
            style={{ accentColor: 'var(--color-accent)' }}
          />
        </SettingRow>
      </Section>

      {/* Card 3: Mascot & Captions */}
      <Section title="Mascot & Captions">
        <SettingRow
          label="Show Captions"
          description="Display live speech transcription"
        >
          <SettingToggle
            checked={settings.showCaptions}
            onChange={(val) => set('showCaptions', val)}
            ariaLabel="Toggle Show Captions"
          />
        </SettingRow>

        <SettingRow
          label="Show Mascot"
          description="Floating Codex Pet companion on kiosk"
        >
          <SettingToggle
            checked={settings.showPet}
            onChange={(val) => set('showPet', val)}
            ariaLabel="Toggle Show Mascot"
          />
        </SettingRow>

        <SettingRow
          label="Pet Size"
          description={`${settings.petScale.toFixed(1)}x`}
          last
        >
          <input
            type="range"
            min={1}
            max={4}
            step={0.1}
            value={settings.petScale}
            onChange={(e) => set('petScale', parseFloat(e.target.value))}
            className="w-28 sm:w-32 cursor-pointer accent-[var(--color-accent)]"
            style={{ accentColor: 'var(--color-accent)' }}
          />
        </SettingRow>
      </Section>
      </div>
    </div>
  );
}
