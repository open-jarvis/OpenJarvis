import { useState, useEffect } from 'react';
import {
  Palette,
  Globe,
  Cpu,
  Database,
  Info,
  Check,
  Sun,
  Moon,
  Monitor,
  Download,
  Upload,
  Trash2,
  Mic,
  Key,
  Search,
  Brain,
  Trophy,
  Volume2,
} from 'lucide-react';
import {
  useAppStore,
  type NavigationMode,
  type SpeechInputMode,
  type ThemeMode,
  type TtsMode,
} from '../lib/store';
import { checkHealth, getMemoryStats, speakVoice } from '../lib/api';
import { locationErrorMessage, requestCurrentLocation } from '../lib/location';

function OllamaModelList() {
  const [models, setModels] = useState<Array<{ name: string; size: number }>>([]);
  useEffect(() => {
    fetch('http://localhost:11434/api/tags')
      .then(r => r.json())
      .then(data => setModels((data.models || []).map((m: any) => ({ name: m.name, size: m.size }))))
      .catch(() => setModels([]));
  }, []);
  if (models.length === 0) return <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>No models loaded</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {models.map(m => (
        <span key={m.name} className="flex items-center gap-1 px-2 py-0.5 rounded text-[10px]"
          style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text)' }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--color-success)', display: 'inline-block' }} />
          {m.name} ({(m.size / 1e9).toFixed(1)} GB)
        </span>
      ))}
    </div>
  );
}

function ApiKeyInput({ storageKey, placeholder }: { storageKey: string; placeholder: string }) {
  const [value, setValue] = useState(() => {
    try { return localStorage.getItem(storageKey) || ''; } catch { return ''; }
  });
  const [saved, setSaved] = useState(false);
  const save = (v: string) => {
    setValue(v);
    try { if (v) localStorage.setItem(storageKey, v); else localStorage.removeItem(storageKey); } catch {}
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };
  return (
    <div className="flex items-center gap-2">
      <input type="password" value={value} onChange={e => save(e.target.value)} placeholder={placeholder}
        className="w-48 px-2 py-1 rounded text-xs"
        style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
      {saved && <span className="text-[10px]" style={{ color: 'var(--color-success)' }}>Saved</span>}
    </div>
  );
}

function CloudProviderStatus({ label, storageKey }: { label: string; storageKey: string }) {
  const [hasKey, setHasKey] = useState(false);
  useEffect(() => {
    try { setHasKey(!!localStorage.getItem(storageKey)); } catch { setHasKey(false); }
  }, [storageKey]);
  return (
    <span className="flex items-center gap-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
      <span style={{
        width: 6, height: 6, borderRadius: '50%', display: 'inline-block',
        background: hasKey ? 'var(--color-success)' : 'var(--color-text-tertiary)',
      }} />
      {label}
    </span>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div
      className="quiet-panel rounded-lg p-5"
    >
      <h3 className="text-xs font-semibold uppercase mb-4" style={{ color: 'var(--color-text-secondary)' }}>
        {title}
      </h3>
      {children}
    </div>
  );
}

function SettingRow({ label, description, children }: { label: string; description?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-3" style={{ borderBottom: '1px solid var(--color-border-subtle)' }}>
      <div className="min-w-0">
        <div className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>{label}</div>
        {description && (
          <div className="text-xs mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>{description}</div>
        )}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

const themeOptions: { value: ThemeMode; label: string; icon: typeof Sun }[] = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
];

const ttsModeOptions: { value: TtsMode; label: string }[] = [
  { value: 'macos_say', label: 'macOS say' },
  { value: 'browser_speech_synthesis', label: 'Browser speechSynthesis' },
  { value: 'gemini_tts', label: 'Gemini 2.5 Flash TTS' },
  { value: 'edge_tts', label: 'Edge TTS' },
  { value: 'elevenlabs', label: 'ElevenLabs' },
  { value: 'piper', label: 'Piper' },
  { value: 'disabled', label: 'Disabled' },
];

const speechInputModeOptions: { value: SpeechInputMode; label: string }[] = [
  { value: 'free_web_speech', label: 'Free Web Speech' },
  { value: 'auto', label: 'Auto fallback' },
  { value: 'local_stt', label: 'Local STT upload' },
];

const geminiVoiceOptions = [
  { value: 'Sulafat', label: 'Sulafat · Warm' },
  { value: 'Achird', label: 'Achird · Friendly' },
  { value: 'Vindemiatrix', label: 'Vindemiatrix · Gentle' },
  { value: 'Achernar', label: 'Achernar · Soft' },
  { value: 'Aoede', label: 'Aoede · Breezy' },
  { value: 'Puck', label: 'Puck · Upbeat' },
  { value: 'Kore', label: 'Kore · Firm' },
  { value: 'Iapetus', label: 'Iapetus · Clear' },
  { value: 'Zephyr', label: 'Zephyr · Bright' },
  { value: 'Charon', label: 'Charon · Informative' },
  { value: 'Fenrir', label: 'Fenrir · Excitable' },
  { value: 'Leda', label: 'Leda · Youthful' },
  { value: 'Orus', label: 'Orus · Firm' },
  { value: 'Callirrhoe', label: 'Callirrhoe · Easy-going' },
  { value: 'Autonoe', label: 'Autonoe · Bright' },
  { value: 'Enceladus', label: 'Enceladus · Breathy' },
  { value: 'Umbriel', label: 'Umbriel · Easy-going' },
  { value: 'Algieba', label: 'Algieba · Smooth' },
  { value: 'Despina', label: 'Despina · Smooth' },
  { value: 'Erinome', label: 'Erinome · Clear' },
  { value: 'Algenib', label: 'Algenib · Gravelly' },
  { value: 'Rasalgethi', label: 'Rasalgethi · Informative' },
  { value: 'Laomedeia', label: 'Laomedeia · Upbeat' },
  { value: 'Alnilam', label: 'Alnilam · Firm' },
  { value: 'Schedar', label: 'Schedar · Even' },
  { value: 'Gacrux', label: 'Gacrux · Mature' },
  { value: 'Pulcherrima', label: 'Pulcherrima · Forward' },
  { value: 'Zubenelgenubi', label: 'Zubenelgenubi · Casual' },
  { value: 'Sadachbia', label: 'Sadachbia · Lively' },
  { value: 'Sadaltager', label: 'Sadaltager · Knowledgeable' },
];

const edgeVoiceOptions = [
  { value: 'ko-KR-SunHiNeural', label: 'SunHi · Korean female' },
  { value: 'ko-KR-InJoonNeural', label: 'InJoon · Korean male' },
  { value: 'en-US-JennyNeural', label: 'Jenny · English female' },
  { value: 'en-US-GuyNeural', label: 'Guy · English male' },
  { value: 'ja-JP-NanamiNeural', label: 'Nanami · Japanese female' },
  { value: 'zh-CN-XiaoxiaoNeural', label: 'Xiaoxiao · Chinese female' },
];

export function SettingsPage() {
  const settings = useAppStore((s) => s.settings);
  const updateSettings = useAppStore((s) => s.updateSettings);
  const currentLocation = useAppStore((s) => s.currentLocation);
  const locationStatus = useAppStore((s) => s.locationStatus);
  const setCurrentLocation = useAppStore((s) => s.setCurrentLocation);
  const setLocationStatus = useAppStore((s) => s.setLocationStatus);
  const conversations = useAppStore((s) => s.conversations);
  const serverInfo = useAppStore((s) => s.serverInfo);
  const optInEnabled = useAppStore((s) => s.optInEnabled);
  const setOptInModalOpen = useAppStore((s) => s.setOptInModalOpen);
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [browserSpeechAvailable, setBrowserSpeechAvailable] = useState<boolean | null>(null);
  const [saved, setSaved] = useState(false);
  const [ttsSampleStatus, setTtsSampleStatus] = useState('');
  const [locationRequesting, setLocationRequesting] = useState(false);

  const [memoryStats, setMemoryStats] = useState<{ entries: number; backend: string } | null>(null);
  const [memoryEnabled, setMemoryEnabled] = useState(() => {
    try { return localStorage.getItem('openjarvis-memory-enabled') !== 'false'; } catch { return true; }
  });
  const [memoryBackend, setMemoryBackend] = useState(() => {
    try { return localStorage.getItem('openjarvis-memory-backend') || 'sqlite'; } catch { return 'sqlite'; }
  });
  const [memoryTopK, setMemoryTopK] = useState(() => {
    try { return parseInt(localStorage.getItem('openjarvis-memory-top-k') || '5'); } catch { return 5; }
  });
  const [memoryMinScore, setMemoryMinScore] = useState(() => {
    try { return parseFloat(localStorage.getItem('openjarvis-memory-min-score') || '0.1'); } catch { return 0.1; }
  });
  const [memoryMaxTokens, setMemoryMaxTokens] = useState(() => {
    try { return parseInt(localStorage.getItem('openjarvis-memory-max-tokens') || '2048'); } catch { return 2048; }
  });

  useEffect(() => {
    checkHealth().then(setHealthy);
    setBrowserSpeechAvailable(Boolean(window.SpeechRecognition || window.webkitSpeechRecognition));
    getMemoryStats()
      .then(setMemoryStats)
      .catch(() => setMemoryStats(null));
  }, []);

  const showSaved = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  };

  const requestLocationNow = async () => {
    updateSettings({ locationAlwaysOn: true });
    setLocationRequesting(true);
    setLocationStatus('위치 권한 확인 중');
    try {
      const location = await requestCurrentLocation();
      setCurrentLocation(location);
      setLocationStatus('현재 위치 사용 중');
      showSaved();
    } catch (err) {
      setCurrentLocation(null);
      setLocationStatus(locationErrorMessage(err));
    } finally {
      setLocationRequesting(false);
    }
  };

  const applyManualLocation = () => {
    const latitude = Number.parseFloat(settings.manualLatitude);
    const longitude = Number.parseFloat(settings.manualLongitude);
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
      setCurrentLocation(null);
      setLocationStatus('수동 위치 좌표를 확인해주세요');
      return;
    }
    setCurrentLocation({
      latitude,
      longitude,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Seoul',
    });
    updateSettings({ locationAlwaysOn: true });
    setLocationStatus(`${settings.manualLocationName || '수동 위치'} 사용 중`);
    showSaved();
  };

  const playGeminiVoiceSample = async () => {
    const key = settings.geminiApiKey.trim();
    if (!key) {
      setTtsSampleStatus('Gemini API key required');
      return;
    }
    setTtsSampleStatus('Playing sample...');
    try {
      const result = await speakVoice({
        text: '안녕하세요. 저는 프라이데이예요. 이렇게 자연스러운 목소리로 답변드릴게요.',
        mode: 'gemini_tts',
        voice: settings.ttsVoice || 'Yuna',
        gemini_api_key: key,
        gemini_voice: settings.geminiVoice || 'Sulafat',
        max_chars: 180,
        naturalize: true,
      });
      setTtsSampleStatus(result.ok ? 'Sample playing' : result.message || 'Sample failed');
    } catch {
      setTtsSampleStatus('Sample failed');
    }
  };

  const playEdgeVoiceSample = async () => {
    setTtsSampleStatus('Playing Edge sample...');
    try {
      const result = await speakVoice({
        text: '안녕하세요. 엣지 티티에스 목소리 샘플입니다.',
        mode: 'edge_tts',
        edge_voice: settings.edgeVoice || 'ko-KR-SunHiNeural',
        rate: settings.ttsRate || 165,
        max_chars: 180,
        naturalize: true,
      });
      setTtsSampleStatus(
        result.ok ? 'Edge sample playing' : result.message || 'Edge sample failed',
      );
    } catch {
      setTtsSampleStatus('Edge sample failed');
    }
  };

  const handleExport = () => {
    const data = localStorage.getItem('openjarvis-conversations') || '{}';
    const blob = new Blob([data], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `openjarvis-export-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleImport = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (ev) => {
        try {
          const data = JSON.parse(ev.target?.result as string);
          if (data.version === 1) {
            localStorage.setItem('openjarvis-conversations', JSON.stringify(data));
            useAppStore.getState().loadConversations();
            showSaved();
          }
        } catch {}
      };
      reader.readAsText(file);
    };
    input.click();
  };

  const [confirmClear, setConfirmClear] = useState(false);
  const handleClear = () => {
    if (!confirmClear) {
      setConfirmClear(true);
      setTimeout(() => setConfirmClear(false), 3000);
      return;
    }
    localStorage.removeItem('openjarvis-conversations');
    useAppStore.getState().loadConversations();
    setConfirmClear(false);
    showSaved();
  };

  return (
    <div className="flex-1 overflow-y-auto px-6 py-10">
      <div className="max-w-2xl mx-auto">
        <header className="mb-6">
          <div className="flex items-center justify-between gap-3">
            <h1 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>
              Settings
            </h1>
            {saved && (
              <span className="flex items-center gap-1 text-xs px-2 py-1 rounded-full" style={{
                background: 'var(--color-accent-subtle)',
                color: 'var(--color-success)',
              }}>
                <Check size={12} /> Saved
              </span>
            )}
          </div>
          <p className="text-sm mt-2 max-w-2xl" style={{ color: 'var(--color-text-secondary)' }}>
            App preferences — appearance, model defaults, keyboard shortcuts, and data management.
          </p>
        </header>

        <div className="flex flex-col gap-4">
          {/* Appearance */}
          <Section title="Appearance">
            <SettingRow label="Theme" description="Choose how OpenJarvis looks">
              <div className="flex gap-1 p-0.5 rounded-lg" style={{ background: 'var(--color-bg-secondary)' }}>
                {themeOptions.map((opt) => {
                  const isActive = settings.theme === opt.value;
                  return (
                    <button
                      key={opt.value}
                      onClick={() => { updateSettings({ theme: opt.value }); showSaved(); }}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer"
                      style={{
                        background: isActive ? 'var(--color-surface)' : 'transparent',
                        color: isActive ? 'var(--color-text)' : 'var(--color-text-tertiary)',
                        boxShadow: isActive ? 'var(--shadow-sm)' : 'none',
                      }}
                    >
                      <opt.icon size={14} />
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </SettingRow>
            <SettingRow label="Font size">
              <select
                value={settings.fontSize}
                onChange={(e) => { updateSettings({ fontSize: e.target.value as any }); showSaved(); }}
                className="text-sm px-3 py-1.5 rounded-lg outline-none cursor-pointer"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <option value="small">Small</option>
                <option value="default">Default</option>
                <option value="large">Large</option>
              </select>
            </SettingRow>
          </Section>

          {/* Connection */}
          <Section title="Connection">
            <SettingRow label="Server status" description={serverInfo ? `${serverInfo.engine} / ${serverInfo.model}` : 'Not connected'}>
              <div className="flex items-center gap-2">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ background: healthy === true ? 'var(--color-success)' : healthy === false ? 'var(--color-error)' : 'var(--color-text-tertiary)' }}
                />
                <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  {healthy === true ? 'Connected' : healthy === false ? 'Disconnected' : 'Checking...'}
                </span>
              </div>
            </SettingRow>
            <SettingRow label="API URL" description="Set if backend runs on a different port or host">
              <input
                type="text"
                value={settings.apiUrl}
                onChange={(e) => { updateSettings({ apiUrl: e.target.value }); showSaved(); }}
                placeholder="http://localhost:8000"
                className="text-sm px-3 py-1.5 rounded-lg outline-none w-56"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              />
            </SettingRow>
          </Section>

          {/* Models */}
          <Section title="Models">
            <SettingRow label="Local models (Ollama)" description="Models available for local inference">
              <OllamaModelList />
            </SettingRow>
            <div className="text-xs mt-2 px-1" style={{ color: 'var(--color-text-tertiary)' }}>
              Run <code className="px-1 py-0.5 rounded text-[11px]" style={{ background: 'var(--color-bg-tertiary)' }}>ollama pull &lt;model-name&gt;</code> in your terminal to add more models
            </div>
            <SettingRow label="Cloud providers" description="Green dot means API key is configured">
              <div className="flex flex-wrap gap-3">
                <CloudProviderStatus label="OpenAI" storageKey="openjarvis-openai-key" />
                <CloudProviderStatus label="Anthropic" storageKey="openjarvis-anthropic-key" />
                <CloudProviderStatus label="Google" storageKey="openjarvis-gemini-key" />
                <CloudProviderStatus label="OpenRouter" storageKey="openjarvis-openrouter-key" />
              </div>
            </SettingRow>
          </Section>

          {/* API Keys */}
          <Section title="API Keys">
            <SettingRow label="OpenAI" description="GPT-4, GPT-3.5, etc.">
              <ApiKeyInput storageKey="openjarvis-openai-key" placeholder="sk-..." />
            </SettingRow>
            <SettingRow label="Anthropic" description="Claude models">
              <ApiKeyInput storageKey="openjarvis-anthropic-key" placeholder="sk-ant-..." />
            </SettingRow>
            <SettingRow label="Google" description="Gemini models">
              <ApiKeyInput storageKey="openjarvis-gemini-key" placeholder="AI..." />
            </SettingRow>
            <SettingRow label="OpenRouter" description="Multi-provider routing">
              <ApiKeyInput storageKey="openjarvis-openrouter-key" placeholder="sk-or-..." />
            </SettingRow>
          </Section>

          {/* Tools */}
          <Section title="Tools">
            <SettingRow label="Web Search" description="SerpAPI or Tavily key for web search tool">
              <ApiKeyInput storageKey="openjarvis-search-key" placeholder="API key..." />
            </SettingRow>
          </Section>

          {/* Navigation */}
          <Section title="Navigation">
            <SettingRow label="TMAP API key" description="Stored locally in this browser for route guidance">
              <input
                type="password"
                value={settings.tmapApiKey}
                onChange={(e) => { updateSettings({ tmapApiKey: e.target.value }); showSaved(); }}
                placeholder="TMAP appKey"
                autoComplete="off"
                spellCheck={false}
                className="w-64 px-2 py-1 rounded text-xs"
                style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              />
            </SettingRow>
            <SettingRow
              label="Always-on location"
              description={
                currentLocation
                  ? `${locationStatus || '현재 위치 사용 중'} · ${currentLocation.latitude.toFixed(4)}, ${currentLocation.longitude.toFixed(4)}`
                  : locationStatus || 'Keep current location updated while the app is open'
              }
            >
              <div className="flex items-center gap-2">
                <button
                  onClick={requestLocationNow}
                  disabled={locationRequesting}
                  className="px-3 py-1.5 rounded text-xs font-medium transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-default"
                  style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
                >
                  {locationRequesting ? 'Checking...' : 'Request location'}
                </button>
                <button
                  onClick={() => { updateSettings({ locationAlwaysOn: !settings.locationAlwaysOn }); showSaved(); }}
                  className="relative w-11 h-6 rounded-full transition-colors cursor-pointer"
                  style={{
                    background: settings.locationAlwaysOn ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                  }}
                >
                  <span
                    className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full transition-transform bg-white"
                    style={{
                      transform: settings.locationAlwaysOn ? 'translateX(20px)' : 'translateX(0)',
                      boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                    }}
                  />
                </button>
              </div>
            </SettingRow>
            <SettingRow label="Manual location" description="Use these coordinates when browser location is unavailable">
              <div className="flex flex-wrap items-center justify-end gap-2">
                <input
                  value={settings.manualLocationName}
                  onChange={(e) => { updateSettings({ manualLocationName: e.target.value }); showSaved(); }}
                  placeholder="Name"
                  className="w-24 px-2 py-1 rounded text-xs"
                  style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                />
                <input
                  value={settings.manualLatitude}
                  onChange={(e) => { updateSettings({ manualLatitude: e.target.value }); showSaved(); }}
                  placeholder="Latitude"
                  inputMode="decimal"
                  className="w-24 px-2 py-1 rounded text-xs"
                  style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                />
                <input
                  value={settings.manualLongitude}
                  onChange={(e) => { updateSettings({ manualLongitude: e.target.value }); showSaved(); }}
                  placeholder="Longitude"
                  inputMode="decimal"
                  className="w-24 px-2 py-1 rounded text-xs"
                  style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                />
                <button
                  onClick={applyManualLocation}
                  className="px-3 py-1.5 rounded text-xs font-medium transition-colors cursor-pointer"
                  style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}
                >
                  Apply
                </button>
              </div>
            </SettingRow>
            <SettingRow label="Default route mode" description="Used unless you say driving or walking in the request">
              <select
                value={settings.navigationMode}
                onChange={(e) => { updateSettings({ navigationMode: e.target.value as NavigationMode }); showSaved(); }}
                className="px-2 py-1 rounded text-xs"
                style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              >
                <option value="car">Car</option>
                <option value="walk">Walk</option>
              </select>
            </SettingRow>
          </Section>

          {/* Memory */}
          <Section title="Memory">
            <SettingRow label="Memory status" description={memoryStats ? `${memoryStats.backend} backend — ${memoryStats.entries} entries` : 'Unable to reach memory service'}>
              <div className="flex items-center gap-2">
                <Brain size={14} style={{ color: memoryStats ? 'var(--color-accent)' : 'var(--color-text-tertiary)' }} />
                <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  {memoryStats ? `${memoryStats.entries} entries` : 'Unavailable'}
                </span>
              </div>
            </SettingRow>
            <SettingRow label="Use memory context" description="Automatically inject relevant memories into conversations">
              <button
                onClick={() => {
                  const next = !memoryEnabled;
                  setMemoryEnabled(next);
                  try { localStorage.setItem('openjarvis-memory-enabled', String(next)); } catch {}
                  showSaved();
                }}
                className="relative w-11 h-6 rounded-full transition-colors cursor-pointer"
                style={{
                  background: memoryEnabled ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                }}
              >
                <span
                  className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full transition-transform bg-white"
                  style={{
                    transform: memoryEnabled ? 'translateX(20px)' : 'translateX(0)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                  }}
                />
              </button>
            </SettingRow>
            <SettingRow label="Memory backend" description="Which retrieval engine to use">
              <select
                value={memoryBackend}
                onChange={(e) => {
                  setMemoryBackend(e.target.value);
                  try { localStorage.setItem('openjarvis-memory-backend', e.target.value); } catch {}
                  showSaved();
                }}
                className="text-sm px-3 py-1.5 rounded-lg outline-none cursor-pointer"
                style={{
                  background: 'var(--color-bg-secondary)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <option value="sqlite">sqlite</option>
                <option value="faiss">faiss</option>
                <option value="bm25">bm25</option>
                <option value="colbert">colbert</option>
                <option value="hybrid">hybrid</option>
              </select>
            </SettingRow>
            <SettingRow label="Results to inject" description={`${memoryTopK}`}>
              <input
                type="range"
                min="1"
                max="20"
                step="1"
                value={memoryTopK}
                onChange={(e) => {
                  const v = parseInt(e.target.value);
                  setMemoryTopK(v);
                  try { localStorage.setItem('openjarvis-memory-top-k', String(v)); } catch {}
                  showSaved();
                }}
                className="w-32 cursor-pointer accent-[var(--color-accent)]"
              />
            </SettingRow>
            <SettingRow label="Min relevance score" description={`${memoryMinScore}`}>
              <input
                type="range"
                min="0"
                max="1"
                step="0.05"
                value={memoryMinScore}
                onChange={(e) => {
                  const v = parseFloat(e.target.value);
                  setMemoryMinScore(v);
                  try { localStorage.setItem('openjarvis-memory-min-score', String(v)); } catch {}
                  showSaved();
                }}
                className="w-32 cursor-pointer accent-[var(--color-accent)]"
              />
            </SettingRow>
            <SettingRow label="Max context tokens" description={`${memoryMaxTokens}`}>
              <input
                type="range"
                min="256"
                max="8192"
                step="256"
                value={memoryMaxTokens}
                onChange={(e) => {
                  const v = parseInt(e.target.value);
                  setMemoryMaxTokens(v);
                  try { localStorage.setItem('openjarvis-memory-max-tokens', String(v)); } catch {}
                  showSaved();
                }}
                className="w-32 cursor-pointer accent-[var(--color-accent)]"
              />
            </SettingRow>
          </Section>

          {/* Model defaults */}
          <Section title="Model Defaults">
            <SettingRow label="Temperature" description={`${settings.temperature}`}>
              <input
                type="range"
                min="0"
                max="2"
                step="0.1"
                value={settings.temperature}
                onChange={(e) => { updateSettings({ temperature: parseFloat(e.target.value) }); showSaved(); }}
                className="w-32 cursor-pointer accent-[var(--color-accent)]"
              />
            </SettingRow>
            <SettingRow label="Max tokens" description={`${settings.maxTokens}`}>
              <input
                type="range"
                min="256"
                max="32768"
                step="256"
                value={settings.maxTokens}
                onChange={(e) => { updateSettings({ maxTokens: parseInt(e.target.value) }); showSaved(); }}
                className="w-32 cursor-pointer accent-[var(--color-accent)]"
              />
            </SettingRow>
          </Section>

          {/* Speech */}
          <Section title="Speech">
            <SettingRow label="Voice input" description="Use browser speech recognition for Korean dictation">
              <button
                onClick={() => { updateSettings({ speechEnabled: !settings.speechEnabled }); showSaved(); }}
                className="relative w-11 h-6 rounded-full transition-colors cursor-pointer"
                style={{
                  background: settings.speechEnabled ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                }}
              >
                <span
                  className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full transition-transform bg-white"
                  style={{
                    transform: settings.speechEnabled ? 'translateX(20px)' : 'translateX(0)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                  }}
                />
              </button>
            </SettingRow>
            <SettingRow label="STT mode" description="Use the free browser Web Speech API in web mode">
              <select
                value={settings.speechInputMode}
                onChange={(e) => { updateSettings({ speechInputMode: e.target.value as SpeechInputMode }); showSaved(); }}
                className="px-2 py-1 rounded text-xs"
                style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              >
                {speechInputModeOptions.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </SettingRow>
            <SettingRow label="Always-on wake" description="Start wake listening automatically when the app opens">
              <button
                onClick={() => {
                  const nextWakeAlwaysOn = !settings.wakeAlwaysOn;
                  updateSettings({
                    wakeAlwaysOn: nextWakeAlwaysOn,
                    speechEnabled: nextWakeAlwaysOn ? true : settings.speechEnabled,
                  });
                  showSaved();
                }}
                className="relative w-11 h-6 rounded-full transition-colors cursor-pointer"
                style={{
                  background: settings.wakeAlwaysOn ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                }}
              >
                <span
                  className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full transition-transform bg-white"
                  style={{
                    transform: settings.wakeAlwaysOn ? 'translateX(20px)' : 'translateX(0)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                  }}
                />
              </button>
            </SettingRow>
            <SettingRow label="Wake phrases" description="Comma-separated call words">
              <input
                value={settings.wakePhrases}
                onChange={(e) => { updateSettings({ wakePhrases: e.target.value }); showSaved(); }}
                className="w-64 px-2 py-1 rounded text-xs"
                style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              />
            </SettingRow>
            <SettingRow label="Speak replies" description="Read assistant replies aloud with browser speech synthesis">
              <button
                onClick={() => { updateSettings({ speakReplies: !settings.speakReplies }); showSaved(); }}
                className="relative w-11 h-6 rounded-full transition-colors cursor-pointer"
                style={{
                  background: settings.speakReplies ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                }}
              >
                <span
                  className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full transition-transform bg-white"
                  style={{
                    transform: settings.speakReplies ? 'translateX(20px)' : 'translateX(0)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                  }}
                />
              </button>
            </SettingRow>
            <SettingRow label="TTS mode" description="Friday.app prefers local macOS say; browser mode can keep speechSynthesis">
              <select
                value={settings.ttsMode}
                onChange={(e) => { updateSettings({ ttsMode: e.target.value as TtsMode }); showSaved(); }}
                className="px-2 py-1 rounded text-xs"
                style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              >
                {ttsModeOptions.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </SettingRow>
            <SettingRow label="Gemini API key" description="Stored locally in this browser for Gemini TTS">
              <input
                type="password"
                value={settings.geminiApiKey}
                onChange={(e) => { updateSettings({ geminiApiKey: e.target.value }); showSaved(); }}
                placeholder="AIza..."
                autoComplete="off"
                spellCheck={false}
                className="w-64 px-2 py-1 rounded text-xs"
                style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              />
            </SettingRow>
            <SettingRow label="Gemini voice" description={ttsSampleStatus || 'Choose a Gemini voice and preview it'}>
              <div className="flex items-center gap-2">
                <select
                  value={settings.geminiVoice}
                  onChange={(e) => { updateSettings({ geminiVoice: e.target.value }); showSaved(); }}
                  className="px-2 py-1 rounded text-xs"
                  style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                >
                  {geminiVoiceOptions.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
                <button
                  onClick={playGeminiVoiceSample}
                  disabled={!settings.geminiApiKey.trim()}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-default"
                  style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
                >
                  <Volume2 size={12} />
                  Sample
                </button>
              </div>
            </SettingRow>
            <SettingRow label="Edge voice" description={ttsSampleStatus || 'Choose an edge-tts voice and preview it'}>
              <div className="flex items-center gap-2">
                <select
                  value={settings.edgeVoice}
                  onChange={(e) => { updateSettings({ edgeVoice: e.target.value }); showSaved(); }}
                  className="px-2 py-1 rounded text-xs"
                  style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                >
                  {edgeVoiceOptions.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
                <button
                  onClick={playEdgeVoiceSample}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer"
                  style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
                >
                  <Volume2 size={12} />
                  Sample
                </button>
              </div>
            </SettingRow>
            <SettingRow label="macOS voice" description="Recommended Korean voice: Yuna">
              <input
                value={settings.ttsVoice}
                onChange={(e) => { updateSettings({ ttsVoice: e.target.value }); showSaved(); }}
                className="w-32 px-2 py-1 rounded text-xs"
                style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              />
            </SettingRow>
            <SettingRow label="TTS rate" description={`${settings.ttsRate} words per minute`}>
              <input
                type="number"
                min="80"
                max="320"
                value={settings.ttsRate}
                onChange={(e) => { updateSettings({ ttsRate: parseInt(e.target.value) || 165 }); showSaved(); }}
                className="w-24 px-2 py-1 rounded text-xs"
                style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              />
            </SettingRow>
            <SettingRow label="TTS pause" description={`${settings.ttsPauseMs ?? 250} ms between chunks`}>
              <input
                type="number"
                min="0"
                max="2000"
                value={settings.ttsPauseMs ?? 250}
                onChange={(e) => { updateSettings({ ttsPauseMs: parseInt(e.target.value) || 250 }); showSaved(); }}
                className="w-24 px-2 py-1 rounded text-xs"
                style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              />
            </SettingRow>
            <SettingRow label="Natural Korean TTS" description="Shortens dense replies and weather into spoken Korean">
              <button
                onClick={() => { updateSettings({ ttsNaturalize: !(settings.ttsNaturalize ?? true) }); showSaved(); }}
                className="relative w-11 h-6 rounded-full transition-colors"
                style={{
                  background: (settings.ttsNaturalize ?? true) ? 'var(--color-accent)' : 'var(--color-bg-tertiary)',
                }}
              >
                <span
                  className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full transition-transform bg-white"
                  style={{
                    transform: (settings.ttsNaturalize ?? true) ? 'translateX(20px)' : 'translateX(0)',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.2)',
                  }}
                />
              </button>
            </SettingRow>
            <SettingRow label="TTS max length" description={`${settings.ttsMaxChars} characters per reply`}>
              <input
                type="number"
                min="80"
                max="1200"
                value={settings.ttsMaxChars}
                onChange={(e) => { updateSettings({ ttsMaxChars: parseInt(e.target.value) || 400 }); showSaved(); }}
                className="w-24 px-2 py-1 rounded text-xs"
                style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              />
            </SettingRow>
            <SettingRow label="Browser status" description="Uses Web Speech API locally in the browser">
              <div className="flex items-center gap-2">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{
                    background: browserSpeechAvailable === true ? 'var(--color-success)'
                      : browserSpeechAvailable === false ? 'var(--color-text-tertiary)'
                      : 'var(--color-text-tertiary)',
                  }}
                />
                <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  {browserSpeechAvailable === null ? 'Checking...'
                    : browserSpeechAvailable ? 'Available'
                    : 'Unavailable'}
                </span>
              </div>
            </SettingRow>
            {!browserSpeechAvailable && browserSpeechAvailable !== null && (
              <div className="text-xs mt-2 px-1" style={{ color: 'var(--color-text-tertiary)' }}>
                This browser does not expose speech recognition. Try Chrome or Safari for voice input.
              </div>
            )}
          </Section>

          {/* Savings Sharing */}
          <Section title="Savings Sharing">
            <SettingRow
              label="Share Your Savings"
              description="Leaderboard sharing is off by default. Open this only if you want to opt in."
            >
              <button
                onClick={() => setOptInModalOpen(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer"
                style={{
                  background: optInEnabled ? 'var(--color-accent-subtle)' : 'var(--color-bg-secondary)',
                  color: optInEnabled ? 'var(--color-accent)' : 'var(--color-text-secondary)',
                  border: optInEnabled ? '1px solid var(--color-accent)' : '1px solid var(--color-border)',
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = optInEnabled ? 'var(--color-accent-subtle)' : 'var(--color-bg-tertiary)')}
                onMouseLeave={(e) => (e.currentTarget.style.background = optInEnabled ? 'var(--color-accent-subtle)' : 'var(--color-bg-secondary)')}
              >
                <Trophy size={12} />
                {optInEnabled ? 'Manage Sharing' : 'Open Sharing'}
              </button>
            </SettingRow>
          </Section>

          {/* Data */}
          <Section title="Data">
            <SettingRow label="Conversations" description={`${conversations.length} stored locally`}>
              <div className="flex gap-2">
                <button
                  onClick={handleExport}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer"
                  style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--color-bg-secondary)')}
                >
                  <Download size={12} /> Export
                </button>
                <button
                  onClick={handleImport}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer"
                  style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--color-bg-secondary)')}
                >
                  <Upload size={12} /> Import
                </button>
              </div>
            </SettingRow>
            <SettingRow label="Clear all data" description="Permanently delete all conversations">
              <button
                onClick={handleClear}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer"
                style={{
                  color: confirmClear ? 'white' : 'var(--color-error)',
                  background: confirmClear ? 'var(--color-error)' : 'transparent',
                  border: '1px solid var(--color-error)',
                }}
                onMouseEnter={(e) => { if (!confirmClear) e.currentTarget.style.background = 'rgba(220,38,38,0.1)'; }}
                onMouseLeave={(e) => { if (!confirmClear) e.currentTarget.style.background = 'transparent'; }}
              >
                <Trash2 size={12} /> {confirmClear ? 'Click again to confirm' : 'Clear'}
              </button>
            </SettingRow>
          </Section>

          {/* About */}
          <Section title="About">
            <div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              <p className="mb-2">
                <span className="font-semibold" style={{ color: 'var(--color-text)' }}>OpenJarvis</span> — Programming abstractions for on-device AI.
              </p>
              <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                Part of Intelligence Per Watt, a research initiative at Stanford SAIL.
              </p>
              <div className="flex gap-3 mt-3 text-xs">
                <a
                  href="https://scalingintelligence.stanford.edu/blogs/openjarvis/"
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: 'var(--color-accent)' }}
                >
                  Project site
                </a>
                <a
                  href="https://open-jarvis.github.io/OpenJarvis/"
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: 'var(--color-accent)' }}
                >
                  Documentation
                </a>
              </div>
            </div>
          </Section>
        </div>
      </div>
    </div>
  );
}
