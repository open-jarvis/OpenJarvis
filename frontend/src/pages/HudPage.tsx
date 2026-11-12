import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router';
import { HoloWorld } from '../components/Hud/HoloWorld';
import { CoreReactor, type HudMode } from '../components/Hud/CoreReactor';
import { Spectrum } from '../components/Hud/Spectrum';
import { AutomationsDeck } from '../components/Hud/AutomationsDeck';
import { ApprovalDock } from '../components/Hud/ApprovalDock';
import { AttachmentsDeck } from '../components/Hud/AttachmentsDeck';
import {
  ACCEPTED_FILES,
  attachmentApi,
  captureScreenshot,
  type Attachment,
} from '../components/Hud/attachmentApi';
import {
  automationApi,
  browserTimezone,
  useAutomations,
  useRunFeed,
} from '../components/Hud/automationApi';
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
import '../components/Hud/hud-automation.css';
import '../components/Hud/hud-attachments.css';

interface HudMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  /** Names of files attached to this (user) message. */
  files?: string[];
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
  const tts = useTts();
  // The HUD keeps its own model choice. "auto" lets the server route each
  // request: everyday chat stays local, complex / automation work goes to Claude.
  const [hudModel, setHudModel] = useState<string>(() => {
    try { return localStorage.getItem('oj-hud-model') || 'auto'; } catch { return 'auto'; }
  });
  const chooseModel = useCallback((id: string) => {
    setHudModel(id);
    try { localStorage.setItem('oj-hud-model', id); } catch { /* private mode */ }
  }, []);
  const [deckOpen, setDeckOpen] = useState(false);
  const automations = useAutomations(true);

  // ---- Attachments ------------------------------------------------------
  const [vaultOpen, setVaultOpen] = useState(false);
  const [pending, setPending] = useState<Attachment[]>([]);
  const [uploadingCount, setUploadingCount] = useState(0);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);

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

  const model = hudModel === 'auto' ? 'auto' : hudModel || serverModel || models[0]?.id || '';
  const claudeReady = !!automations.status?.claude.available;

  const addLog = useCallback((text: string, level: LogLine['level'] = 'info') => {
    setLog((l) => [...l.slice(-60), { id: ++logSeq, time: stamp(), text, level }]);
  }, []);

  // Cron routines follow the user's clock: report the browser timezone once.
  useEffect(() => {
    const tz = browserTimezone();
    if (tz) automationApi.setTimezone(tz).catch(() => {});
  }, []);

  // Announce routines that finish while the HUD is open.
  const voiceOutRef = useRef(true);
  const speakRef = useRef<(id: string, text: string) => void>(() => {});
  useRunFeed((run) => {
    addLog(`Routine "${run.name}" ${run.success ? 'complete' : 'failed'}`, run.success ? 'ok' : 'err');
    setMessages((ms) => [
      ...ms,
      {
        id: `run-${run.id}`,
        role: 'assistant',
        content: `[Routine · ${run.name}] ${run.success ? run.result || 'Done.' : `Failed: ${run.error}`}`,
      },
    ]);
    if (voiceOutRef.current) {
      const summary = run.success ? toSpeakableText(run.result).slice(0, 400) : 'It reported an error.';
      speakRef.current(`run-${run.id}`, `Routine ${run.name} ${run.success ? 'complete.' : 'failed.'} ${summary}`);
    }
    void automations.refresh();
  });
  speakRef.current = speakReply;
  voiceOutRef.current = voiceOut;

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

  const addFiles = useCallback(
    async (files: File[], source: 'upload' | 'paste' | 'drop' | 'screenshot') => {
      if (files.length === 0) return;
      setUploadingCount((n) => n + files.length);
      try {
        const res = await attachmentApi.upload(files, source);
        res.errors.forEach((e) => addLog(`${e.name}: ${e.error}`, 'err'));
        if (res.attachments.length) {
          setPending((p) => [...p, ...res.attachments.filter((a) => !p.some((x) => x.id === a.id))]);
          addLog(`Attached ${res.attachments.map((a) => a.name).join(', ')}`, 'ok');
        }
      } catch (e) {
        addLog(`Attach failed: ${e instanceof Error ? e.message : e}`, 'err');
      } finally {
        setUploadingCount((n) => Math.max(0, n - files.length));
      }
    },
    [addLog],
  );

  const takeScreenshot = useCallback(async () => {
    try {
      const shot = await captureScreenshot();
      await addFiles([shot], 'screenshot');
    } catch (e) {
      // Cancelling the browser's share picker is not an error worth shouting about.
      const msg = e instanceof Error ? e.message : String(e);
      addLog(/denied|abort|cancel/i.test(msg) ? 'Screenshot cancelled' : `Screenshot failed: ${msg}`, 'warn');
    }
  }, [addFiles, addLog]);

  // Refresh pending image chips until their descriptions are ready.
  useEffect(() => {
    if (!pending.some((a) => a.status === 'describing')) return;
    const t = setInterval(async () => {
      const updated = await Promise.all(
        pending.map((a) => (a.status === 'describing' ? attachmentApi.get(a.id).catch(() => a) : Promise.resolve(a))),
      );
      setPending((p) => p.map((a) => updated.find((u) => u.id === a.id) ?? a));
    }, 2000);
    return () => clearInterval(t);
  }, [pending]);

  // Paste images/files straight into the HUD.
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const files = Array.from(e.clipboardData?.files ?? []);
      if (files.length === 0) return;
      e.preventDefault();
      const named = files.map((f, i) =>
        f.name && f.name !== 'image.png'
          ? f
          : new File([f], `pasted-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}-${i + 1}.${(f.type.split('/')[1] || 'png').replace('jpeg', 'jpg')}`, { type: f.type }),
      );
      void addFiles(named, 'paste');
    };
    window.addEventListener('paste', onPaste);
    return () => window.removeEventListener('paste', onPaste);
  }, [addFiles]);

  const dragHandlers = {
    onDragEnter: (e: React.DragEvent) => {
      if (!e.dataTransfer.types.includes('Files')) return;
      e.preventDefault();
      dragDepth.current += 1;
      setDragActive(true);
    },
    onDragOver: (e: React.DragEvent) => {
      if (e.dataTransfer.types.includes('Files')) e.preventDefault();
    },
    onDragLeave: () => {
      dragDepth.current = Math.max(0, dragDepth.current - 1);
      if (dragDepth.current === 0) setDragActive(false);
    },
    onDrop: (e: React.DragEvent) => {
      if (!e.dataTransfer.files.length) return;
      e.preventDefault();
      dragDepth.current = 0;
      setDragActive(false);
      void addFiles(Array.from(e.dataTransfer.files), 'drop');
    },
  };

  const send = useCallback(async (raw: string) => {
    const attached = pending;
    const text = raw.trim() || (attached.length ? 'Please look at the attached file(s).' : '');
    if (!text || abortRef.current) return;
    if (!model) {
      addLog('No model available — pull one in Settings', 'err');
      return;
    }
    stopVoice();
    const userMsg: HudMessage = {
      id: uid(),
      role: 'user',
      content: text,
      files: attached.length ? attached.map((a) => a.name) : undefined,
    };
    const reply: HudMessage = { id: uid(), role: 'assistant', content: '' };
    const history = [...historyRef.current, userMsg];
    setMessages([...history, reply]);
    setInput('');
    setPending([]);
    setPhase('thinking');
    addLog(`> ${text.length > 48 ? text.slice(0, 48) + '…' : text}`);

    const controller = new AbortController();
    abortRef.current = controller;
    const started = performance.now();
    let content = '';
    let tokens = 0;
    let chunks = 0;
    let firstAt = 0;
    let routedTo = '';
    try {
      for await (const ev of streamChat(
        {
          model,
          stream: true,
          messages: [
            {
              role: 'system',
              content:
                'You are J.A.R.V.I.S., a concise, capable personal AI on the user\'s own PC. Keep replies short and conversational unless asked for detail. ' +
                'When tools are available you can: schedule recurring routines or reminders (schedule_task, list_scheduled_tasks), ' +
                'open websites (open_url), open apps (open_app), open files or folders (open_path), check the PC (system_status), ' +
                'run commands (run_pc_command) and hand coding or multi-step computer work to Claude Code (delegate_to_claude_code). ' +
                'Running commands and Claude Code tasks ask the user to approve on screen; say so briefly when you use them. ' +
                'Files and images the user attaches are added to their message (images as a description); ' +
                'earlier attachments can be found with list_attachments, read with read_attachment and kept long-term with save_attachment_to_knowledge.',
            },
            ...history.slice(-12).map((m) => ({ role: m.role, content: m.content })),
          ],
          attachments: attached.length ? attached.map((a) => a.id) : undefined,
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
          if (model === 'auto' && !routedTo && typeof data.model === 'string' && data.model) {
            routedTo = data.model;
            const toClaude = routedTo.startsWith('claude');
            addLog(`Routed → ${routedTo}${toClaude ? ' (Claude)' : ' (local)'}`, toClaude ? 'warn' : 'info');
          }
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
  }, [model, addLog, stopVoice, speakReply, voiceOut, pending]);

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
      if (e.key === 'Escape' && document.activeElement !== inputRef.current && !document.querySelector('.deck')) navigate('/');
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
    <div className={`hud hud--${mode}`} {...dragHandlers}>
      {dragActive && (
        <div className="hud-drop" aria-hidden="true">
          <div className="hud-drop__frame">
            DROP TO ATTACH
            <small>Documents, spreadsheets, code and images</small>
          </div>
        </div>
      )}
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
            <span>{model === 'auto' ? 'AUTO ROUTING' : model ? model.toUpperCase() : 'NO MODEL'}</span>
            <span className="hud-sep" />
            <span className={`hud-dot ${claudeReady ? 'on' : 'off'}`} />
            <span>{claudeReady ? 'CLAUDE LINKED' : 'CLAUDE OFFLINE'}</span>
          </div>
          <button type="button" className="hud-btn hud-btn--ghost hud-routines-btn" onClick={() => setDeckOpen(true)}>
            ROUTINES
            {automations.items.filter((a) => a.status === 'active').length > 0 && (
              <span className="hud-badge">{automations.items.filter((a) => a.status === 'active').length}</span>
            )}
          </button>
          <button type="button" className="hud-btn hud-btn--ghost" onClick={() => setVaultOpen(true)}>
            FILES
          </button>
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
            <button
              type="button"
              className={`hud-chip ${model === 'auto' ? 'is-active' : ''}`}
              onClick={() => { chooseModel('auto'); addLog('Smart routing: local for chat, Claude for hard tasks', 'ok'); }}
              title="Everyday requests stay local; complex, coding and automation requests go to Claude when it is linked."
            >
              <span className="hud-chip__dot" />
              AUTO · smart routing
            </button>
            {models.length === 0 && <p className="hud-muted">Scanning for models…</p>}
            {models.map((m) => (
              <button
                key={m.id}
                type="button"
                className={`hud-chip ${m.id === model ? 'is-active' : ''}`}
                onClick={() => { chooseModel(m.id); addLog(`Model switched to ${m.id}`, 'ok'); }}
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
                    {m.files && m.files.length > 0 && (
                      <span className="hud-msg__files">
                        {m.files.map((f) => <span key={f} className="hud-msg__file">📎 {f}</span>)}
                      </span>
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
          {(pending.length > 0 || uploadingCount > 0) && (
            <div className="hud-attach-tray" aria-label="Attached files">
              {pending.map((a) => (
                <span
                  key={a.id}
                  className={`att-chip ${a.status === 'describing' ? 'is-busy' : ''} ${a.status === 'failed' ? 'is-failed' : ''}`}
                  title={a.error || a.name}
                >
                  <span className="att-chip__icon">{a.kind === 'image' ? 'IMG' : a.kind === 'document' ? 'DOC' : 'TXT'}</span>
                  <span className="att-chip__name">{a.name}</span>
                  <span className="att-chip__state">
                    {a.status === 'describing' ? 'ANALYSING' : a.status === 'failed' ? 'UNREADABLE' : 'READY'}
                  </span>
                  <button
                    type="button"
                    className="att-chip__x"
                    aria-label={`Remove ${a.name}`}
                    onClick={() => setPending((p) => p.filter((x) => x.id !== a.id))}
                  >
                    ×
                  </button>
                </span>
              ))}
              {uploadingCount > 0 && (
                <span className="att-chip is-busy">
                  <span className="att-chip__name">Uploading {uploadingCount} file{uploadingCount > 1 ? 's' : ''}…</span>
                </span>
              )}
            </div>
          )}
          <input
            ref={fileInputRef}
            type="file"
            multiple
            hidden
            accept={ACCEPTED_FILES}
            onChange={(e) => {
              void addFiles(Array.from(e.target.files ?? []), 'upload');
              e.target.value = '';
            }}
          />
          <button
            type="button"
            className="hud-btn hud-btn--icon"
            onClick={() => fileInputRef.current?.click()}
            aria-label="Attach files"
            title="Attach files (or drop / paste them anywhere)"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M16.5 6.5v10a4.5 4.5 0 0 1-9 0V5a3 3 0 0 1 6 0v10.5a1.5 1.5 0 0 1-3 0V6.5H9V15.5a3 3 0 0 0 6 0V5a4.5 4.5 0 0 0-9 0v11.5a6 6 0 0 0 12 0v-10h-1.5Z" /></svg>
          </button>
          <button
            type="button"
            className="hud-btn hud-btn--icon"
            onClick={() => void takeScreenshot()}
            aria-label="Capture screen"
            title="Capture your screen (you choose what to share) and attach it"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h3l1.5-2h7L17 5h3a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Zm8 3.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9Zm0 2a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5Z" /></svg>
          </button>
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
            <button type="submit" className="hud-btn" disabled={!input.trim() && pending.length === 0}>
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

      <ApprovalDock
        onNew={(a) => {
          addLog(`Approval needed: ${a.description}`, 'warn');
          if (voiceOutRef.current) speakRef.current(`approval-${a.id}`, 'Authorisation required. Please approve or deny on screen.');
        }}
        onDecision={(a, approved) => addLog(`${approved ? 'Approved' : 'Denied'}: ${a.description}`, approved ? 'ok' : 'warn')}
      />

      <AttachmentsDeck
        open={vaultOpen}
        onClose={() => setVaultOpen(false)}
        onAttach={(a) => setPending((p) => (p.some((x) => x.id === a.id) ? p : [...p, a]))}
        onLog={addLog}
      />

      <AutomationsDeck
        open={deckOpen}
        onClose={() => setDeckOpen(false)}
        status={automations.status}
        items={automations.items}
        error={automations.error}
        refresh={automations.refresh}
        onLog={addLog}
      />
    </div>
  );
}
