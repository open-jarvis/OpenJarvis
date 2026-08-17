import { useKioskState, type KioskState } from '@/hooks/useKioskState';
import { kioskStateLabel } from '@/hooks/voiceUiText';
import type { UiLanguage } from '@/hooks/useUiLanguage';
import { useEffect, useRef, useState } from 'react';

const STATE_COLOR: Record<KioskState, { bg: string; border: string; color: string }> = {
  idle:        { bg: 'rgba(255,255,255,.05)', border: 'rgba(255,255,255,.15)', color: 'rgba(255,255,255,.4)' },
  approaching: { bg: 'rgba(0,242,254,.08)',   border: 'rgba(0,242,254,.25)',    color: '#00f2fe' },
  prompting:   { bg: 'rgba(0,242,254,.08)',   border: 'rgba(0,242,254,.25)',    color: '#00f2fe' },
  active:      { bg: 'rgba(0,255,100,.08)',   border: 'rgba(0,255,100,.3)',     color: '#00ff64' },
  cleanup:     { bg: 'rgba(255,180,80,.12)',  border: 'rgba(255,180,80,.35)',   color: '#ffb450' },
};

const FADE_MS = 350;

export function KioskOverlay({
  showOverlay = true,
  uiLanguage,
}: {
  showOverlay?: boolean;
  uiLanguage: UiLanguage;
}) {
  const { state, respond } = useKioskState();
  const c = STATE_COLOR[state];

  // Track previous state so we can delay unmounting the consent popup
  // when the user dismisses it (prompting → idle or prompting → active).
  const prevStateRef = useRef<KioskState>(state);
  const [showPopup, setShowPopup] = useState(state === 'prompting');
  const [popupVisible, setPopupVisible] = useState(state === 'prompting');
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const prev = prevStateRef.current;
    prevStateRef.current = state;

    // Entering prompting — show popup immediately.
    if (state === 'prompting') {
      if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
      setShowPopup(true);
      // Force a frame so the browser registers the DOM node before we set opacity → 0 transition from 1.
      requestAnimationFrame(() => setPopupVisible(true));
      return;
    }

    // Exiting prompting — fade out, then unmount.
    if ((prev as KioskState) === 'prompting') {
      setPopupVisible(false); // triggers CSS opacity 1 → 0
      timerRef.current = setTimeout(() => {
        setShowPopup(false);
        timerRef.current = null;
      }, FADE_MS);
    }

    return () => {
      if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
    };
  }, [state]);

  return (
    <>
      {/* State banner — conditionally visible */}
      {showOverlay && (
        <div
          className="absolute top-4 left-1/2 -translate-x-1/2 z-40 px-4 py-2 rounded-full text-[13px] font-medium transition-all duration-500"
          style={{ background: c.bg, border: `1px solid ${c.border}`, color: c.color }}
        >
          {/* Inner span: the pill keeps its own background, the text gets the sweep. */}
          <span
            className="text-shimmer"
            style={{ '--shimmer-base': c.color, '--shimmer-highlight': '#ffffff' } as React.CSSProperties}
          >
            {kioskStateLabel(uiLanguage, state)}
          </span>
        </div>
      )}

      {/* Consent popup — mounted while prompting or still fading out */}
      {showPopup && (
        <div
          className="absolute inset-0 z-50 flex items-center justify-center transition-opacity"
          style={{
            background: 'rgba(0,0,0,.6)',
            opacity: popupVisible ? 1 : 0,
            transitionDuration: `${FADE_MS}ms`,
          }}
        >
          <div
            className="rounded-2xl p-8 text-center max-w-sm mx-4 shadow-2xl transition-all"
            style={{
              background: '#14141e',
              border: '1px solid rgba(255,255,255,.1)',
              transform: popupVisible ? 'scale(1)' : 'scale(0.95)',
              transitionDuration: `${FADE_MS}ms`,
            }}
          >
            <div className="text-4xl mb-4">🤖</div>
            <h2 className="text-xl font-semibold mb-2" style={{ color: '#fff' }}>
              Talk to the AI?
            </h2>
            <p className="text-sm mb-6" style={{ color: 'rgba(255,255,255,.5)' }}>
              Would you like to start a voice conversation with the AI assistant?
            </p>
            <div className="flex gap-3 justify-center">
              <button
                onClick={() => respond(true)}
                className="px-6 py-2.5 rounded-xl text-sm font-semibold cursor-pointer transition-all hover:scale-105"
                style={{ background: 'var(--color-accent)', color: '#fff' }}
              >
                Yes
              </button>
              <button
                onClick={() => respond(false)}
                className="px-6 py-2.5 rounded-xl text-sm font-semibold cursor-pointer transition-all hover:scale-105"
                style={{ background: 'rgba(255,255,255,.08)', color: 'rgba(255,255,255,.7)', border: '1px solid rgba(255,255,255,.1)' }}
              >
                No
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
