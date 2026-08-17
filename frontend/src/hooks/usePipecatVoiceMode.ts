import { PipecatClient, RTVIEvent } from '@pipecat-ai/client-js';
import { SmallWebRTCTransport } from '@pipecat-ai/small-webrtc-transport';
import { useCallback, useEffect, useRef, useState } from 'react';

import { apiFetch } from '@/lib/api';
import { voiceActivityFromServerMessage, type VoiceActivity } from '@/hooks/voiceActivity';
import type { LocalVoiceStatus } from '@/hooks/voiceStatus';
import type { ChatMessage } from '@/types';

/** Where the server answers an SDP offer and starts a pipeline behind it. */
const OFFER_URL = '/api/voice/webrtc/offer';

export type VoiceAvailability = {
  enabled: boolean;
  unavailableReason: string | null;
};

export function voiceAvailability(payload: {
  gemini_live_enabled?: boolean;
  gemini_live_reason?: string | null;
}): VoiceAvailability {
  if (payload.gemini_live_enabled === true) {
    return { enabled: true, unavailableReason: null };
  }
  return {
    enabled: false,
    unavailableReason: payload.gemini_live_reason ?? 'poc_disabled',
  };
}

/**
 * Turn a finished voice turn into a chat message, or nothing.
 *
 * Barge-in can end an assistant turn before a word was spoken, and an empty
 * bubble in the sidebar is worse than no bubble.
 */
export function voiceTurnMessage(
  role: 'user' | 'assistant',
  content: string,
): ChatMessage | null {
  const trimmed = content.trim();
  if (!trimmed) return null;
  return {
    id: `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`,
    role,
    content: trimmed,
    timestamp: Date.now(),
  };
}

/**
 * Turn BotStoppedSpeaking into a message and the caption's next state.
 *
 * pipecat fires BotStoppedSpeaking on a TTS idle timeout, and a tool call
 * mid-answer routinely exceeds it — "Đang mở YouTube…" [browser tool]
 * "…xong rồi" is one turn split across two of these events. The caption must
 * be cleared every time this fires, whether or not it produced a message —
 * otherwise the next chunk is appended to what was already emitted and the
 * same answer is written to the sidebar again, longer each time.
 */
export function botStoppedSpeaking(caption: string): {
  message: ChatMessage | null;
  nextCaption: string;
} {
  return { message: voiceTurnMessage('assistant', caption), nextCaption: '' };
}

/**
 * A refused lease is not a failure.
 *
 * The server answers 409 when another Voice session already holds the single
 * lease, and the caller falls back to text rather than showing an error.
 */
export function voiceStatusForError(error: unknown): LocalVoiceStatus {
  const status = (error as { status?: number } | undefined)?.status;
  return status === 409 ? 'busy' : 'error';
}

export function voiceStatusForActivity(activity: VoiceActivity): {
  status: LocalVoiceStatus;
  detail: string | null;
} {
  if (activity.phase === 'processing') return { status: 'processing', detail: null };
  if (activity.phase === 'inference') return { status: 'inference', detail: activity.model };
  return { status: 'tool', detail: activity.toolName };
}

export function hasAudibleSpectrum(spectrum: Uint8Array): boolean {
  let sum = 0;
  for (const value of spectrum) sum += value;
  return sum > spectrum.length;
}

/**
 * Connect, tolerating a lease the server has not finished releasing.
 *
 * The single Voice lease outlives its pipeline by the time it takes the peer
 * connection to close and the server to notice. A reconnect that lands inside
 * that window — a page reload, or React StrictMode remounting the page in
 * development — gets a 409 that is not a real refusal, just early. Retrying a
 * few times turns it back into a connection; a lease genuinely held by another
 * session outlasts the retries and still surfaces as busy.
 */
async function connectWithLeaseRetry(
  client: PipecatClient,
  attempts = 4,
  delayMs = 400,
): Promise<void> {
  for (let attempt = 1; ; attempt += 1) {
    try {
      await client.connect();
      return;
    } catch (failure) {
      const busy = (failure as { status?: number } | undefined)?.status === 409;
      if (!busy || attempt >= attempts) throw failure;
      await new Promise((resolve) => setTimeout(resolve, delayMs * attempt));
    }
  }
}

export function usePipecatVoiceMode(options: { onTurn?: (message: ChatMessage) => void } = {}) {
  const [enabled, setEnabled] = useState(false);
  const [unavailableReason, setUnavailableReason] = useState<string | null>(null);
  const [status, setStatus] = useState<LocalVoiceStatus>('idle');
  const [activityDetail, setActivityDetail] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [assistantCaptionText, setAssistantCaptionText] = useState('');
  const [transcript, setTranscript] = useState('');

  const onTurnRef = useRef(options.onTurn);
  onTurnRef.current = options.onTurn;

  // The accumulated caption is read on the turn boundary. Reading it through
  // a setState updater instead would put a side effect in an updater React is
  // allowed to invoke twice — and StrictMode does, firing onTurn twice per turn.
  const captionRef = useRef('');

  const clientRef = useRef<PipecatClient | null>(null);
  const audioElementRef = useRef<HTMLAudioElement | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const spectrumRef = useRef(new Uint8Array(128));
  const idleRef = useRef({ t: 0, spectrum: new Uint8Array(128) });

  useEffect(() => {
    void apiFetch('/api/voice/availability')
      .then(async (response) => {
        if (!response.ok) return;
        const availability = voiceAvailability(await response.json());
        setEnabled(availability.enabled);
        setUnavailableReason(availability.unavailableReason);
      })
      .catch(() => setUnavailableReason('voice_availability_unreachable'));
  }, []);

  /** Gentle breathing spectrum so the sphere never freezes in silence. */
  const idleSpectrum = useCallback((): Uint8Array => {
    const idle = idleRef.current;
    idle.t += 0.02;
    const swell = 0.5 + 0.5 * Math.sin(idle.t * 0.6);
    for (let i = 0; i < idle.spectrum.length; i += 1) {
      const base = Math.exp(-i * 0.05) * 60;
      idle.spectrum[i] = Math.max(
        0,
        Math.min(255, base * (0.35 + swell * 0.4) + Math.sin(idle.t * (0.8 + i * 0.05)) * 10),
      );
    }
    return idle.spectrum;
  }, []);

  const getFrequencyData = useCallback((): Uint8Array => {
    const analyser = analyserRef.current;
    if (!analyser) return idleSpectrum();
    analyser.getByteFrequencyData(spectrumRef.current);
    return hasAudibleSpectrum(spectrumRef.current) ? spectrumRef.current : idleSpectrum();
  }, [idleSpectrum]);

  /** The analyser that drives the visualiser. Playback is the element's job. */
  const ensureAnalyser = useCallback((): AnalyserNode | null => {
    if (analyserRef.current) {
      if (audioContextRef.current?.state === 'suspended') {
        void audioContextRef.current.resume();
      }
      return analyserRef.current;
    }
    try {
      const context = new AudioContext();
      const analyser = context.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.8;
      // Deliberately NOT connected to context.destination: the <audio>
      // element below does the playing, and routing here as well would play
      // the assistant twice.
      audioContextRef.current = context;
      analyserRef.current = analyser;
      spectrumRef.current = new Uint8Array(analyser.frequencyBinCount);
      idleRef.current = { t: 0, spectrum: new Uint8Array(analyser.frequencyBinCount) };
      return analyser;
    } catch {
      return null;
    }
  }, []);

  /**
   * Play the assistant's track, and tap it for the visualiser.
   *
   * The element is what makes sound. Chrome does not pump a remote WebRTC
   * track into Web Audio until that track is also attached to a media
   * element, so a createMediaStreamSource tap on its own reads pure silence —
   * which is exactly what a graph wired only to the analyser produced.
   */
  const playBotAudio = useCallback((track: MediaStreamTrack) => {
    const stream = new MediaStream([track]);

    let element = audioElementRef.current;
    if (!element) {
      element = new Audio();
      element.autoplay = true;
      // Safari and some Chrome builds refuse to start a detached element.
      element.style.display = 'none';
      document.body.appendChild(element);
      audioElementRef.current = element;
    }
    element.srcObject = stream;
    void element.play().catch((failure) => {
      console.warn('VOICE-AUDIO: playback blocked, will retry on next click', failure);
      const retry = () => {
        void element?.play().catch(() => undefined);
        window.removeEventListener('pointerdown', retry);
      };
      window.addEventListener('pointerdown', retry);
    });

    const analyser = ensureAnalyser();
    if (analyser && audioContextRef.current) {
      audioContextRef.current.createMediaStreamSource(stream).connect(analyser);
    }
  }, [ensureAnalyser]);

  /**
   * The small-webrtc transport never surfaces remote tracks: its media
   * manager is built with the player disabled and reports the local mic only.
   * The peer connection is the only place the assistant's track exists, so
   * take it from there — both the track already negotiated by the time
   * connect resolves and any that arrive later.
   */
  const attachRemoteAudio = useCallback((client: PipecatClient) => {
    const pc = (client.transport as unknown as { pc: RTCPeerConnection }).pc;
    if (!pc) {
      console.warn('VOICE-AUDIO: no peer connection — the assistant cannot be heard');
      return;
    }
    if (pc.ontrack === null) {
      pc.ontrack = (event: RTCTrackEvent) => {
        if (event.track.kind === 'audio') playBotAudio(event.track);
      };
    }
    for (const receiver of pc.getReceivers()) {
      if (receiver.track?.kind === 'audio') playBotAudio(receiver.track);
    }
  }, [playBotAudio]);

  const end = useCallback(async () => {
    const client = clientRef.current;
    clientRef.current = null;
    setStatus('ended');
    setActivityDetail(null);
    captionRef.current = '';
    setAssistantCaptionText('');
    if (audioElementRef.current) {
      audioElementRef.current.srcObject = null;
    }
    // Nothing on the server waits for playback to finish any more, so tearing
    // the connection down is the whole of stopping.
    await client?.disconnect().catch(() => undefined);
  }, []);

  const start = useCallback(async (chatThreadId: string, model: string) => {
    if (clientRef.current) return;
    setError(null);
    setStatus('connecting');
    setActivityDetail(null);

    const client = new PipecatClient({
      transport: new SmallWebRTCTransport({
        webrtcRequestParams: {
          endpoint: OFFER_URL,
          requestData: { chat_thread_id: chatThreadId, model },
        },
      }),
      enableMic: true,
      enableCam: false,
    });
    clientRef.current = client;

    client.on(RTVIEvent.UserStartedSpeaking, () => {
      setStatus('listening');
      setActivityDetail(null);
      captionRef.current = '';
      setAssistantCaptionText('');
    });
    client.on(RTVIEvent.UserStoppedSpeaking, () => {
      setStatus('processing');
      setActivityDetail(null);
    });
    client.on(RTVIEvent.ServerMessage, (message: unknown) => {
      const activity = voiceActivityFromServerMessage(message);
      if (!activity) return;
      const next = voiceStatusForActivity(activity);
      setStatus(next.status);
      setActivityDetail(next.detail);
    });
    client.on(RTVIEvent.BotStartedSpeaking, () => {
      setStatus('speaking');
      setActivityDetail(null);
    });
    client.on(RTVIEvent.BotStoppedSpeaking, () => {
      setStatus('listening');
      setActivityDetail(null);
      const { message, nextCaption } = botStoppedSpeaking(captionRef.current);
      captionRef.current = nextCaption;
      setAssistantCaptionText(nextCaption);
      if (message) onTurnRef.current?.(message);
    });
    client.on(RTVIEvent.BotTtsText, (data: { text: string }) => {
      captionRef.current += data.text;
      setAssistantCaptionText((current) => current + data.text);
    });
    client.on(RTVIEvent.UserTranscript, (data: { text: string; final: boolean }) => {
      if (!data.final) return;
      setTranscript(data.text);
      const message = voiceTurnMessage('user', data.text);
      if (message) onTurnRef.current?.(message);
    });
    client.on(RTVIEvent.Disconnected, () => {
      setStatus('ended');
      setActivityDetail(null);
      captionRef.current = '';
      setAssistantCaptionText('');
    });

    try {
      await connectWithLeaseRetry(client);
      attachRemoteAudio(client);
      setStatus('listening');
    } catch (failure) {
      clientRef.current = null;
      const next = voiceStatusForError(failure);
      setStatus(next);
      setActivityDetail(null);
      setError(next === 'busy' ? 'voice_busy' : String(failure));
    }
  }, [attachRemoteAudio]);

  useEffect(() => () => void clientRef.current?.disconnect().catch(() => undefined), []);

  return {
    enabled,
    unavailableReason,
    status,
    activityDetail,
    error,
    transcript,
    assistantCaptionText,
    start,
    end,
    getFrequencyData,
  };
}
