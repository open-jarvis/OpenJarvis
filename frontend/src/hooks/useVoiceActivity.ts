import { useCallback, useEffect, useRef, useState } from 'react';
import { createVoiceDetector, encodeWav, frameRms, resampleLinear } from '../lib/hud/audio';
import frameTapUrl from '../lib/hud/frame-tap.worklet.js?url&no-inline';

export type MicStatus = 'off' | 'starting' | 'listening' | 'denied' | 'unsupported';

export interface VoiceActivityOptions {
  /** Contexto de audio ya desbloqueado por un gesto del usuario; null = micrófono apagado. */
  audioContext: AudioContext | null;
  /** Exigencia extra del detector (> 1 mientras suena la voz de Jarvis). */
  sensitivityFactor: number;
  /** Frase terminada, lista para transcribir. `manual` = se grabó con la tecla de hablar. */
  onUtterance: (wav: Blob, manual: boolean) => void;
}

const FRAME_MS = 20;
/** Audio previo al inicio detectado, para no perder la primera sílaba ("Jar-"). */
const PRE_ROLL_MS = 400;
/** Frecuencia que espera Whisper; enviar más solo agranda el archivo. */
const TARGET_SAMPLE_RATE = 16000;
/** Una pulsación accidental de la tecla no llega a ser una frase. */
const MIN_MANUAL_MS = 300;

/** Debe coincidir con el nombre registrado en frame-tap.worklet.js. */
const WORKLET_NAME = 'hud-frame-tap';

function concatFrames(frames: Float32Array[]): Float32Array {
  const total = frames.reduce((sum, frame) => sum + frame.length, 0);
  const joined = new Float32Array(total);
  let offset = 0;
  for (const frame of frames) {
    joined.set(frame, offset);
    offset += frame.length;
  }
  return joined;
}

/**
 * Micrófono abierto con corte automático de frases.
 *
 * Captura PCM crudo (no MediaRecorder) para conservar un tramo previo al
 * inicio de la voz y entregar WAV, que el servidor lee sin recodificar.
 */
export function useVoiceActivity({ audioContext, sensitivityFactor, onUtterance }: VoiceActivityOptions) {
  const [status, setStatus] = useState<MicStatus>('off');
  const [isHearing, setIsHearing] = useState(false);

  const levelRef = useRef(0);
  const detectorRef = useRef(createVoiceDetector());
  const onUtteranceRef = useRef(onUtterance);
  onUtteranceRef.current = onUtterance;
  // Estado de captura fuera de React: cambia 50 veces por segundo.
  const captureRef = useRef({ frames: [] as Float32Array[], capturing: false, manual: false });

  useEffect(() => {
    detectorRef.current.setSensitivityFactor(sensitivityFactor);
  }, [sensitivityFactor]);

  const finishUtterance = useCallback((sampleRate: number) => {
    const capture = captureRef.current;
    const { frames, manual } = capture;
    capture.frames = [];
    capture.capturing = false;
    capture.manual = false;
    setIsHearing(false);

    const samples = concatFrames(frames);
    if (manual && (samples.length / sampleRate) * 1000 < MIN_MANUAL_MS) return;
    const wav = encodeWav(
      resampleLinear(samples, sampleRate, TARGET_SAMPLE_RATE),
      TARGET_SAMPLE_RATE,
    );
    onUtteranceRef.current(new Blob([wav], { type: 'audio/wav' }), manual);
  }, []);

  useEffect(() => {
    if (!audioContext) {
      setStatus('off');
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || !audioContext.audioWorklet) {
      setStatus('unsupported');
      return;
    }

    let cancelled = false;
    let stream: MediaStream | null = null;
    let nodes: AudioNode[] = [];
    const detector = detectorRef.current;
    const capture = captureRef.current;
    const preRollFrames = Math.ceil(PRE_ROLL_MS / FRAME_MS);

    const handleFrame = (frame: Float32Array) => {
      const level = frameRms(frame);
      levelRef.current = level;

      if (capture.manual) {
        capture.frames.push(frame);
        return;
      }
      const event = detector.process(level, FRAME_MS);
      capture.frames.push(frame);
      if (event === 'speech_start') {
        capture.capturing = true;
        setIsHearing(true);
      } else if (event === 'speech_end') {
        finishUtterance(audioContext.sampleRate);
      } else if (!capture.capturing && capture.frames.length > preRollFrames) {
        capture.frames.shift();
      }
    };

    const start = async () => {
      setStatus('starting');
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          // La cancelación de eco evita que Jarvis se escuche a sí mismo.
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
      } catch {
        if (!cancelled) setStatus('denied');
        return;
      }
      try {
        await audioContext.audioWorklet.addModule(frameTapUrl);
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }

        const source = audioContext.createMediaStreamSource(stream);
        const tap = new AudioWorkletNode(audioContext, WORKLET_NAME, {
          numberOfOutputs: 1,
          processorOptions: { frameSize: Math.round((audioContext.sampleRate * FRAME_MS) / 1000) },
        });
        // Un nodo sin salida conectada puede no procesarse; se conecta en silencio.
        const mute = audioContext.createGain();
        mute.gain.value = 0;
        tap.port.onmessage = (message) => handleFrame(message.data as Float32Array);
        source.connect(tap).connect(mute).connect(audioContext.destination);
        nodes = [source, tap, mute];
        setStatus('listening');
      } catch {
        // El micrófono se concedió pero el procesador de audio no pudo iniciarse.
        stream.getTracks().forEach((track) => track.stop());
        if (!cancelled) setStatus('unsupported');
      }
    };
    void start();

    return () => {
      cancelled = true;
      nodes.forEach((node) => node.disconnect());
      stream?.getTracks().forEach((track) => track.stop());
      detector.reset();
      capture.frames = [];
      capture.capturing = false;
      capture.manual = false;
      levelRef.current = 0;
      setIsHearing(false);
    };
  }, [audioContext, finishUtterance]);

  /** Tecla de hablar: graba desde ya, sin esperar al detector ni a la palabra de activación. */
  const startManual = useCallback(() => {
    const capture = captureRef.current;
    if (status !== 'listening' || capture.manual) return;
    detectorRef.current.reset();
    capture.manual = true;
    capture.capturing = true;
    setIsHearing(true);
  }, [status]);

  const stopManual = useCallback(() => {
    if (!captureRef.current.manual || !audioContext) return;
    finishUtterance(audioContext.sampleRate);
  }, [audioContext, finishUtterance]);

  const getLevel = useCallback(() => levelRef.current, []);

  return { status, isHearing, getLevel, startManual, stopManual };
}
