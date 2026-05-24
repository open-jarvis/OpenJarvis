import { useState, useCallback, useRef, useEffect } from 'react';

export type SpeechState = 'idle' | 'recording';

type SpeechRecognitionResultLike = {
  readonly isFinal: boolean;
  readonly [index: number]: { readonly transcript: string };
};

type SpeechRecognitionEventLike = {
  readonly resultIndex: number;
  readonly results: {
    readonly length: number;
    readonly [index: number]: SpeechRecognitionResultLike;
  };
};

type BrowserSpeechRecognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

type BrowserSpeechRecognitionConstructor = new () => BrowserSpeechRecognition;

declare global {
  interface Window {
    SpeechRecognition?: BrowserSpeechRecognitionConstructor;
    webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor;
  }
}

export function useSpeech() {
  const [state, setState] = useState<SpeechState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [available, setAvailable] = useState(false);
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const transcriptRef = useRef('');
  const callbackRef = useRef<((text: string) => void) | null>(null);
  const resolveRef = useRef<((text: string) => void) | null>(null);
  const rejectRef = useRef<((error: Error) => void) | null>(null);

  useEffect(() => {
    setAvailable(Boolean(window.SpeechRecognition || window.webkitSpeechRecognition));
  }, []);

  const startRecording = useCallback(async (
    lang = 'ko-KR',
    onTranscript?: (text: string) => void,
  ): Promise<void> => {
    setError(null);

    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
      setError('Browser speech recognition is not supported');
      return;
    }

    try {
      transcriptRef.current = '';
      callbackRef.current = onTranscript || null;
      const recognition = new Recognition();
      recognition.lang = lang;
      recognition.continuous = false;
      recognition.interimResults = true;
      recognition.onresult = (event) => {
        let text = '';
        for (let i = event.resultIndex; i < event.results.length; i += 1) {
          text += event.results[i][0]?.transcript || '';
          if (event.results[i].isFinal) {
            transcriptRef.current = text.trim();
          }
        }
        if (text.trim()) transcriptRef.current = text.trim();
      };
      recognition.onerror = () => {
        const err = new Error('Speech recognition failed');
        setError(err.message);
        setState('idle');
        rejectRef.current?.(err);
        callbackRef.current = null;
        resolveRef.current = null;
        rejectRef.current = null;
      };
      recognition.onend = () => {
        const text = transcriptRef.current;
        setState('idle');
        if (resolveRef.current) {
          resolveRef.current(text);
        } else if (text) {
          callbackRef.current?.(text);
        }
        callbackRef.current = null;
        resolveRef.current = null;
        rejectRef.current = null;
      };

      recognitionRef.current = recognition;
      recognition.start();
      setState('recording');
    } catch (err) {
      setError('Microphone access denied or unavailable');
      setState('idle');
    }
  }, []);

  const stopRecording = useCallback((): Promise<string> => {
    return new Promise((resolve, reject) => {
      const recognition = recognitionRef.current;
      if (!recognition || state !== 'recording') {
        reject(new Error('Not recording'));
        return;
      }
      resolveRef.current = resolve;
      rejectRef.current = reject;
      recognition.stop();
    });
  }, [state]);

  return {
    state,
    error,
    available,
    startRecording,
    stopRecording,
    isRecording: state === 'recording',
    isTranscribing: false,
  };
}
