/**
 * Jarvis's brain for the home screen: chat (one tab per question), voice in
 * and out, hands-free conversation, Malayalam, attachments, routines feed,
 * telemetry and the event log. The page only renders what this returns.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { streamChat } from '../../lib/sse';
import {
  checkHealth,
  fetchEnergy,
  fetchServerInfo,
  fetchTelemetry,
  transcribeAudio,
} from '../../lib/api';
import { stripThinkTags, toSpeakableText } from '../../lib/message-text';
import { useAppStore } from '../../lib/store';
import { useTts } from '../../hooks/useTts';
import { attachmentApi, captureScreenshot, type Attachment } from '../Hud/attachmentApi';
import { automationApi, browserTimezone, useAutomations, useRunFeed } from '../Hud/automationApi';
import {
  hasMalayalam,
  isSpeechLang,
  nextSpeechLang,
  pickMalayalamVoice,
  spokenReplySuffix,
  whisperLanguage,
  type SpeechLang,
} from '../Hud/speechLang';
import { createVoiceActivity } from '../Hud/voiceActivity';

export type JarvisMode = 'idle' | 'listening' | 'transcribing' | 'thinking' | 'speaking' | 'offline';
type Phase = 'idle' | 'listening' | 'transcribing' | 'thinking' | 'streaming';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  files?: string[];
}

export interface LogLine {
  id: number;
  time: string;
  text: string;
  level: 'info' | 'ok' | 'warn' | 'err';
}

export interface Telemetry {
  total_requests?: number;
  total_tokens?: number;
  avg_throughput_tok_per_sec?: number;
  avg_gpu_utilization_pct?: number;
}

export interface Energy {
  avg_power_w?: number;
  cpu_temp_c?: number | null;
  gpu_temp_c?: number | null;
}

const SYSTEM_PROMPT =
  "You are J.A.R.V.I.S., a concise, capable personal AI on the user's own PC. Keep replies short and conversational unless asked for detail. " +
  'When tools are available you can: schedule recurring routines or reminders (schedule_task, list_scheduled_tasks), ' +
  'track habits (add_habit, complete_habit, list_habits) and write journal entries (write_journal) on the home screen, ' +
  'open websites (open_url), open apps (open_app), open files or folders (open_path), check the PC (system_status), ' +
  'run commands (run_pc_command) and hand coding or multi-step computer work to Claude Code (delegate_to_claude_code). ' +
  'Running commands and Claude Code tasks ask the user to approve on screen; say so briefly when you use them. ' +
  'You have long-term memory: facts the user shares are saved automatically and remembered in future sessions, ' +
  'so when asked to remember something, confirm that you will (never claim you cannot remember). ' +
  'Files and images the user attaches are added to their message (images as a description); ' +
  'earlier attachments can be found with list_attachments, read with read_attachment and kept long-term with save_attachment_to_knowledge. ' +
  'Reply in the language the user uses; when they write or speak Malayalam, reply in Malayalam script.';

/** Plain text for the transcript (no markdown chrome). */
export const toChatText = (raw: string) =>
  stripThinkTags(raw)
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/(^|\s)[*_](\S.*?\S|\S)[*_](?=\s|$|[.,!?])/g, '$1$2')
    .replace(/^#{1,6}\s*/gm, '')
    .replace(/^\s*[-*]\s+/gm, '• ')
    .replace(/`{1,3}/g, '');

let logSeq = 0;
const stamp = () => new Date().toLocaleTimeString([], { hour12: false });
const uid = () => Math.random().toString(36).slice(2, 10);
const readPref = (key: string): string | null => {
  try { return localStorage.getItem(key); } catch { return null; }
};
const writePref = (key: string, value: string) => {
  try { localStorage.setItem(key, value); } catch { /* private mode */ }
};

/** Wait briefly for the browser's voice list (Edge loads it asynchronously). */
function loadVoices(synth: SpeechSynthesis): Promise<SpeechSynthesisVoice[]> {
  const now = synth.getVoices();
  if (now.length) return Promise.resolve(now);
  return new Promise((resolve) => {
    const done = () => { synth.removeEventListener('voiceschanged', done); resolve(synth.getVoices()); };
    synth.addEventListener('voiceschanged', done);
    window.setTimeout(done, 1500);
  });
}

export function useJarvis() {
  const models = useAppStore((s) => s.models);
  const tts = useTts();
  const automations = useAutomations(true);

  // ---- settings -----------------------------------------------------------------
  const [hudModel, setHudModel] = useState<string>(() => readPref('oj-hud-model') || 'auto');
  const chooseModel = useCallback((id: string) => { setHudModel(id); writePref('oj-hud-model', id); }, []);
  const [voiceOut, setVoiceOut] = useState(true);
  const [speechLang, setSpeechLang] = useState<SpeechLang>(() => {
    const saved = readPref('oj-hud-speech-lang');
    return isSpeechLang(saved) ? saved : 'auto';
  });
  const [handsFree, setHandsFree] = useState(() => readPref('oj-hud-hands-free') === '1');
  useEffect(() => { writePref('oj-hud-speech-lang', speechLang); }, [speechLang]);
  useEffect(() => { writePref('oj-hud-hands-free', handsFree ? '1' : '0'); }, [handsFree]);
  const speechLangRef = useRef(speechLang);
  speechLangRef.current = speechLang;
  const handsFreeRef = useRef(handsFree);
  handsFreeRef.current = handsFree;

  // ---- state -----------------------------------------------------------------
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [log, setLog] = useState<LogLine[]>([]);
  const [online, setOnline] = useState(true);
  const [serverModel, setServerModel] = useState('');
  const [stats, setStats] = useState<Telemetry>({});
  const [energy, setEnergy] = useState<Energy>({});
  const [phase, setPhase] = useState<Phase>('idle');
  const [lastTps, setLastTps] = useState(0);
  const [replyCount, setReplyCount] = useState(0);
  const [browserSpeaking, setBrowserSpeaking] = useState(false);
  const [pending, setPending] = useState<Attachment[]>([]);
  const [uploadingCount, setUploadingCount] = useState(0);
  const [activeTab, setActiveTab] = useState<string | null>(null);
  const speaking = tts.isSpeaking || browserSpeaking;

  const levelRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const speechPollRef = useRef(0);
  const historyRef = useRef<ChatMessage[]>([]);
  historyRef.current = messages;

  const model = hudModel === 'auto' ? 'auto' : hudModel || serverModel || models[0]?.id || '';
  const claudeReady = !!automations.status?.claude.available;
  const gptReady = !!automations.status?.openai?.available;

  const addLog = useCallback((text: string, level: LogLine['level'] = 'info') => {
    setLog((l) => [...l.slice(-60), { id: ++logSeq, time: stamp(), text, level }]);
  }, []);

  // ---- voice out -----------------------------------------------------------------
  const stopVoice = useCallback(() => {
    tts.stop();
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    window.clearInterval(speechPollRef.current);
    setBrowserSpeaking(false);
  }, [tts]);

  const speak = useCallback(async (id: string, text: string) => {
    // Kokoro has no Malayalam voice; Edge's natural Malayalam voices do.
    const malayalam = hasMalayalam(text);
    if (tts.available && !malayalam) { void tts.speak(id, text); return; }
    if (!('speechSynthesis' in window)) return;
    const synth = window.speechSynthesis;
    setBrowserSpeaking(true);
    const voices = await loadVoices(synth);
    const u = new SpeechSynthesisUtterance(text);
    if (malayalam) {
      u.lang = 'ml-IN';
      u.voice = pickMalayalamVoice(voices);
      if (!u.voice) addLog('No Malayalam voice in this browser - open Jarvis in Microsoft Edge', 'warn');
    } else {
      u.voice =
        voices.find((v) => /en-GB/i.test(v.lang) && /male|george|ryan|daniel|thomas/i.test(v.name)) ||
        voices.find((v) => /en-GB/i.test(v.lang)) ||
        voices.find((v) => v.lang.startsWith('en')) ||
        null;
      u.rate = 1.03;
      u.pitch = 0.9;
    }
    synth.cancel();
    synth.speak(u);
    window.clearInterval(speechPollRef.current);
    speechPollRef.current = window.setInterval(() => {
      if (!synth.speaking && !synth.pending) {
        window.clearInterval(speechPollRef.current);
        setBrowserSpeaking(false);
      }
    }, 250);
  }, [tts, addLog]);

  const voiceOutRef = useRef(voiceOut);
  voiceOutRef.current = voiceOut;
  const speakRef = useRef(speak);
  speakRef.current = speak;
  /** Speak a notice (routine finished, approval needed) if voice is on. */
  const announce = useCallback((id: string, text: string) => {
    if (voiceOutRef.current) void speakRef.current(id, text);
  }, []);

  // ---- tabs: every question opens its own tab ----------------------------------------
  const tabs = useMemo(() => {
    const list: { id: string; label: string; msgs: ChatMessage[] }[] = [];
    for (const m of messages) {
      if (m.role === 'user') {
        list.push({ id: m.id, label: m.content.length > 24 ? `${m.content.slice(0, 24)}…` : m.content, msgs: [m] });
      } else if (list.length > 0) {
        list[list.length - 1].msgs.push(m);
      }
    }
    return list;
  }, [messages]);
  const currentTab = tabs.find((t) => t.id === activeTab) ?? tabs[tabs.length - 1];
  const closeTab = useCallback((id: string) => {
    const tab = tabs.find((t) => t.id === id);
    if (!tab) return;
    const drop = new Set(tab.msgs.map((m) => m.id));
    setMessages((ms) => ms.filter((m) => !drop.has(m.id)));
    setActiveTab((a) => (a === id ? null : a));
  }, [tabs]);

  // ---- routines, timezone, telemetry ------------------------------------------------
  useEffect(() => {
    const tz = browserTimezone();
    if (tz) automationApi.setTimezone(tz).catch(() => {});
  }, []);

  useRunFeed((run) => {
    addLog(`Routine "${run.name}" ${run.success ? 'complete' : 'failed'}`, run.success ? 'ok' : 'err');
    setMessages((ms) => [
      ...ms,
      { id: `run-${run.id}`, role: 'assistant', content: `[Routine · ${run.name}] ${run.success ? run.result || 'Done.' : `Failed: ${run.error}`}` },
    ]);
    const summary = run.success ? toSpeakableText(run.result).slice(0, 400) : 'It reported an error.';
    announce(`run-${run.id}`, `Routine ${run.name} ${run.success ? 'complete.' : 'failed.'} ${summary}`);
    void automations.refresh();
  });

  const wasOnlineRef = useRef<boolean | null>(null);
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      const ok = await checkHealth();
      if (cancelled) return;
      setOnline(ok);
      if (wasOnlineRef.current !== ok) {
        addLog(ok ? 'Jarvis is online' : 'Jarvis core unreachable', ok ? 'ok' : 'err');
        wasOnlineRef.current = ok;
      }
      if (!ok) return;
      fetchTelemetry().then((s) => !cancelled && setStats(s as Telemetry)).catch(() => {});
      fetchEnergy().then((e) => !cancelled && setEnergy(e as Energy)).catch(() => {});
    };
    fetchServerInfo().then((i) => { if (!cancelled) setServerModel(i.model); }).catch(() => {});
    void poll();
    const t = setInterval(poll, 5000);
    return () => { cancelled = true; clearInterval(t); };
  }, [addLog]);

  // ---- attachments ---------------------------------------------------------------
  const addFiles = useCallback(async (files: File[], source: 'upload' | 'paste' | 'drop' | 'screenshot') => {
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
  }, [addLog]);

  const takeScreenshot = useCallback(async () => {
    try {
      await addFiles([await captureScreenshot()], 'screenshot');
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      addLog(/denied|abort|cancel/i.test(msg) ? 'Screenshot cancelled' : `Screenshot failed: ${msg}`, 'warn');
    }
  }, [addFiles, addLog]);

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

  // ---- chat -----------------------------------------------------------------
  const send = useCallback(async (raw: string, opts: { spoken?: boolean } = {}) => {
    const attached = pending;
    const text = raw.trim() || (attached.length ? 'Please look at the attached file(s).' : '');
    if (!text || abortRef.current) return;
    if (!model) { addLog('No model available - pull one in Settings', 'err'); return; }
    stopVoice();
    const userMsg: ChatMessage = { id: uid(), role: 'user', content: text, files: attached.length ? attached.map((a) => a.name) : undefined };
    const reply: ChatMessage = { id: uid(), role: 'assistant', content: '' };
    const history = [...historyRef.current, userMsg];
    setMessages([...history, reply]);
    setActiveTab(userMsg.id);
    setInput('');
    setPending([]);
    setPhase('thinking');
    addLog(`> ${text.length > 48 ? `${text.slice(0, 48)}…` : text}`);

    const controller = new AbortController();
    abortRef.current = controller;
    const started = performance.now();
    let content = '';
    let tokens = 0;
    let chunks = 0;
    let routedTo = '';
    try {
      for await (const ev of streamChat(
        {
          model,
          stream: true,
          messages: [
            { role: 'system', content: SYSTEM_PROMPT },
            ...history.slice(-12).map((m) => ({
              role: m.role,
              content: opts.spoken && m.id === userMsg.id ? m.content + spokenReplySuffix(speechLangRef.current, m.content) : m.content,
            })),
          ],
          attachments: attached.length ? attached.map((a) => a.id) : undefined,
        },
        controller.signal,
      )) {
        if (ev.event === 'tool_call_start') {
          try { addLog(`Using ${JSON.parse(ev.data).tool}`, 'warn'); } catch { /* ignore */ }
          continue;
        }
        if (ev.event === 'tool_call_end') {
          try { const d = JSON.parse(ev.data); addLog(`${d.tool} ${d.success ? 'done' : 'failed'}`, d.success ? 'ok' : 'err'); } catch { /* ignore */ }
          continue;
        }
        if (ev.event) continue;
        try {
          const data = JSON.parse(ev.data);
          if (model === 'auto' && !routedTo && typeof data.model === 'string' && data.model) {
            routedTo = data.model;
            addLog(`Answering with ${routedTo}`, routedTo.startsWith('claude') || routedTo.startsWith('gpt') ? 'warn' : 'info');
          }
          const delta = data.choices?.[0]?.delta?.content;
          if (delta) {
            if (!chunks) setPhase('streaming');
            content += delta;
            chunks++;
            const shown = toChatText(content);
            setMessages((ms) => ms.map((m) => (m.id === reply.id ? { ...m, content: shown } : m)));
          }
          if (data.usage?.completion_tokens) tokens = data.usage.completion_tokens;
          if (data.choices?.[0]?.finish_reason === 'stop') break;
        } catch { /* keep streaming */ }
      }
      const secs = (performance.now() - started) / 1000;
      if (!tokens) tokens = chunks > 1 ? chunks : Math.round(content.length / 4);
      setLastTps(secs > 0 ? tokens / secs : 0);
      addLog(`Replied in ${secs.toFixed(1)}s`, 'ok');
      const final = stripThinkTags(content).trim();
      if (!final) {
        setMessages((ms) => ms.map((m) => (m.id === reply.id ? { ...m, content: '(no response)' } : m)));
      } else if (voiceOutRef.current) {
        void speak(reply.id, toSpeakableText(final));
      }
    } catch (err) {
      const aborted = (err as Error)?.name === 'AbortError';
      addLog(aborted ? 'Stopped' : `Error: ${(err as Error).message}`, aborted ? 'warn' : 'err');
      setMessages((ms) => ms.map((m) => (m.id === reply.id
        ? { ...m, content: stripThinkTags(content) || (aborted ? '(stopped)' : 'Could not reach Jarvis.') }
        : m)));
    } finally {
      abortRef.current = null;
      levelRef.current = 0;
      setPhase('idle');
      setReplyCount((n) => n + 1);
    }
  }, [model, addLog, stopVoice, speak, pending]);

  const abort = useCallback(() => abortRef.current?.abort(), []);

  // ---- voice in ---------------------------------------------------------------
  const stopReasonRef = useRef<'manual' | 'pause' | 'discard'>('manual');
  const stopRecorder = (reason: 'manual' | 'pause' | 'discard') => {
    const rec = recorderRef.current;
    recorderRef.current = null;
    stopReasonRef.current = reason;
    if (rec && rec.state === 'recording') rec.stop();
  };
  const closeAudio = () => {
    levelRef.current = 0;
    audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;
  };

  const startListening = useCallback(async () => {
    if (recorderRef.current) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      addLog('Microphone not supported here', 'err');
      setHandsFree(false);
      return;
    }
    try {
      stopVoice();
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      streamRef.current = stream;
      const ctx = new AudioContext();
      audioCtxRef.current = ctx;
      const source = ctx.createMediaStreamSource(stream);
      // Voice activity runs on the audio callback so it works in a background tab.
      const vad = createVoiceActivity();
      const meter = ctx.createScriptProcessor(1024, 1, 1);
      const mute = ctx.createGain();
      mute.gain.value = 0;
      source.connect(meter);
      meter.connect(mute);
      mute.connect(ctx.destination);
      meter.onaudioprocess = (e) => {
        const data = e.inputBuffer.getChannelData(0);
        let sum = 0;
        for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
        const level = Math.min(1, Math.sqrt(sum / data.length) * 4);
        levelRef.current = level;
        const event = vad.update(level, performance.now());
        if (event === 'speech-end') stopRecorder('pause');
        else if (event === 'timeout') stopRecorder('discard');
      };

      const chunks: Blob[] = [];
      const rec = new MediaRecorder(stream);
      rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
      rec.onstop = async () => {
        meter.onaudioprocess = null;
        stream.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        closeAudio();
        const reason = stopReasonRef.current;
        if (reason === 'discard' || (reason === 'pause' && !vad.heardSpeech())) {
          setPhase('idle');
          return;
        }
        setPhase('transcribing');
        try {
          const blob = new Blob(chunks, { type: rec.mimeType || 'audio/webm' });
          const result = await transcribeAudio(blob, 'recording.webm', whisperLanguage(speechLangRef.current));
          const heard = result.text.trim();
          setPhase('idle');
          if (heard) {
            addLog(`Heard: "${heard.slice(0, 40)}"`, 'ok');
            void send(heard, { spoken: true });
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
      stopReasonRef.current = 'manual';
      setPhase('listening');
    } catch {
      addLog('Microphone access denied', 'err');
      setHandsFree(false);
      closeAudio();
      setPhase('idle');
    }
  }, [addLog, send, stopVoice]);

  const stopListening = useCallback(() => stopRecorder('manual'), []);

  // Hands-free: once Jarvis is idle and silent again, listen for the next turn.
  useEffect(() => {
    if (!handsFree || phase !== 'idle' || speaking || tts.isLoading || abortRef.current) return;
    const t = window.setTimeout(() => {
      if (handsFreeRef.current && !recorderRef.current) void startListening();
    }, 350);
    return () => window.clearTimeout(t);
  }, [handsFree, phase, speaking, tts.isLoading, startListening]);

  const toggleHandsFree = useCallback(() => {
    const on = handsFreeRef.current;
    if (on && recorderRef.current) stopRecorder('discard');
    addLog(on ? 'Hands-free off' : 'Hands-free on: talk any time, I send when you pause', on ? 'info' : 'ok');
    setHandsFree(!on);
  }, [addLog]);

  const cycleLanguage = useCallback(() => setSpeechLang((l) => nextSpeechLang(l)), []);

  // Simulated level while Jarvis speaks (drives the orb animation).
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

  useEffect(() => () => {
    abortRef.current?.abort();
    recorderRef.current?.stop();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    audioCtxRef.current?.close().catch(() => {});
    window.clearInterval(speechPollRef.current);
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
  }, []);

  const mode: JarvisMode = useMemo(() => {
    if (phase === 'listening') return 'listening';
    if (phase === 'transcribing') return 'transcribing';
    if (phase === 'thinking') return 'thinking';
    if (phase === 'streaming' || speaking || tts.isLoading) return 'speaking';
    if (!online) return 'offline';
    return 'idle';
  }, [phase, speaking, tts.isLoading, online]);

  /** One button for everything: talk, stop listening, stop thinking, hush. */
  const activate = useCallback(() => {
    if (mode === 'listening') return stopListening();
    if (mode === 'thinking' || phase === 'streaming') { abort(); return; }
    if (speaking || tts.isLoading) { stopVoice(); return; }
    if (mode === 'transcribing') return;
    void startListening();
  }, [mode, phase, speaking, tts.isLoading, stopVoice, startListening, stopListening, abort]);

  const lastReplyId = [...messages].reverse().find((m) => m.role === 'assistant')?.id;

  return {
    // chat
    messages, tabs, currentTab, setActiveTab, closeTab, input, setInput, send, abort, lastReplyId, replyCount,
    // state
    mode, phase, busy: phase !== 'idle', online, levelRef, log, addLog,
    // models
    model, hudModel, chooseModel, models, claudeReady, gptReady, automations,
    // voice
    voiceOut, setVoiceOut, stopVoice, announce, handsFree, toggleHandsFree,
    speechLang, cycleLanguage, startListening, stopListening, activate,
    // attachments
    pending, setPending, uploadingCount, addFiles, takeScreenshot,
    // telemetry
    stats, energy, lastTps,
  };
}

export type Jarvis = ReturnType<typeof useJarvis>;
