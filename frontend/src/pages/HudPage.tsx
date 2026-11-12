import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router';
import { HoloWorld } from '../components/Hud/HoloWorld';
import { CoreReactor, type HudMode } from '../components/Hud/CoreReactor';
import { Spectrum } from '../components/Hud/Spectrum';
import { useAppStore } from '../lib/store';
import { streamChat } from '../lib/sse';
import {
  checkHealth,
  fetchEnergy,
  fetchServerInfo,
  fetchTelemetry,
  transcribeAudio,
} from '../lib/api';
import { stripThinkTags, toSpeakableText } from '../lib/message-text';
import { useTts } from '../hooks/useTts';
import '../components/Hud/hud.css';

interface HudMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

interface LogLine {
  id: number;
  time: string;
  text: string;
  level: 'info' | 'ok' | 'warn' | 'err';
}

interface Stats {
  total_requests?: number;
  total_tokens?: number;
  avg_throughput_tok_per_sec?: number;
  avg_gpu_utilization_pct?: number;
  total_energy_joules?: number;
}

interface Energy {
  avg_power_w?: number;
  cpu_temp_c?: number | null;
  gpu_temp_c?: number | null;
  energy_per_token_j?: number;
}

const QUICK_COMMANDS = [
  'Give me a status report',
  'What can you help me with?',
  'Summarize today in one line',
  'Tell me a fascinating science fact',
];

/** Plain-text rendering for the holographic transcript (no markdown chrome). */
const toHudText = (raw: string) =>
  stripThinkTags(raw)
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/(^|\s)[*_](\S.*?\S|\S)[*_](?=\s|$|[.,!?])/g, '$1$2')
    .replace(/^#{1,6}\s*/gm, '')
    .replace(/^\s*[-*]\s+/gm, '▸ ')
    .replace(/`{1,3}/g, '');

let logSeq = 0;
const stamp = () => new Date().toLocaleTimeString([], { hour12: false });
const uid = () => Math.random().toString(36).slice(2, 10);

function Panel({
  title,
  code,
  className = '',
  children,
}: {
  title: string;
  code?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={`hud-panel ${className}`}>
      <span className="hud-panel__corner hud-panel__corner--tl" />
      <span className="hud-panel__corner hud-panel__corner--tr" />
      <span className="hud-panel__corner hud-panel__corner--bl" />
      <span className="hud-panel__corner hud-panel__corner--br" />
      <header className="hud-panel__head">
        <span className="hud-panel__title">{title}</span>
        {code && <span className="hud-panel__code">{code}</span>}
      </header>
      <div className="hud-panel__body">{children}</div>
    </section>
  );
}

function Meter({ label, value, max, unit }: { label: string; value: number; max: number; unit?: string }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const shown = Number.isFinite(value)
    ? value >= 1000 ? value.toLocaleString(undefined, { maximumFractionDigits: 0 }) : value.toFixed(value % 1 ? 1 : 0)
    : '--';
  return (
    <div className="hud-meter">
      <div className="hud-meter__row">
        <span>{label}</span>
        <span className="hud-meter__val">{shown}{unit && <small>{unit}</small>}</span>
      </div>
      <div className="hud-meter__bar">
        <span style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function Chrono() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  const s = now.getSeconds(), m = now.getMinutes(), h = now.getHours() % 12;
  return (
    <div className="hud-chrono">
      <svg viewBox="0 0 120 120" aria-hidden="true">
        <circle cx="60" cy="60" r="54" className="chrono-ring" />
        {Array.from({ length: 60 }, (_, i) => (
          <line key={i} x1="60" y1="8" x2="60" y2={i % 5 ? 11 : 15}
            transform={`rotate(${i * 6} 60 60)`} className={i <= s ? 'chrono-tick on' : 'chrono-tick'} />
        ))}
        <line x1="60" y1="60" x2="60" y2="32" className="chrono-h" transform={`rotate(${h * 30 + m / 2} 60 60)`} />
        <line x1="60" y1="60" x2="60" y2="22" className="chrono-m" transform={`rotate(${m * 6} 60 60)`} />
        <circle cx="60" cy="60" r="3" className="chrono-pin" />
      </svg>
      <div className="hud-chrono__text">
        <strong>{now.toLocaleTimeString([], { hour12: false })}</strong>
        <span>{now.toLocaleDateString([], { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' }).toUpperCase()}</span>
      </div>
    </div>
  );
}

/** Reveals text progressively so replies that arrive in one chunk still "type out". */
function Typewriter({ text, onTick }: { text: string; onTick?: () => void }) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    if (shown >= text.length) return;
    const step = Math.max(1, Math.ceil((text.length - shown) / 40));
    const t = setTimeout(() => { setShown((n) => Math.min(text.length, n + step)); onTick?.(); }, 18);
    return () => clearTimeout(t);
  }, [shown, text, onTick]);
  return (
    <>
      {text.slice(0, shown)}
      {shown < text.length && <span className="hud-caret" />}
    </>
  );
}

export function HudPage() {
  const navigate = useNavigate();
  const models = useAppStore((s) => s.models);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const setSelectedModel = useAppStore((s) => s.setSelectedModel);
  const tts = useTts();

  const [messages, setMessages] = useState<HudMessage[]>([]);
  const [input, setInput] = useState('');
  const [log, setLog] = useState<LogLine[]>([]);
  const [online, setOnline] = useState(true);
  const [serverModel, setServerModel] = useState('');
  const [stats, setStats] = useState<Stats>({});
  const [energy, setEnergy] = useState<Energy>({});
  const [phase, setPhase] = useState<'idle' | 'listening' | 'transcribing' | 'thinking' | 'streaming'>('idle');
  const [voiceOut, setVoiceOut] = useState(true);
  const [lastTps, setLastTps] = useState(0);
  const [browserSpeaking, setBrowserSpeaking] = useState(false);
  const speechPollRef = useRef(0);
  const speaking = tts.isSpeaking || browserSpeaking;

  // Voice output: server TTS when configured, otherwise the browser's own
  // speech synthesis so spoken replies work out of the box.
  const stopVoice = useCallback(() => {
    tts.stop();
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    window.clearInterval(speechPollRef.current);
    setBrowserSpeaking(false);
  }, [tts]);

  const speakReply = useCallback((id: string, text: string) => {
    if (tts.available) { void tts.speak(id, text); return; }
    if (!('speechSynthesis' in window)) return;
    const synth = window.speechSynthesis;
    const voices = synth.getVoices();
    const u = new SpeechSynthesisUtterance(text);
    u.voice =
      voices.find((v) => /en-GB/i.test(v.lang) && /male|george|ryan|daniel|thomas/i.test(v.name)) ||
      voices.find((v) => /en-GB/i.test(v.lang)) ||
      voices.find((v) => v.lang.startsWith('en')) ||
      null;
    u.rate = 1.03;
    u.pitch = 0.9;
    synth.cancel();
    synth.speak(u);
    // start/end events are unreliable across browsers, so poll the engine.
    setBrowserSpeaking(true);
    window.clearInterval(speechPollRef.current);
    speechPollRef.current = window.setInterval(() => {
      if (!synth.speaking && !synth.pending) {
        window.clearInterval(speechPollRef.current);
        setBrowserSpeaking(false);
      }
    }, 250);
  }, [tts]);

  const levelRef = useRef(0);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const meterRaf = useRef(0);
  const stageRef = useRef<HTMLDivElement>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const historyRef = useRef<HudMessage[]>([]);
  historyRef.current = messages;

  const model = selectedModel || serverModel || models[0]?.id || '';

  const addLog = useCallback((text: string, level: LogLine['level'] = 'info') => {
    setLog((l) => [...l.slice(-60), { id: ++logSeq, time: stamp(), text, level }]);
  }, []);

  // Boot sequence + telemetry polling
  const bootedRef = useRef(false);
  const wasOnlineRef = useRef<boolean | null>(null);
  useEffect(() => {
    if (!bootedRef.current) {
      bootedRef.current = true;
      addLog('HUD interface initialised', 'ok');
    }
    let cancelled = false;
    const poll = async () => {
      const ok = await checkHealth();
      if (cancelled) return;
      setOnline(ok);
      if (wasOnlineRef.current !== ok) {
        addLog(ok ? 'Link to Jarvis core established' : 'Jarvis core unreachable', ok ? 'ok' : 'err');
        wasOnlineRef.current = ok;
      }
      if (!ok) return;
      fetchTelemetry().then((s) => !cancelled && setStats(s as Stats)).catch(() => {});
      fetchEnergy().then((e) => !cancelled && setEnergy(e as Energy)).catch(() => {});
    };
    fetchServerInfo()
      .then((i) => {
        if (cancelled) return;
        setServerModel(i.model);
        addLog(`Engine ${String((i as unknown as Record<string, unknown>).engine ?? '')} · model ${i.model}`);
      })
      .catch(() => {});
    poll();
    const t = setInterval(poll, 4000);
    return () => { cancelled = true; clearInterval(t); };
  }, [addLog]);

  // 3D parallax tilt on the whole HUD stage
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    let raf = 0, tx = 0, ty = 0, x = 0, y = 0;
    const onMove = (e: PointerEvent) => {
      tx = (e.clientX / window.innerWidth - 0.5) * 2;
      ty = (e.clientY / window.innerHeight - 0.5) * 2;
    };
    const tick = () => {
      x += (tx - x) * 0.08;
      y += (ty - y) * 0.08;
      stage.style.setProperty('--tilt-x', `${(-y * 3).toFixed(3)}deg`);
      stage.style.setProperty('--tilt-y', `${(x * 4).toFixed(3)}deg`);
      raf = requestAnimationFrame(tick);
    };
    window.addEventListener('pointermove', onMove);
    raf = requestAnimationFrame(tick);
    return () => { cancelAnimationFrame(raf); window.removeEventListener('pointermove', onMove); };
  }, []);

  // Keep transcript scrolled to newest
  const scrollTranscript = useCallback(() => {
    const el = transcriptRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, []);
  useEffect(scrollTranscript, [messages, scrollTranscript]);

  // Speech-level simulation while TTS is speaking
  useEffect(() => {
    if (!speaking) return;
    let raf = 0;
    const loop = (t: number) => {
      levelRef.current = 0.35 + Math.abs(Math.sin(t / 110)) * 0.35 + Math.random() * 0.15;
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => { cancelAnimationFrame(raf); levelRef.current = 0; };
  }, [speaking]);

  const mode: HudMode = useMemo(() => {
    if (phase === 'listening') return 'listening';
    if (phase === 'transcribing') return 'transcribing';
    if (phase === 'thinking') return 'thinking';
    if (phase === 'streaming' || speaking || tts.isLoading) return 'speaking';
    if (!online) return 'offline';
    return 'idle';
  }, [phase, speaking, tts.isLoading, online]);

  const worldEnergy = mode === 'thinking' ? 1 : mode === 'speaking' ? 0.6 : mode === 'listening' ? 0.4 : 0;

  const send = useCallback(async (raw: string) => {
    const text = raw.trim();
    if (!text || abortRef.current) return;
    if (!model) {
      addLog('No model available — pull one in Settings', 'err');
      return;
    }
    stopVoice();
    const userMsg: HudMessage = { id: uid(), role: 'user', content: text };
    const reply: HudMessage = { id: uid(), role: 'assistant', content: '' };
    const history = [...historyRef.current, userMsg];
    setMessages([...history, reply]);
    setInput('');
    setPhase('thinking');
    addLog(`> ${text.length > 48 ? text.slice(0, 48) + '…' : text}`);

    const controller = new AbortController();
    abortRef.current = controller;
    const started = performance.now();
    let content = '';
    let tokens = 0;
    let chunks = 0;
    let firstAt = 0;
    try {
      for await (const ev of streamChat(
        {
          model,
          stream: true,
          messages: [
            { role: 'system', content: 'You are J.A.R.V.I.S., a concise, capable personal AI running locally. Keep replies short and conversational unless asked for detail.' },
            ...history.slice(-12).map((m) => ({ role: m.role, content: m.content })),
          ],
        },
        controller.signal,
      )) {
        if (ev.event === 'tool_call_start') {
          try { addLog(`Tool ▸ ${JSON.parse(ev.data).tool}`, 'warn'); } catch {}
          continue;
        }
        if (ev.event === 'tool_call_end') {
          try { const d = JSON.parse(ev.data); addLog(`Tool ${d.tool} ${d.success ? 'complete' : 'failed'}`, d.success ? 'ok' : 'err'); } catch {}
          continue;
        }
        if (ev.event === 'inference_start') { addLog('Inference engaged'); continue; }
        if (ev.event) continue;
        try {
          const data = JSON.parse(ev.data);
          const delta = data.choices?.[0]?.delta?.content;
          if (delta) {
            if (!firstAt) { firstAt = performance.now(); setPhase('streaming'); }
            content += delta;
            chunks++;
            levelRef.current = 0.3 + Math.random() * 0.5;
            const shown = toHudText(content);
            setMessages((ms) => ms.map((m) => (m.id === reply.id ? { ...m, content: shown } : m)));
          }
          if (data.usage?.completion_tokens) tokens = data.usage.completion_tokens;
          if (data.choices?.[0]?.finish_reason === 'stop') break;
        } catch {}
      }
      const secs = (performance.now() - started) / 1000;
      // The agent endpoint may deliver the whole reply as one chunk, so prefer
      // the server's token count and estimate (~4 chars/token) otherwise.
      if (!tokens) tokens = chunks > 1 ? chunks : Math.round(content.length / 4);
      const tps = secs > 0 ? tokens / secs : 0;
      setLastTps(tps);
      addLog(`Response complete · ${tokens} tokens · ${secs.toFixed(1)}s`, 'ok');
      const final = stripThinkTags(content).trim();
      if (!final) {
        setMessages((ms) => ms.map((m) => (m.id === reply.id ? { ...m, content: '(no response)' } : m)));
      } else if (voiceOut) {
        speakReply(reply.id, toSpeakableText(final));
      }
    } catch (err) {
      const aborted = (err as Error)?.name === 'AbortError';
      addLog(aborted ? 'Generation aborted' : `Error: ${(err as Error).message}`, aborted ? 'warn' : 'err');
      setMessages((ms) => ms.map((m) => (m.id === reply.id
        ? { ...m, content: stripThinkTags(content) || (aborted ? '(stopped)' : 'Connection to the core failed.') }
        : m)));
    } finally {
      abortRef.current = null;
      levelRef.current = 0;
      setPhase('idle');
    }
  }, [model, addLog, stopVoice, speakReply, voiceOut]);

  const stopMeter = () => {
    cancelAnimationFrame(meterRaf.current);
    levelRef.current = 0;
    analyserRef.current = null;
    audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;
  };

  const startListening = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      addLog('Microphone not supported here', 'err');
      return;
    }
    try {
      stopVoice();
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const ctx = new AudioContext();
      audioCtxRef.current = ctx;
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      ctx.createMediaStreamSource(stream).connect(analyser);
      analyserRef.current = analyser;
      const buf = new Uint8Array(analyser.fftSize);
      const loop = () => {
        analyser.getByteTimeDomainData(buf);
        let sum = 0;
        for (const v of buf) sum += ((v - 128) / 128) ** 2;
        levelRef.current = Math.min(1, Math.sqrt(sum / buf.length) * 4);
        meterRaf.current = requestAnimationFrame(loop);
      };
      loop();

      const chunks: Blob[] = [];
      const rec = new MediaRecorder(stream);
      rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        stopMeter();
        setPhase('transcribing');
        addLog('Decoding voice input…');
        try {
          const blob = new Blob(chunks, { type: rec.mimeType || 'audio/webm' });
          const result = await transcribeAudio(blob);
          const heard = result.text.trim();
          setPhase('idle');
          if (heard) {
            addLog(`Heard: "${heard.slice(0, 40)}"`, 'ok');
            void send(heard);
          } else {
            addLog('No speech detected', 'warn');
          }
        } catch (err) {
          setPhase('idle');
          addLog(`Voice decode failed: ${(err as Error).message}`, 'err');
        }
      };
      rec.start();
      recorderRef.current = rec;
      setPhase('listening');
      addLog('Microphone live', 'ok');
    } catch {
      addLog('Microphone access denied', 'err');
      stopMeter();
      setPhase('idle');
    }
  }, [addLog, send, stopVoice]);

  const stopListening = useCallback(() => {
    const rec = recorderRef.current;
    recorderRef.current = null;
    if (rec && rec.state === 'recording') rec.stop();
  }, []);

  // Cleanup on unmount
  useEffect(() => () => {
    abortRef.current?.abort();
    recorderRef.current?.stop();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    cancelAnimationFrame(meterRaf.current);
    audioCtxRef.current?.close().catch(() => {});
    window.clearInterval(speechPollRef.current);
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
  }, []);

  const activateCore = useCallback(() => {
    if (mode === 'listening') return stopListening();
    if (mode === 'thinking' || phase === 'streaming') { abortRef.current?.abort(); return; }
    if (speaking || tts.isLoading) { stopVoice(); return; }
    if (mode === 'transcribing') return;
    void startListening();
  }, [mode, phase, speaking, tts.isLoading, stopVoice, startListening, stopListening]);

  // Keyboard: Esc exits, "/" focuses input
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && document.activeElement !== inputRef.current) navigate('/');
      if (e.key === '/' && document.activeElement !== inputRef.current) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [navigate]);

  const lastReply = [...messages].reverse().find((m) => m.role === 'assistant');
  const busy = phase !== 'idle';
  const temp = energy.gpu_temp_c ?? energy.cpu_temp_c ?? null;

  return (
    <div className={`hud hud--${mode}`}>
      <HoloWorld energy={worldEnergy} />
      <div className="hud-vignette" aria-hidden="true" />

      <div className="hud-stage" ref={stageRef}>
        <header className="hud-top">
          <div className="hud-brand">
            <span className="hud-brand__glyph" aria-hidden="true" />
            <div>
              <h1>J.A.R.V.I.S</h1>
              <span>OPENJARVIS · LOCAL INTELLIGENCE GRID</span>
            </div>
          </div>
          <div className="hud-top__status">
            <span className={`hud-dot ${online ? 'on' : 'off'}`} />
            <span>{online ? 'CORE ONLINE' : 'CORE OFFLINE'}</span>
            <span className="hud-sep" />
            <span>{model ? model.toUpperCase() : 'NO MODEL'}</span>
          </div>
          <button type="button" className="hud-btn hud-btn--ghost" onClick={() => navigate('/')}>
            EXIT HUD
          </button>
        </header>

        <aside className="hud-col hud-col--left">
          <Panel title="Systems" code="SYS-01" className="depth-2">
            <Meter label="Requests" value={stats.total_requests ?? 0} max={Math.max(10, (stats.total_requests ?? 0) * 1.2)} />
            <Meter label="Tokens" value={stats.total_tokens ?? 0} max={Math.max(1000, (stats.total_tokens ?? 0) * 1.2)} />
            <Meter label="Throughput" value={lastTps || stats.avg_throughput_tok_per_sec || 0} max={80} unit=" t/s" />
            <Meter label="GPU load" value={stats.avg_gpu_utilization_pct ?? 0} max={100} unit="%" />
            <Meter label="Power" value={energy.avg_power_w ?? 0} max={350} unit=" W" />
            <Meter label="Temp" value={temp ?? 0} max={100} unit="°C" />
          </Panel>
          <Panel title="Chrono" code="TMR-02" className="depth-1">
            <Chrono />
          </Panel>
          <Panel title="Neural model" code="MDL-03" className="depth-1 hud-models">
            {models.length === 0 && <p className="hud-muted">Scanning for models…</p>}
            {models.map((m) => (
              <button
                key={m.id}
                type="button"
                className={`hud-chip ${m.id === model ? 'is-active' : ''}`}
                onClick={() => { setSelectedModel(m.id); addLog(`Model switched to ${m.id}`, 'ok'); }}
              >
                <span className="hud-chip__dot" />
                {m.id}
              </button>
            ))}
          </Panel>
        </aside>

        <main className="hud-center">
          <CoreReactor mode={mode} levelRef={levelRef} onActivate={activateCore} />
          <div className="hud-transcript" ref={transcriptRef} aria-live="polite">
            {messages.length === 0 ? (
              <p className="hud-transcript__empty">
                Good {new Date().getHours() < 12 ? 'morning' : new Date().getHours() < 18 ? 'afternoon' : 'evening'}.
                {' '}All systems nominal. Tap the core to speak, or type a command below.
              </p>
            ) : (
              messages.slice(-6).map((m) => (
                <div key={m.id} className={`hud-msg hud-msg--${m.role}`}>
                  <span className="hud-msg__who">{m.role === 'user' ? 'YOU' : 'JARVIS'}</span>
                  <p>
                    {!m.content ? (
                      <span className="hud-typing"><i /><i /><i /></span>
                    ) : m.id === lastReply?.id ? (
                      <Typewriter text={m.content} onTick={scrollTranscript} />
                    ) : (
                      m.content
                    )}
                  </p>
                </div>
              ))
            )}
          </div>
        </main>

        <aside className="hud-col hud-col--right">
          <Panel title="Signal" code="AUD-04" className="depth-2">
            <Spectrum analyserRef={analyserRef} levelRef={levelRef} mode={mode} />
          </Panel>
          <Panel title="Event log" code="LOG-05" className="depth-1 hud-log-panel">
            <ol className="hud-log">
              {log.slice(-14).map((l) => (
                <li key={l.id} className={`lv-${l.level}`}>
                  <time>{l.time}</time>
                  <span>{l.text}</span>
                </li>
              ))}
            </ol>
          </Panel>
          <Panel title="Directives" code="CMD-06" className="depth-1">
            <div className="hud-quick">
              {QUICK_COMMANDS.map((q) => (
                <button key={q} type="button" className="hud-quick__btn" disabled={busy} onClick={() => send(q)}>
                  <span>▸</span>{q}
                </button>
              ))}
            </div>
          </Panel>
        </aside>

        <form
          className="hud-command"
          onSubmit={(e) => { e.preventDefault(); void send(input); }}
        >
          <button
            type="button"
            className={`hud-btn hud-btn--icon ${mode === 'listening' ? 'is-live' : ''}`}
            onClick={() => (mode === 'listening' ? stopListening() : startListening())}
            disabled={phase === 'thinking' || phase === 'streaming' || phase === 'transcribing'}
            aria-label={mode === 'listening' ? 'Stop listening' : 'Start voice input'}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-2.08A7 7 0 0 0 19 12h-2Z" /></svg>
          </button>
          <div className="hud-command__field">
            <span className="hud-command__prompt">JARVIS://</span>
            <input
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={online ? 'Enter a command…' : 'Waiting for the core to come online…'}
              aria-label="Command"
              autoComplete="off"
            />
          </div>
          {busy && phase !== 'listening' && phase !== 'transcribing' ? (
            <button type="button" className="hud-btn hud-btn--warn" onClick={() => abortRef.current?.abort()}>
              ABORT
            </button>
          ) : (
            <button type="submit" className="hud-btn" disabled={!input.trim()}>
              EXECUTE
            </button>
          )}
          <button
            type="button"
            className={`hud-btn hud-btn--toggle ${voiceOut ? 'is-on' : ''}`}
            onClick={() => { setVoiceOut((v) => !v); if (voiceOut) stopVoice(); }}
            title="Speak replies aloud"
            aria-pressed={voiceOut}
          >
            VOICE {voiceOut ? 'ON' : 'OFF'}
          </button>
        </form>
      </div>
    </div>
  );
}
