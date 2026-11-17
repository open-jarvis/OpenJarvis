import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { checkHealth, fetchModels, fetchServerInfo, fetchTtsHealth, transcribeAudio } from '../lib/api';
import { stripThinkTags, toSpeakableText } from '../lib/message-text';
import { streamChat } from '../lib/sse';
import { useAppStore } from '../lib/store';
import { buildWsProtocols, buildWsUrl } from '../lib/useAgentEvents';
import type { AgentEvent } from '../lib/useAgentEvents';
import { BrowserSpeechQueue } from '../lib/hud/browser-speech-queue';
import { SpeechQueue } from '../lib/hud/speech-queue';
import type { SpeechQueueCallbacks, VoiceOutput } from '../lib/hud/speech-queue';
import { createSentenceSplitter, matchWakeWord } from '../lib/hud/speech-text';
import { buildAnswerCard, buildToolCard, describeToolCall } from '../lib/hud/tool-cards';
import type { HudCard } from '../lib/hud/tool-cards';
import { useVoiceActivity } from './useVoiceActivity';

export type HudPhase = 'standby' | 'idle' | 'hearing' | 'transcribing' | 'thinking' | 'speaking';

export interface ActivityEntry {
  id: string;
  timestamp: number;
  kind: 'tool' | 'inference' | 'ignored' | 'error';
  label: string;
  status: 'running' | 'ok' | 'error';
  /** Segundos que tardó, cuando se conoce. */
  latency?: number;
}

export interface InferenceStats {
  latencyS?: number;
  ttftS?: number;
  tokensPerSec?: number;
  powerW?: number;
  totalTokens?: number;
}

const MAX_ACTIVITY_ENTRIES = 40;
const MAX_CARDS = 6;
/** Mensajes previos que se envían como contexto de la conversación. */
const MAX_CONTEXT_MESSAGES = 12;
/** Tras una respuesta se puede seguir hablando sin repetir "Jarvis". */
const FOLLOW_UP_WINDOW_MS = 8000;
/** Margen tras la voz de Jarvis en el que su propio eco no cuenta como respuesta. */
const ECHO_GUARD_MS = 700;
/** Mientras Jarvis habla, solo una voz claramente más fuerte lo interrumpe. */
const SPEAKING_SENSITIVITY_FACTOR = 3;
const GREETING = 'Sistemas en línea, señor.';
const ACKNOWLEDGEMENT = '¿Sí, señor?';

/** Cada cuánto se comprueba que el servidor responde. */
const HEALTH_POLL_MS = 4000;
const SERVER_UNREACHABLE = 'Sin conexión con el servidor de Jarvis';

let idCounter = 0;
const nextId = (prefix: string) => `${prefix}-${Date.now()}-${(idCounter += 1)}`;

/**
 * Texto de error para el registro. `fetch` rechaza con TypeError ("Failed to
 * fetch") cuando no hubo respuesta: el servidor está apagado o se cayó.
 */
function describeError(error: unknown): string {
  if (error instanceof TypeError) return SERVER_UNREACHABLE;
  return error instanceof Error ? error.message : String(error);
}

/** Extrae el texto nuevo de un fragmento de `chat.completion.chunk`. */
function parseContentDelta(data: string): string {
  try {
    const content = JSON.parse(data)?.choices?.[0]?.delta?.content;
    return typeof content === 'string' ? content : '';
  } catch {
    return '';
  }
}

/**
 * Se suscribe a todos los eventos del agente (herramientas e inferencia).
 * `useAgentEvents` exige filtrar por un agente; el HUD necesita el flujo
 * completo, así que abre su propio socket reutilizando la URL y la autenticación.
 */
function subscribeAgentEvents(onEvent: (event: AgentEvent) => void): () => void {
  let socket: WebSocket | null = null;
  let closed = false;
  let retries = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;

  const scheduleReconnect = () => {
    if (closed) return;
    timer = setTimeout(connect, Math.min(30000, 1000 * 2 ** Math.min(retries, 5)));
    retries += 1;
  };
  const connect = () => {
    if (closed) return;
    try {
      socket = new WebSocket(buildWsUrl(), buildWsProtocols());
    } catch {
      scheduleReconnect();
      return;
    }
    socket.onopen = () => {
      retries = 0;
    };
    socket.onmessage = (message) => {
      try {
        onEvent(JSON.parse(message.data) as AgentEvent);
      } catch {
        // Mensaje con formato inesperado: se ignora.
      }
    };
    socket.onclose = scheduleReconnect;
    socket.onerror = () => socket?.close();
  };
  connect();

  return () => {
    closed = true;
    if (timer) clearTimeout(timer);
    socket?.close();
  };
}

/**
 * Sesión de voz del HUD: escucha, decide si la frase va dirigida a Jarvis,
 * consulta al agente, dice la respuesta y registra lo que el agente hizo.
 */
export function useHudSession() {
  const selectedModel = useAppStore((s) => s.selectedModel);
  const serverModel = useAppStore((s) => s.serverInfo?.model);
  // Primero el modelo del servidor: es el que se configura para Jarvis. La
  // selección del chat puede apuntar a otro (por ejemplo, uno local y lento).
  const model = serverModel || selectedModel || '';
  const setServerInfo = useAppStore((s) => s.setServerInfo);
  const setModels = useAppStore((s) => s.setModels);
  /** null mientras no se ha comprobado. */
  const [serverOnline, setServerOnline] = useState<boolean | null>(null);

  const [audioContext, setAudioContext] = useState<AudioContext | null>(null);
  /** Descripción de la voz activa para el panel; vacía si Jarvis solo escribe. */
  const [voiceOutput, setVoiceOutput] = useState('');
  const [requestActive, setRequestActive] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [heardText, setHeardText] = useState('');
  const [caption, setCaption] = useState('');
  const [activity, setActivity] = useState<ActivityEntry[]>([]);
  const [cards, setCards] = useState<HudCard[]>([]);
  const [stats, setStats] = useState<InferenceStats>({});

  const speechQueueRef = useRef<VoiceOutput | null>(null);
  const messagesRef = useRef<Array<{ role: string; content: string }>>([]);
  const abortRef = useRef<AbortController | null>(null);
  const transcriptionChainRef = useRef<Promise<void>>(Promise.resolve());
  // Copias en refs: los manejadores de audio y red no deben quedar con valores viejos.
  const busyRef = useRef(false);
  const followUpUntilRef = useRef(0);
  const speechEndedAtRef = useRef(0);
  const modelRef = useRef(model);
  modelRef.current = model;
  busyRef.current = speaking || requestActive;

  const addActivity = useCallback((entry: Omit<ActivityEntry, 'id' | 'timestamp'>) => {
    const full = { ...entry, id: nextId('act'), timestamp: Date.now() };
    setActivity((entries) => {
      // Las frases ignoradas no se acumulan: solo se conserva la última.
      const rest = entry.kind === 'ignored' && entries[0]?.kind === 'ignored' ? entries.slice(1) : entries;
      return [full, ...rest].slice(0, MAX_ACTIVITY_ENTRIES);
    });
  }, []);

  const addCard = useCallback((card: HudCard | null) => {
    if (card) setCards((current) => [card, ...current].slice(0, MAX_CARDS));
  }, []);

  const dismissCard = useCallback((id: string) => {
    setCards((current) => current.filter((card) => card.id !== id));
  }, []);

  /** Corta la voz y la consulta en curso (interrupción). */
  const interrupt = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    speechQueueRef.current?.stop();
    setRequestActive(false);
  }, []);

  const submit = useCallback(
    async (text: string) => {
      const command = text.trim();
      if (!command) return;
      if (!modelRef.current) {
        // La página pudo cargarse con el servidor apagado: se pregunta otra vez.
        const info = await fetchServerInfo().catch(() => null);
        if (info?.model) {
          setServerInfo(info);
          modelRef.current = info.model;
        } else {
          addActivity({
            kind: 'error',
            label: info ? 'El servidor no tiene un modelo configurado' : SERVER_UNREACHABLE,
            status: 'error',
          });
          return;
        }
      }

      interrupt();
      const controller = new AbortController();
      abortRef.current = controller;
      setHeardText(command);
      setCaption('');
      setRequestActive(true);

      const history = [...messagesRef.current, { role: 'user', content: command }].slice(
        -MAX_CONTEXT_MESSAGES,
      );
      messagesRef.current = history;

      const splitter = createSentenceSplitter();
      const say = (sentences: string[]) =>
        sentences.forEach((sentence) => speechQueueRef.current?.enqueue(sentence));
      let answer = '';

      try {
        const request = { model: modelRef.current, messages: history, stream: true as const };
        for await (const event of streamChat(request, controller.signal)) {
          // Los eventos con nombre (herramientas) llegan también por el WebSocket.
          if (event.event) continue;
          const delta = parseContentDelta(event.data);
          if (!delta) continue;
          answer += delta;
          say(splitter.push(delta));
          if (!speechQueueRef.current) setCaption(toSpeakableText(answer));
        }
        say(splitter.flush());
      } catch (error) {
        if (!controller.signal.aborted) {
          addActivity({ kind: 'error', label: `Consulta fallida · ${describeError(error)}`, status: 'error' });
          setCaption('No pude completar la solicitud, señor.');
        }
      } finally {
        // Solo la consulta vigente apaga el indicador; una interrumpida ya fue reemplazada.
        if (abortRef.current === controller) {
          abortRef.current = null;
          setRequestActive(false);
        }
      }
      if (controller.signal.aborted || !answer) return;

      const visibleAnswer = stripThinkTags(answer);
      messagesRef.current = [...messagesRef.current, { role: 'assistant', content: visibleAnswer }];
      addCard(buildAnswerCard(nextId('answer'), visibleAnswer, Date.now(), command));
      if (!speechQueueRef.current) followUpUntilRef.current = Date.now() + FOLLOW_UP_WINDOW_MS;
    },
    [addActivity, addCard, interrupt, setServerInfo],
  );

  /** Decide qué hacer con una frase ya transcrita. */
  const routeTranscript = useCallback(
    (transcript: string, manual: boolean, capturedWhileBusy: boolean) => {
      if (!transcript) return;
      if (manual) {
        void submit(transcript);
        return;
      }
      const wake = matchWakeWord(transcript);
      if (wake.matched) {
        if (wake.command) {
          void submit(wake.command);
        } else {
          // Solo dijo el nombre: Jarvis se calla, responde y espera la orden.
          interrupt();
          setHeardText('Jarvis');
          setCaption(ACKNOWLEDGEMENT);
          followUpUntilRef.current = Date.now() + FOLLOW_UP_WINDOW_MS;
          speechQueueRef.current?.enqueue(ACKNOWLEDGEMENT);
        }
        return;
      }
      if (!capturedWhileBusy && Date.now() < followUpUntilRef.current) {
        void submit(transcript);
        return;
      }
      addActivity({ kind: 'ignored', label: `Sin "Jarvis" · ${transcript}`, status: 'ok' });
    },
    [addActivity, interrupt, submit],
  );

  const handleUtterance = useCallback(
    (wav: Blob, manual: boolean) => {
      // Lo captado mientras Jarvis hablaba (o justo después) puede ser su eco:
      // solo se acepta si trae la palabra de activación.
      const capturedWhileBusy =
        busyRef.current || Date.now() - speechEndedAtRef.current < ECHO_GUARD_MS;
      // Las frases se transcriben en orden, una a la vez.
      transcriptionChainRef.current = transcriptionChainRef.current.then(async () => {
        setTranscribing(true);
        try {
          const { text } = await transcribeAudio(wav, 'utterance.wav');
          routeTranscript(text.trim(), manual, capturedWhileBusy);
        } catch (error) {
          addActivity({
            kind: 'error',
            label: `Transcripción fallida · ${describeError(error)}`,
            status: 'error',
          });
        } finally {
          setTranscribing(false);
        }
      });
    },
    [addActivity, routeTranscript],
  );

  const voice = useVoiceActivity({
    audioContext,
    sensitivityFactor: speaking ? SPEAKING_SENSITIVITY_FACTOR : 1,
    onUtterance: handleUtterance,
  });

  /** Debe llamarse desde un clic: el navegador exige un gesto para audio y micrófono. */
  const activate = useCallback(async () => {
    if (audioContext) return;
    const context = new AudioContext();
    await context.resume();

    const callbacks: SpeechQueueCallbacks = {
      onSentenceStart: setCaption,
      onSpeakingChange: (isSpeaking) => {
        setSpeaking(isSpeaking);
        if (!isSpeaking) {
          speechEndedAtRef.current = Date.now();
          followUpUntilRef.current = Date.now() + FOLLOW_UP_WINDOW_MS;
        }
      },
      onError: (message) =>
        addActivity({ kind: 'error', label: `Voz no disponible · ${message}`, status: 'error' }),
    };

    // Primero la voz del navegador: gratis, instantánea y sin gastar memoria
    // del servidor. La del servidor (Kokoro, ElevenLabs…) queda de respaldo.
    const browserVoice = await BrowserSpeechQueue.create(callbacks);
    if (browserVoice) {
      speechQueueRef.current = browserVoice;
      setVoiceOutput(`NAVEGADOR · ${browserVoice.voice.name}`);
    } else {
      const tts = await fetchTtsHealth().catch(() => ({ available: false, backend: undefined }));
      if (tts.available) {
        speechQueueRef.current = new SpeechQueue(context, callbacks);
        setVoiceOutput(`SERVIDOR · ${tts.backend ?? ''}`.trim());
      }
    }
    if (speechQueueRef.current) speechQueueRef.current.enqueue(GREETING);
    else setCaption(GREETING);
    setAudioContext(context);
  }, [addActivity, audioContext]);

  const deactivate = useCallback(() => {
    interrupt();
    speechQueueRef.current = null;
    void audioContext?.close();
    setAudioContext(null);
    setVoiceOutput('');
    setSpeaking(false);
    setCaption('');
    setHeardText('');
  }, [audioContext, interrupt]);

  // Al salir de la pantalla se liberan el micrófono y el audio.
  const audioContextRef = useRef(audioContext);
  audioContextRef.current = audioContext;
  useEffect(
    () => () => {
      abortRef.current?.abort();
      speechQueueRef.current?.stop();
      void audioContextRef.current?.close();
    },
    [],
  );

  // Actividad en vivo del agente: herramientas e inferencia.
  useEffect(() => {
    const runningTools = new Map<string, string[]>();

    return subscribeAgentEvents(({ type, data }) => {
      const tool = typeof data.tool === 'string' ? data.tool : '';

      if (type === 'tool_call_start' && tool) {
        const args = (data.arguments ?? {}) as Record<string, unknown>;
        const id = nextId('tool');
        runningTools.set(tool, [...(runningTools.get(tool) ?? []), id]);
        setActivity((entries) =>
          [
            {
              id,
              timestamp: Date.now(),
              kind: 'tool' as const,
              label: describeToolCall(tool, args),
              status: 'running' as const,
            },
            ...entries,
          ].slice(0, MAX_ACTIVITY_ENTRIES),
        );
      } else if (type === 'tool_call_end' && tool) {
        // El fin no trae identificador: cierra la llamada más antigua de esa herramienta.
        const id = runningTools.get(tool)?.shift();
        const success = data.success === true;
        const latency = typeof data.latency === 'number' ? data.latency : undefined;
        setActivity((entries) =>
          entries.map((entry) =>
            entry.id === id ? { ...entry, status: success ? 'ok' : 'error', latency } : entry,
          ),
        );
        const metadata = (data.metadata ?? {}) as { arguments?: Record<string, unknown> };
        addCard(
          buildToolCard({
            id: id ?? nextId('tool'),
            timestamp: Date.now(),
            tool,
            args: metadata.arguments ?? {},
            result: typeof data.result === 'string' ? data.result : JSON.stringify(data.result ?? ''),
            success,
            latency,
          }),
        );
      } else if (type === 'inference_end' && typeof data.latency === 'number') {
        // De los dos eventos de fin de inferencia, este es el que trae las métricas.
        const usage = (data.usage ?? {}) as { total_tokens?: number };
        const number = (value: unknown) => (typeof value === 'number' ? value : undefined);
        setStats({
          latencyS: data.latency,
          ttftS: number(data.ttft),
          tokensPerSec: number(data.throughput_tok_per_sec),
          powerW: number(data.power_watts),
          totalTokens: number(usage.total_tokens),
        });
      }
    });
  }, [addCard]);

  // Si la página cargó antes que el servidor, las consultas iniciales de la app
  // fallaron sin reintento; aquí se repiten en cuanto el servidor responde.
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      const online = await checkHealth();
      if (cancelled) return;
      setServerOnline(online);
      if (online && !modelRef.current) {
        fetchServerInfo().then((info) => !cancelled && setServerInfo(info)).catch(() => {});
        fetchModels().then((models) => !cancelled && setModels(models)).catch(() => {});
      }
    };
    void poll();
    const timer = setInterval(poll, HEALTH_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [setModels, setServerInfo]);

  const active = audioContext !== null;
  const phase: HudPhase = useMemo(() => {
    if (!active) return 'standby';
    if (voice.isHearing) return 'hearing';
    if (transcribing) return 'transcribing';
    if (speaking) return 'speaking';
    if (requestActive) return 'thinking';
    return 'idle';
  }, [active, voice.isHearing, transcribing, speaking, requestActive]);

  /** Nivel de audio que anima el núcleo: la voz de Jarvis o el micrófono. */
  const getMicLevel = voice.getLevel;
  const getLevel = useCallback(
    () => speechQueueRef.current?.getLevel() || getMicLevel(),
    [getMicLevel],
  );

  return {
    phase,
    active,
    serverOnline,
    model,
    micStatus: voice.status,
    voiceOutput,
    heardText,
    caption,
    activity,
    cards,
    stats,
    getLevel,
    activate,
    deactivate,
    submit,
    interrupt,
    dismissCard,
    startPushToTalk: voice.startManual,
    stopPushToTalk: voice.stopManual,
  };
}
