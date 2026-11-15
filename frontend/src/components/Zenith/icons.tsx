/** Thin line icons matching the home screen style (24px grid, currentColor). */
import type { ReactNode } from 'react';

const Icon = ({ children }: { children: ReactNode }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {children}
  </svg>
);

export const IconGrid = () => <Icon><rect x="4" y="4" width="6.5" height="6.5" rx="1.5" /><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5" /><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5" /><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5" /></Icon>;
export const IconTarget = () => <Icon><circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="4.5" /><circle cx="12" cy="12" r="1.2" /></Icon>;
export const IconMoon = () => <Icon><path d="M19 14.5A7.5 7.5 0 0 1 9.5 5a7.5 7.5 0 1 0 9.5 9.5Z" /></Icon>;
export const IconBook = () => <Icon><path d="M4 5.5C6.5 4.5 9.5 4.5 12 6c2.5-1.5 5.5-1.5 8-.5v13c-2.5-1-5.5-1-8 .5-2.5-1.5-5.5-1.5-8-.5Z" /><path d="M12 6v13.5" /></Icon>;
export const IconChart = () => <Icon><path d="M4 20V4" /><path d="M4 20h16" /><path d="M7 15l4-4 3 3 5-6" /></Icon>;
export const IconBars = () => <Icon><path d="M6 19v-6" /><path d="M10 19V9" /><path d="M14 19v-9" /><path d="M18 19V6" /></Icon>;
export const IconQuote = () => <Icon><path d="M9 7H6a2 2 0 0 0-2 2v3h5V7Z" /><path d="M9 12c0 3-1.5 4.5-4 5" /><path d="M19 7h-3a2 2 0 0 0-2 2v3h5V7Z" /><path d="M19 12c0 3-1.5 4.5-4 5" /></Icon>;
export const IconClock = () => <Icon><circle cx="12" cy="12" r="8" /><path d="M12 7.5V12l3 2" /></Icon>;
export const IconFolder = () => <Icon><path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v7.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2Z" /></Icon>;
export const IconHome = () => <Icon><path d="M4 11l8-6.5 8 6.5" /><path d="M6 9.5V19h4.5v-5h3v5H18V9.5" /></Icon>;
export const IconUser = () => <Icon><circle cx="12" cy="8.5" r="3.5" /><path d="M5 19.5c1.2-3.3 3.8-5 7-5s5.8 1.7 7 5" /></Icon>;
export const IconMic = () => <Icon><rect x="9" y="3.5" width="6" height="11" rx="3" /><path d="M5.5 11a6.5 6.5 0 0 0 13 0" /><path d="M12 17.5V21" /></Icon>;
export const IconClip = () => <Icon><path d="M16 7.5 9.2 14.3a2 2 0 0 0 2.8 2.8l7-7a4 4 0 0 0-5.7-5.7L6 11.8a6 6 0 0 0 8.5 8.5L20 14.8" /></Icon>;
export const IconCamera = () => <Icon><path d="M4 8.5a2 2 0 0 1 2-2h2l1.5-2h5L16 6.5h2a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z" /><circle cx="12" cy="12.5" r="3.5" /></Icon>;
export const IconSend = () => <Icon><path d="M5 12h13" /><path d="M13 6l6 6-6 6" /></Icon>;
export const IconPlus = () => <Icon><path d="M12 5v14" /><path d="M5 12h14" /></Icon>;
export const IconCheck = () => <Icon><path d="M5 12.5l4.5 4.5L19 7.5" /></Icon>;
export const IconFlag = () => <Icon><path d="M5.5 21V4" /><path d="M5.5 4.5h11l-2 4 2 4h-11" /></Icon>;
export const IconBookmark = ({ filled = false }: { filled?: boolean }) => (
  <svg viewBox="0 0 24 24" fill={filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" aria-hidden="true">
    <path d="M7 4h10v16l-5-3.5L7 20Z" />
  </svg>
);
export const IconSpeaker = () => <Icon><path d="M5 10v4h3l4 3.5v-11L8 10Z" /><path d="M15.5 9a4 4 0 0 1 0 6" /><path d="M18 6.5a7.5 7.5 0 0 1 0 11" /></Icon>;
export const IconWave = () => <Icon><path d="M4 12h2" /><path d="M8 8v8" /><path d="M12 5v14" /><path d="M16 8v8" /><path d="M20 12h-2" /></Icon>;
export const IconSettings = () => <Icon><circle cx="12" cy="12" r="3" /><path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2M6 6l1.6 1.6M16.4 16.4 18 18M6 18l1.6-1.6M16.4 7.6 18 6" /></Icon>;
