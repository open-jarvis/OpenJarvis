import { useEffect, useRef } from 'react';
import type { Jarvis } from '../Jarvis/useJarvis';
import { Diamond } from './ZenArt';
import { IconChart, IconClock, IconFolder, IconHome } from './icons';

const ORB_TITLE: Record<Jarvis['mode'], string> = {
  idle: 'Talk to Jarvis',
  listening: 'Listening - tap to send now',
  transcribing: 'Understanding…',
  thinking: 'Thinking - tap to stop',
  speaking: 'Speaking - tap to stop',
  offline: 'Jarvis is offline',
};

/** Floating dock; the diamond in the middle is Jarvis's voice button. */
export function ZenDock({
  j,
  onHome,
  onProgress,
  onRoutines,
  onFiles,
  routineCount,
}: {
  j: Jarvis;
  onHome: () => void;
  onProgress: () => void;
  onRoutines: () => void;
  onFiles: () => void;
  routineCount: number;
}) {
  const orbRef = useRef<HTMLButtonElement>(null);
  const { levelRef } = j;

  // Pulse the orb with the microphone / voice level.
  useEffect(() => {
    let raf = 0;
    let shown = 0;
    const loop = () => {
      shown += (levelRef.current - shown) * 0.25;
      orbRef.current?.style.setProperty('--level', shown.toFixed(3));
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [levelRef]);

  return (
    <nav className="zen-dock" aria-label="Main">
      <button type="button" className="zen-dock__btn" onClick={onHome} aria-label="Home"><IconHome /></button>
      <button type="button" className="zen-dock__btn" onClick={onProgress} aria-label="Progress"><IconChart /></button>
      <button
        ref={orbRef}
        type="button"
        className={`zen-orb zen-orb--${j.mode} ${j.handsFree ? 'is-handsfree' : ''}`}
        onClick={j.activate}
        aria-label={ORB_TITLE[j.mode]}
        title={ORB_TITLE[j.mode]}
      >
        <Diamond />
      </button>
      <button type="button" className="zen-dock__btn" onClick={onRoutines} aria-label="Routines">
        <IconClock />
        {routineCount > 0 && <span className="zen-badge zen-badge--dot">{routineCount}</span>}
      </button>
      <button type="button" className="zen-dock__btn" onClick={onFiles} aria-label="Files"><IconFolder /></button>
    </nav>
  );
}
