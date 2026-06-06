import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchTtsHealth, synthesizeSpeech, synthesizeSpeechResponse } from '../lib/api';

const MP3_MIME = 'audio/mpeg';

/** Whether the browser can stream MP3 through Media Source Extensions. */
function canStreamMp3(): boolean {
  return (
    typeof MediaSource !== 'undefined' &&
    typeof MediaSource.isTypeSupported === 'function' &&
    MediaSource.isTypeSupported(MP3_MIME)
  );
}

/** Strip markdown-ish noise so TTS reads naturally. */
function plainForSpeech(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[#*_~>|]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Stream MP3 bytes from a fetch Response into an <audio> element via
 * MediaSource so playback starts before the full clip arrives. Resolves when
 * playback finishes. Throws if streaming is unsupported or fails, so the
 * caller can fall back to buffered playback.
 */
async function playStreamedMp3(
  res: Response,
  setAudio: (a: HTMLAudioElement) => void,
  setUrl: (u: string) => void,
): Promise<void> {
  if (!res.body) throw new Error('No response body to stream');

  const mediaSource = new MediaSource();
  const url = URL.createObjectURL(mediaSource);
  setUrl(url);
  const audio = new Audio();
  audio.src = url;
  setAudio(audio);

  await new Promise<void>((resolve, reject) => {
    const onSourceOpen = async () => {
      let sourceBuffer: SourceBuffer;
      try {
        sourceBuffer = mediaSource.addSourceBuffer(MP3_MIME);
      } catch (err) {
        reject(err);
        return;
      }

      const pending: Uint8Array[] = [];
      let readerDone = false;

      const flush = () => {
        if (sourceBuffer.updating) return;
        if (pending.length > 0) {
          try {
            sourceBuffer.appendBuffer(pending.shift()!);
          } catch (err) {
            reject(err);
          }
          return;
        }
        if (readerDone && mediaSource.readyState === 'open') {
          try {
            mediaSource.endOfStream();
          } catch {
            /* already ended */
          }
        }
      };

      sourceBuffer.addEventListener('updateend', flush);
      audio.onended = () => resolve();
      audio.onerror = () => reject(new Error('Playback failed'));

      try {
        const reader = res.body!.getReader();
        // Kick off playback as soon as the element is ready.
        void audio.play().catch(() => undefined);
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          if (value && value.byteLength > 0) {
            pending.push(value);
            flush();
          }
        }
        readerDone = true;
        flush();
      } catch (err) {
        reject(err);
      }
    };

    mediaSource.addEventListener('sourceopen', onSourceOpen, { once: true });
  });
}

export function useVoiceReply() {
  const [ttsAvailable, setTtsAvailable] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const objectUrlRef = useRef<string | null>(null);

  useEffect(() => {
    fetchTtsHealth()
      .then((h) => setTtsAvailable(h.available))
      .catch(() => setTtsAvailable(false));
  }, []);

  const stopSpeaking = useCallback(() => {
    const el = audioRef.current;
    if (el) {
      el.pause();
      el.currentTime = 0;
    }
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
    setIsSpeaking(false);
  }, []);

  const speak = useCallback(
    async (text: string): Promise<void> => {
      const plain = plainForSpeech(text);
      if (!plain || !ttsAvailable) return;

      stopSpeaking();
      setIsSpeaking(true);

      const setAudio = (a: HTMLAudioElement) => {
        audioRef.current = a;
      };
      const setUrl = (u: string) => {
        objectUrlRef.current = u;
      };

      const playBuffered = async () => {
        const blob = await synthesizeSpeech(plain);
        const url = URL.createObjectURL(blob);
        objectUrlRef.current = url;
        const audio = new Audio(url);
        audioRef.current = audio;
        await new Promise<void>((resolve, reject) => {
          audio.onended = () => resolve();
          audio.onerror = () => reject(new Error('Playback failed'));
          audio.play().catch(reject);
        });
      };

      try {
        if (canStreamMp3()) {
          try {
            const res = await synthesizeSpeechResponse(plain);
            await playStreamedMp3(res, setAudio, setUrl);
          } catch {
            // Streaming path failed (codec quirk, aborted body, etc.) —
            // fall back to the reliable buffered path.
            stopSpeaking();
            setIsSpeaking(true);
            await playBuffered();
          }
        } else {
          await playBuffered();
        }
      } catch {
        // Non-fatal — chat still works without spoken reply.
      } finally {
        stopSpeaking();
      }
    },
    [ttsAvailable, stopSpeaking],
  );

  useEffect(() => () => stopSpeaking(), [stopSpeaking]);

  return { ttsAvailable, isSpeaking, speak, stopSpeaking };
}
