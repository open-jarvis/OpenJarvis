import { useEffect, useRef, useState } from 'react';

/**
 * Reconocimiento de voz del navegador (Web Speech API).
 *
 * En Edge lo hace el servicio de voz de Microsoft y en Chrome el de Google:
 * entiende mucho mejor que un Whisper pequeño en CPU, devuelve el texto casi
 * al instante y no consume memoria del PC. El audio sale hacia ese servicio.
 */
export type RecognitionStatus = 'unsupported' | 'off' | 'listening' | 'failed';

interface BrowserRecognitionOptions {
  enabled: boolean;
  lang: string;
  /** Frase terminada. */
  onFinal: (text: string) => void;
  /** Texto provisional mientras el usuario habla (vacío al terminar). */
  onInterim?: (text: string) => void;
}

/** Errores tras los que no tiene sentido reintentar: se pasa al respaldo local. */
const FATAL_ERRORS = new Set([
  'not-allowed',
  'service-not-allowed',
  'network',
  'audio-capture',
  'language-not-supported',
]);
const MAX_RESTART_DELAY_MS = 5000;

// La API no tiene tipos en TypeScript estándar; se usa la mínima interfaz necesaria.
interface RecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((event: any) => void) | null;
  onerror: ((event: any) => void) | null;
  onend: (() => void) | null;
  start(): void;
  abort(): void;
}

export function getRecognitionConstructor(): (new () => RecognitionLike) | null {
  if (typeof window === 'undefined') return null;
  const scope = window as unknown as Record<string, unknown>;
  return (scope.SpeechRecognition ?? scope.webkitSpeechRecognition ?? null) as
    | (new () => RecognitionLike)
    | null;
}

export function useBrowserRecognition({ enabled, lang, onFinal, onInterim }: BrowserRecognitionOptions) {
  const [status, setStatus] = useState<RecognitionStatus>(() =>
    getRecognitionConstructor() ? 'off' : 'unsupported',
  );
  const onFinalRef = useRef(onFinal);
  onFinalRef.current = onFinal;
  const onInterimRef = useRef(onInterim);
  onInterimRef.current = onInterim;

  useEffect(() => {
    const Recognition = getRecognitionConstructor();
    if (!Recognition) {
      setStatus('unsupported');
      return;
    }
    if (!enabled) {
      setStatus('off');
      return;
    }

    let stopped = false;
    let fatal = false;
    let restarts = 0;
    let restartTimer: ReturnType<typeof setTimeout> | undefined;
    const recognition = new Recognition();
    recognition.lang = lang;
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    recognition.onresult = (event) => {
      restarts = 0;
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        const text = String(result[0]?.transcript ?? '').trim();
        if (result.isFinal) {
          if (text) onFinalRef.current(text);
        } else if (text) {
          interim += `${text} `;
        }
      }
      onInterimRef.current?.(interim.trim());
    };
    recognition.onerror = (event) => {
      // "no-speech" y "aborted" son normales; el reinicio de onend los cubre.
      if (FATAL_ERRORS.has(event.error)) {
        fatal = true;
        setStatus('failed');
      }
    };
    // El navegador corta la escucha tras un silencio largo: se reanuda sola.
    recognition.onend = () => {
      if (stopped || fatal) return;
      restarts += 1;
      restartTimer = setTimeout(start, Math.min(MAX_RESTART_DELAY_MS, 250 * restarts));
    };
    function start() {
      try {
        recognition.start();
        setStatus('listening');
      } catch {
        // Ya estaba escuchando.
      }
    }
    start();

    return () => {
      stopped = true;
      clearTimeout(restartTimer);
      recognition.onend = null;
      try {
        recognition.abort();
      } catch {
        // Ya estaba detenido.
      }
      setStatus('off');
    };
  }, [enabled, lang]);

  return { status };
}
