import { useRef, useState, useEffect, useCallback } from 'react';
import { Play, Pause, Volume2 } from 'lucide-react';

interface AudioPlayerProps {
  src: string;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export function AudioPlayer({ src }: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  const toggle = useCallback(() => {
    const el = audioRef.current;
    if (!el) return;
    if (playing) {
      el.pause();
    } else {
      el.play();
    }
    setPlaying(!playing);
  }, [playing]);

  useEffect(() => {
    const el = audioRef.current;
    if (!el) return;

    const onTime = () => setCurrentTime(el.currentTime);
    const onMeta = () => setDuration(el.duration);
    const onEnded = () => {
      setPlaying(false);
      setCurrentTime(0);
    };

    el.addEventListener('timeupdate', onTime);
    el.addEventListener('loadedmetadata', onMeta);
    el.addEventListener('ended', onEnded);
    return () => {
      el.removeEventListener('timeupdate', onTime);
      el.removeEventListener('loadedmetadata', onMeta);
      el.removeEventListener('ended', onEnded);
    };
  }, []);

  const progress = duration > 0 ? (currentTime / duration) * 100 : 0;

  const seek = (e: React.MouseEvent<HTMLDivElement>) => {
    const el = audioRef.current;
    if (!el || !duration) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const pct = (e.clientX - rect.left) / rect.width;
    el.currentTime = pct * duration;
  };

  return (
    <div
      className="flex items-center gap-3 px-4 py-3 rounded-xl mb-3"
      style={{
        background: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
      }}
    >
      <audio ref={audioRef} src={src} preload="metadata" />

      <button
        onClick={toggle}
        className="flex items-center justify-center w-9 h-9 rounded-full transition-colors shrink-0"
        style={{
          background: 'var(--color-accent)',
          color: 'var(--color-on-accent)',
          cursor: 'pointer',
        }}
      >
        {playing ? <Pause size={16} /> : <Play size={16} className="ml-0.5" />}
      </button>

      <div className="flex flex-col gap-1.5 flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <Volume2 size={14} style={{ color: 'var(--color-text-tertiary)' }} />
          <span
            className="text-xs font-medium"
            style={{ color: 'var(--color-text-secondary)' }}
          >
            Morning Digest
          </span>
        </div>

        <div
          className="h-1.5 rounded-full cursor-pointer"
          style={{ background: 'var(--color-bg-tertiary)' }}
          onClick={seek}
        >
          <div
            className="h-full rounded-full transition-all"
            style={{
              width: `${progress}%`,
              background: 'var(--color-accent)',
            }}
          />
        </div>

        <div
          className="flex justify-between text-xs"
          style={{ color: 'var(--color-text-tertiary)' }}
        >
          <span>{formatTime(currentTime)}</span>
          <span>{duration > 0 ? formatTime(duration) : '--:--'}</span>
        </div>
      </div>
    </div>
  );
}
