import { useCallback, useEffect, useRef, useState } from 'react';
import { synthesizeSpeech, transcribeAudio } from '../lib/api';
import { NO_AUDIO_MESSAGE, blockPeak } from '../lib/mic-level';
import { ReplySpeaker } from '../lib/voice/reply-speaker';
import { UtteranceDetector } from '../lib/voice/utterance-detector';
import { encodeUtteranceWav } from '../lib/voice/wav';
import {
  isDismissal,
  isLikelyHallucination,
  isStopCommand,
  parseWakeCommand,
} from '../lib/voice/wake-word';

/**
 * Hands-free voice mode: talk to the assistant by name, no clicks.
 *
 * - sleeping:  the mic is open, but only utterances that start (or end) with
 *              the wake word are acted on.
 * - listening: the assistant is waiting for a question without the wake word,
 *              right after "Jarvis" alone or after it finished a reply
 *              (follow-up window).
 * - thinking / speaking: a turn is in progress. Saying the wake word again
 *              ("Jarvis, stop" / "Jarvis, <new question>") interrupts it.
 */
export type HandsFreeMode = 'off' | 'starting' | 'sleeping' | 'listening' | 'thinking' | 'speaking' | 'error';

export interface HandsFreeOptions {
  enabled: boolean;
  wakeWord: string;
  /** Language code sent with each utterance; undefined lets the backend detect it. */
  language?: string;
  /** Run one turn through the chat. Resolves with the reply text, or null if it did not run. */
  onCommand: (command: string, signal: AbortSignal) => Promise<string | null>;
  /** How long to keep listening for a follow-up without the wake word. */
  followUpMs?: number;
}

const FRAME_SIZE = 2048;
/** Report a dead mic if not a single non-zero sample arrives in this window. */
const DEAD_MIC_MS = 4000;
/** While the assistant talks, interrupting speech must be this much louder. */
const BARGE_IN_SCALE = 2.5;
/** Ignore the mic briefly after our own audio stops, so its echo tail is not heard. */
const ECHO_TAIL_MS = 350;
const isBusy = (m: HandsFreeMode) => m === 'thinking' || m === 'speaking';
/** Spoken when the user says only the wake word. */
const ACK_PHRASE = 'Yes?';

/**
 * Recent transcripts and clips, kept in memory only, for diagnosing wake-word
 * misses from the devtools console: `window.__openjarvisVoiceDebug`.
 */
interface VoiceDebug {
  transcripts: Array<{ at: string; mode: HandsFreeMode; text: string; woke: boolean; command: string }>;
  clips: Blob[];
}
function voiceDebug(): VoiceDebug {
  const w = window as unknown as { __openjarvisVoiceDebug?: VoiceDebug };
  w.__openjarvisVoiceDebug ??= { transcripts: [], clips: [] };
  return w.__openjarvisVoiceDebug;
}

export function useHandsFree({ enabled, wakeWord, language, onCommand, followUpMs = 8000 }: HandsFreeOptions) {
  const [mode, setModeState] = useState<HandsFreeMode>('off');
  const [transcribing, setTranscribing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [heard, setHeard] = useState<string>('');
  const [level, setLevel] = useState(0);

  const modeRef = useRef<HandsFreeMode>('off');
  const onCommandRef = useRef(onCommand);
  onCommandRef.current = onCommand;
  const wakeWordRef = useRef(wakeWord);
  wakeWordRef.current = wakeWord;
  const languageRef = useRef(language);
  languageRef.current = language;

  const detectorRef = useRef<UtteranceDetector | null>(null);
  const speakerRef = useRef<ReplySpeaker | null>(null);
  const turnRef = useRef<AbortController | null>(null);
  const followUpTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const queueRef = useRef<Promise<void>>(Promise.resolve());
  /** performance.now() until which mic frames are dropped (echo tail). */
  const muteUntilRef = useRef(0);
  /** Pre-synthesized "Yes?" so the acknowledgement plays instantly. */
  const ackUrlRef = useRef<string | null>(null);

  const setMode = useCallback((m: HandsFreeMode) => {
    if (modeRef.current === 'speaking' && m !== 'speaking') {
      muteUntilRef.current = performance.now() + ECHO_TAIL_MS;
    }
    modeRef.current = m;
    setModeState(m);
    const detector = detectorRef.current;
    if (detector) {
      detector.setSensitivityScale(m === 'speaking' ? BARGE_IN_SCALE : 1);
    }
  }, []);

  const clearFollowUp = () => {
    if (followUpTimer.current) clearTimeout(followUpTimer.current);
    followUpTimer.current = null;
  };

  const chime = useCallback((up: boolean) => {
    const ctx = audioCtxRef.current;
    if (!ctx || ctx.state !== 'running') return;
    const t = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(up ? 660 : 880, t);
    osc.frequency.linearRampToValueAtTime(up ? 990 : 520, t + 0.12);
    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.exponentialRampToValueAtTime(0.12, t + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.2);
    osc.connect(gain).connect(ctx.destination);
    osc.start(t);
    osc.stop(t + 0.22);
    muteUntilRef.current = performance.now() + 220 + ECHO_TAIL_MS;
  }, []);

  /** Answer a bare wake word out loud ("Yes?"), or chime if no voice is available. */
  const acknowledge = useCallback(() => {
    const url = ackUrlRef.current;
    if (!url) {
      chime(true);
      return;
    }
    const el = new Audio(url);
    muteUntilRef.current = performance.now() + 1200;
    el.onloadedmetadata = () => {
      if (Number.isFinite(el.duration)) {
        muteUntilRef.current = performance.now() + el.duration * 1000 + ECHO_TAIL_MS;
      }
    };
    el.play().catch(() => chime(true));
  }, [chime]);

  const startFollowUp = useCallback(() => {
    clearFollowUp();
    setMode('listening');
    const expire = () => {
      if (modeRef.current !== 'listening') return;
      // Never cut someone off mid-sentence.
      if (detectorRef.current?.inSpeech) {
        followUpTimer.current = setTimeout(expire, 1000);
        return;
      }
      setMode('sleeping');
    };
    followUpTimer.current = setTimeout(expire, followUpMs);
  }, [followUpMs, setMode]);

  const interrupt = useCallback(() => {
    turnRef.current?.abort();
    turnRef.current = null;
    speakerRef.current?.cancel();
  }, []);

  const runTurn = useCallback(
    async (command: string) => {
      clearFollowUp();
      interrupt();
      const controller = new AbortController();
      turnRef.current = controller;
      setMode('thinking');
      let reply: string | null = null;
      try {
        reply = await onCommandRef.current(command, controller.signal);
      } catch (err) {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : String(err));
      }
      if (controller.signal.aborted || turnRef.current !== controller) return;
      if (reply) {
        setMode('speaking');
        try {
          await speakerRef.current?.speak(reply);
        } catch (err) {
          if (!controller.signal.aborted) setError(err instanceof Error ? err.message : String(err));
        }
        if (controller.signal.aborted || turnRef.current !== controller) return;
      }
      turnRef.current = null;
      startFollowUp();
    },
    [interrupt, setMode, startFollowUp],
  );

  const handleTranscript = useCallback(
    (text: string, startMode: HandsFreeMode) => {
      // Speech that began while the assistant was thinking or talking keeps
      // those rules (wake word required) even if the reply has since ended:
      // otherwise the tail of its own voice could be taken as a follow-up.
      const current = isBusy(startMode) && !isBusy(modeRef.current) ? startMode : modeRef.current;
      const match = parseWakeCommand(text, wakeWordRef.current);
      const debug = voiceDebug();
      debug.transcripts.push({ at: new Date().toISOString(), mode: current, text, woke: match.woke, command: match.command });
      if (debug.transcripts.length > 30) debug.transcripts.shift();
      setHeard(text);

      if (current === 'sleeping') {
        if (!match.woke) return;
        if (!match.command) {
          acknowledge();
          startFollowUp();
        } else if (isDismissal(match.command, wakeWordRef.current) || isStopCommand(match.command)) {
          chime(false);
        } else {
          void runTurn(match.command);
        }
        return;
      }

      if (current === 'listening') {
        if (isLikelyHallucination(text)) return;
        const command = match.woke ? match.command : text.trim();
        if (!command) {
          acknowledge();
          startFollowUp();
        } else if (isDismissal(command, wakeWordRef.current) || isStopCommand(command)) {
          clearFollowUp();
          chime(false);
          setMode('sleeping');
        } else {
          void runTurn(command);
        }
        return;
      }

      if (isBusy(current)) {
        // Only an explicit "Jarvis, ..." may interrupt -- anything else heard
        // here is most likely the assistant's own voice.
        if (!match.woke) return;
        if (!match.command || isStopCommand(match.command)) {
          interrupt();
          chime(true);
          startFollowUp();
        } else if (isDismissal(match.command, wakeWordRef.current)) {
          interrupt();
          chime(false);
          setMode('sleeping');
        } else {
          void runTurn(match.command);
        }
      }
    },
    [acknowledge, chime, interrupt, runTurn, setMode, startFollowUp],
  );

  const handleUtterance = useCallback(
    (samples: Float32Array, sampleRate: number, startMode: HandsFreeMode) => {
      // Serialize transcriptions so results are handled in the order spoken.
      queueRef.current = queueRef.current.then(async () => {
        if (modeRef.current === 'off' || modeRef.current === 'error') return;
        setTranscribing(true);
        try {
          const wav = encodeUtteranceWav(samples, sampleRate);
          const debug = voiceDebug();
          debug.clips.push(wav);
          if (debug.clips.length > 8) debug.clips.shift();
          // Hint the wake word: without it Whisper often hears "Jarvis" as
          // "Charis", "Service" or "George".
          const wake = wakeWordRef.current;
          const result = await transcribeAudio(wav, 'utterance.wav', {
            hotwords: wake ? wake[0].toUpperCase() + wake.slice(1) : undefined,
            language: languageRef.current,
          });
          const text = (result.text ?? '').trim();
          if (text) handleTranscript(text, startMode);
        } catch (err) {
          setError(err instanceof Error ? err.message : String(err));
        } finally {
          setTranscribing(false);
        }
      });
    },
    [handleTranscript],
  );

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let stream: MediaStream | null = null;
    let ctx: AudioContext | null = null;
    let processor: ScriptProcessorNode | null = null;
    let deadMicTimer: ReturnType<typeof setTimeout> | null = null;
    let levelTimer: ReturnType<typeof setInterval> | null = null;
    let peak = 0;

    speakerRef.current = new ReplySpeaker({
      synthesize: (text, signal) => synthesizeSpeech(text, { signal }),
    });
    setError(null);
    setMode('starting');

    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
        if (cancelled) return;
        ctx = new AudioContext();
        audioCtxRef.current = ctx;
        if (ctx.state === 'suspended') await ctx.resume().catch(() => {});
        const source = ctx.createMediaStreamSource(stream);
        // ScriptProcessor (not an AudioWorklet): the app's CSP does not allow
        // blob: worklet modules, and audio callbacks are not throttled like
        // timers when the window is in the background.
        processor = ctx.createScriptProcessor(FRAME_SIZE, 1, 1);
        const silent = ctx.createGain();
        silent.gain.value = 0;
        source.connect(processor);
        processor.connect(silent).connect(ctx.destination);

        const detector = new UtteranceDetector({ sampleRate: ctx.sampleRate });
        detectorRef.current = detector;
        const rate = ctx.sampleRate;
        let startMode: HandsFreeMode = 'sleeping';
        processor.onaudioprocess = (e) => {
          const frame = e.inputBuffer.getChannelData(0);
          if (peak === 0) peak = blockPeak(frame);
          const m = modeRef.current;
          if (m === 'off' || m === 'error' || m === 'starting') return;
          if (performance.now() < muteUntilRef.current) {
            if (!detector.inSpeech) detector.reset();
            return;
          }
          const wasInSpeech = detector.inSpeech;
          const utterance = detector.push(frame);
          if (!wasInSpeech && detector.inSpeech) startMode = m;
          if (utterance) handleUtterance(utterance, rate, startMode);
        };

        deadMicTimer = setTimeout(() => {
          if (!cancelled && peak === 0) {
            setError(NO_AUDIO_MESSAGE);
            setMode('error');
          }
        }, DEAD_MIC_MS);
        levelTimer = setInterval(() => setLevel(detector.lastLevel), 120);
        setMode('sleeping');
        // Prepare the acknowledgement in the background; the chime covers
        // the gap (or a missing TTS backend).
        synthesizeSpeech(ACK_PHRASE)
          .then((blob) => {
            if (cancelled) return;
            ackUrlRef.current = URL.createObjectURL(blob);
          })
          .catch(() => {});
      } catch (err) {
        if (cancelled) return;
        const name = err instanceof DOMException ? err.name : '';
        setError(
          name === 'NotAllowedError'
            ? 'Microphone access was denied, so hands-free mode cannot listen.'
            : `Could not open the microphone: ${err instanceof Error ? err.message : String(err)}`,
        );
        setMode('error');
      }
    })();

    return () => {
      cancelled = true;
      clearFollowUp();
      if (deadMicTimer) clearTimeout(deadMicTimer);
      if (levelTimer) clearInterval(levelTimer);
      turnRef.current?.abort();
      turnRef.current = null;
      speakerRef.current?.cancel();
      speakerRef.current = null;
      if (processor) processor.onaudioprocess = null;
      stream?.getTracks().forEach((t) => t.stop());
      ctx?.close().catch(() => {});
      audioCtxRef.current = null;
      detectorRef.current = null;
      if (ackUrlRef.current) URL.revokeObjectURL(ackUrlRef.current);
      ackUrlRef.current = null;
      setLevel(0);
      setMode('off');
    };
  }, [enabled, handleUtterance, setMode]);

  /** Stop the current reply or request and wait for the next question. */
  const stopTurn = useCallback(() => {
    if (modeRef.current !== 'thinking' && modeRef.current !== 'speaking') return;
    interrupt();
    startFollowUp();
  }, [interrupt, startFollowUp]);

  return { mode, transcribing, error, heard, level, stopTurn };
}
