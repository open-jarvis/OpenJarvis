import { useState, useCallback, useRef, useEffect } from 'react';
import { listenOnceVoice, transcribeVoice } from '../lib/api';

export type SpeechState = 'idle' | 'recording' | 'transcribing';
export type SpeechInputMode = 'free_web_speech' | 'auto' | 'local_stt';

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

export const MICROPHONE_DENIED_MESSAGE =
  '마이크 권한이 거부되었습니다. 시스템 설정 > 개인정보 보호 및 보안 > 마이크에서 OpenJarvis Friday를 허용해주세요.';
export const MICROPHONE_UNAVAILABLE_MESSAGE =
  '현재 앱 환경에서 마이크 접근 API를 사용할 수 없습니다.';
export const TAURI_SPEECH_UNAVAILABLE_MESSAGE =
  '현재 macOS 앱 모드에서는 Web Speech 음성 인식이 지원되지 않습니다. 로컬 STT를 사용합니다.';

declare global {
  interface Window {
    SpeechRecognition?: BrowserSpeechRecognitionConstructor;
    webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor;
    __TAURI_INTERNALS__?: unknown;
  }
}

export function getSpeechRecognitionConstructor() {
  return window.SpeechRecognition || window.webkitSpeechRecognition;
}

export function isTauriAppMode(): boolean {
  return Boolean(window.__TAURI_INTERNALS__);
}

export function getSpeechUnavailableMessage(): string {
  return isTauriAppMode()
    ? TAURI_SPEECH_UNAVAILABLE_MESSAGE
    : '이 브라우저는 음성 인식과 마이크 녹음 업로드를 지원하지 않습니다';
}

export function isFreeWebSpeechAvailable(): boolean {
  return Boolean(getSpeechRecognitionConstructor());
}

function canRecordWithMediaRecorder(): boolean {
  return Boolean(
    typeof navigator.mediaDevices?.getUserMedia === 'function'
      && typeof MediaRecorder !== 'undefined',
  );
}

export async function requestMicrophonePermission(): Promise<void> {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error(MICROPHONE_UNAVAILABLE_MESSAGE);
  }
  let stream: MediaStream | null = null;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    throw new Error(MICROPHONE_DENIED_MESSAGE);
  } finally {
    stream?.getTracks().forEach((track) => track.stop());
  }
}

export function useSpeech() {
  const [state, setState] = useState<SpeechState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string>('');
  const [available, setAvailable] = useState(false);
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaChunksRef = useRef<BlobPart[]>([]);
  const mediaMimeTypeRef = useRef('audio/webm');
  const backendListenRef = useRef(false);
  const transcriptRef = useRef('');
  const callbackRef = useRef<((text: string) => void) | null>(null);
  const resolveRef = useRef<((text: string) => void) | null>(null);
  const rejectRef = useRef<((error: Error) => void) | null>(null);

  useEffect(() => {
    setAvailable(
      Boolean(getSpeechRecognitionConstructor())
        || canRecordWithMediaRecorder()
        || isTauriAppMode(),
    );
  }, []);

  const getPreferredMimeType = useCallback((): string => {
    const candidates = [
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/mp4',
      'audio/ogg;codecs=opus',
      'audio/ogg',
    ];
    return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || '';
  }, []);

  const startBackendListenOnce = useCallback(async (
    onTranscript?: (text: string) => void,
  ): Promise<void> => {
    try {
      backendListenRef.current = true;
      callbackRef.current = onTranscript || null;
      setStatusMessage('듣는 중...');
      setState('recording');
      const result = await listenOnceVoice();
      setStatusMessage('음성 인식 중...');
      setState('transcribing');
      if (result.ok && result.text.trim()) {
        setStatusMessage('인식 완료');
        callbackRef.current?.(result.text.trim());
      } else {
        const message = result.message || '로컬 STT 설정이 필요합니다';
        setStatusMessage(message);
        setError(message);
      }
    } catch {
      const message = '마이크 권한 또는 STT 엔진을 확인해주세요';
      setStatusMessage(message);
      setError(message);
    } finally {
      backendListenRef.current = false;
      callbackRef.current = null;
      setState('idle');
    }
  }, []);

  const startRecording = useCallback(async (
    lang = 'ko-KR',
    onTranscript?: (text: string) => void,
    mode: SpeechInputMode = 'free_web_speech',
  ): Promise<void> => {
    setError(null);

    const Recognition = getSpeechRecognitionConstructor();
    if (mode === 'local_stt' || !Recognition) {
      if (mode === 'free_web_speech' && !Recognition) {
        setError(
          '무료 브라우저 Web Speech API를 사용할 수 없습니다. Chrome 또는 Safari의 웹 모드에서 다시 시도해주세요.',
        );
        return;
      }
      if (!canRecordWithMediaRecorder()) {
        if (isTauriAppMode()) {
          await startBackendListenOnce(onTranscript);
          return;
        }
        setError(getSpeechUnavailableMessage());
        return;
      }
      try {
        await requestMicrophonePermission();
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const mimeType = getPreferredMimeType();
        const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
        mediaChunksRef.current = [];
        mediaMimeTypeRef.current = mimeType || 'audio/webm';
        callbackRef.current = onTranscript || null;
        recorder.ondataavailable = (event) => {
          if (event.data.size > 0) mediaChunksRef.current.push(event.data);
        };
        recorder.onerror = () => {
          const message = '마이크 녹음에 실패했습니다';
          setError(message);
          setStatusMessage(message);
          setState('idle');
          stream.getTracks().forEach((track) => track.stop());
          rejectRef.current?.(new Error(message));
        };
        recorder.onstop = async () => {
          setState('transcribing');
          setStatusMessage('음성 인식 중...');
          stream.getTracks().forEach((track) => track.stop());
          try {
            const audio = new Blob(mediaChunksRef.current, {
              type: mediaMimeTypeRef.current,
            });
            const extension = mediaMimeTypeRef.current.includes('mp4')
              ? 'm4a'
              : mediaMimeTypeRef.current.includes('ogg')
                ? 'ogg'
                : 'webm';
            const result = await transcribeVoice(
              audio,
              `microphone.${extension}`,
              lang.split('-')[0] || 'ko',
            );
            const text = result.text.trim();
            if (result.ok && text) {
              setStatusMessage('인식 완료');
              callbackRef.current?.(text);
              resolveRef.current?.(text);
            } else {
              const message = result.message || '로컬 STT 설정이 필요합니다';
              setError(message);
              setStatusMessage(message);
              rejectRef.current?.(new Error(message));
            }
          } catch (err) {
            const message = err instanceof Error ? err.message : '음성 인식에 실패했습니다';
            setError(message);
            setStatusMessage(message);
            rejectRef.current?.(new Error(message));
          } finally {
            mediaChunksRef.current = [];
            callbackRef.current = null;
            resolveRef.current = null;
            rejectRef.current = null;
            mediaRecorderRef.current = null;
            setState('idle');
          }
        };
        mediaRecorderRef.current = recorder;
        setStatusMessage('듣는 중...');
        setState('recording');
        recorder.start();
      } catch (err) {
        setError(err instanceof Error ? err.message : MICROPHONE_DENIED_MESSAGE);
        setStatusMessage('마이크 권한 또는 STT 엔진을 확인해주세요');
        setState('idle');
      }
      return;
    }

    try {
      await requestMicrophonePermission();
      transcriptRef.current = '';
      callbackRef.current = onTranscript || null;
      setStatusMessage('듣는 중...');
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
        if (isTauriAppMode()) {
          recognitionRef.current = null;
          callbackRef.current = null;
          resolveRef.current = null;
          rejectRef.current = null;
          void startBackendListenOnce(onTranscript);
          return;
        }
        const err = new Error('Speech recognition failed');
        setError(err.message);
        setStatusMessage('마이크 권한 또는 STT 엔진을 확인해주세요');
        setState('idle');
        rejectRef.current?.(err);
        callbackRef.current = null;
        resolveRef.current = null;
        rejectRef.current = null;
      };
      recognition.onend = () => {
        const text = transcriptRef.current;
        setState('idle');
        setStatusMessage(text ? '인식 완료' : '');
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
      if (isTauriAppMode()) {
        await startBackendListenOnce(onTranscript);
        return;
      }
      setError(err instanceof Error ? err.message : MICROPHONE_DENIED_MESSAGE);
      setStatusMessage('마이크 권한 또는 STT 엔진을 확인해주세요');
      setState('idle');
    }
  }, [getPreferredMimeType, startBackendListenOnce]);

  const stopRecording = useCallback((): Promise<string> => {
    return new Promise((resolve, reject) => {
      const recognition = recognitionRef.current;
      const mediaRecorder = mediaRecorderRef.current;
      if (backendListenRef.current) {
        reject(new Error('Backend listen-once cannot be stopped'));
        return;
      }
      if (mediaRecorder && state === 'recording') {
        resolveRef.current = resolve;
        rejectRef.current = reject;
        mediaRecorder.stop();
        return;
      }
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
    statusMessage,
    available,
    startRecording,
    stopRecording,
    isRecording: state === 'recording',
    isTranscribing: state === 'transcribing',
  };
}
