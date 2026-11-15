/**
 * Original vector art for the home screen, drawn in code in the lavender
 * palette: misty skylines, a glowing crystal, a ring gate, the Jarvis emblem.
 */
import { useId } from 'react';

type Scene = 'city' | 'mountain' | 'sea';

/** Layered misty scene with an optional lone figure. */
export function Skyline({ scene = 'city', figure = false, className = '' }: { scene?: Scene; figure?: boolean; className?: string }) {
  const id = useId().replace(/:/g, '');
  const far = scene === 'mountain'
    ? 'M0,120 L60,70 L95,95 L150,40 L210,100 L260,60 L320,110 L320,160 L0,160Z'
    : scene === 'sea'
      ? 'M0,118 C60,110 120,124 180,116 C240,108 280,120 320,114 L320,160 L0,160Z'
      : 'M0,110 h18 v-38 h14 v24 h12 v-52 h10 v-14 h6 v14 h10 v66 h16 v-30 h20 v40 h14 v-70 h8 v-12 h4 v12 h8 v58 h18 v-22 h22 v36 h12 v-48 h16 v48 h20 v-28 h18 v42 h30 v58 H0Z';
  const near = scene === 'mountain'
    ? 'M0,140 L70,105 L120,128 L190,92 L250,130 L320,118 L320,160 L0,160Z'
    : scene === 'sea'
      ? 'M0,136 C50,130 110,142 170,134 C230,126 280,140 320,132 L320,160 L0,160Z'
      : 'M0,132 h26 v-26 h18 v18 h22 v-40 h12 v40 h28 v-18 h20 v30 h18 v-50 h10 v50 h26 v-22 h24 v28 h40 v-14 h24 v14 h32 v30 H0Z';
  return (
    <svg className={`zen-art ${className}`} viewBox="0 0 320 160" preserveAspectRatio="xMidYMax slice" aria-hidden="true">
      <defs>
        <linearGradient id={`${id}-sky`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#f6f4ff" />
          <stop offset="1" stopColor="#dcd8fb" />
        </linearGradient>
        <linearGradient id={`${id}-far`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#c9c4f4" stopOpacity="0.55" />
          <stop offset="1" stopColor="#e9e7fb" stopOpacity="0.2" />
        </linearGradient>
        <linearGradient id={`${id}-near`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#a99ff0" stopOpacity="0.75" />
          <stop offset="1" stopColor="#efedfd" stopOpacity="0.6" />
        </linearGradient>
        <radialGradient id={`${id}-sun`} cx="0.72" cy="0.3" r="0.35">
          <stop offset="0" stopColor="#ffffff" stopOpacity="0.95" />
          <stop offset="1" stopColor="#ffffff" stopOpacity="0" />
        </radialGradient>
      </defs>
      <rect width="320" height="160" fill={`url(#${id}-sky)`} />
      <rect width="320" height="160" fill={`url(#${id}-sun)`} />
      <path d={far} fill={`url(#${id}-far)`} />
      <path d={near} fill={`url(#${id}-near)`} />
      {figure && (
        <g fill="#5b54a8" opacity="0.85">
          <circle cx="232" cy="118" r="3.2" />
          <path d="M228.5,122 h7 l1.2,13 h-2.4 l-1,-7 l-0.8,7 h-2.2 l-0.8,-7 l-1,7 h-2.4Z" />
        </g>
      )}
      {[30, 88, 140, 205, 270, 300].map((x, i) => (
        <circle key={x} className="zen-mote" cx={x} cy={20 + ((i * 37) % 70)} r={i % 2 ? 1.2 : 1.8} style={{ animationDelay: `${i * 0.9}s` }} />
      ))}
    </svg>
  );
}

/** Faceted crystal on a pedestal (focus streak). */
export function Crystal({ className = '' }: { className?: string }) {
  const id = useId().replace(/:/g, '');
  return (
    <svg className={`zen-crystal ${className}`} viewBox="0 0 140 150" aria-hidden="true">
      <defs>
        <linearGradient id={`${id}-a`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#e9e6ff" />
          <stop offset="1" stopColor="#6d5dfc" />
        </linearGradient>
        <linearGradient id={`${id}-b`} x1="1" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#b9b0ff" />
          <stop offset="1" stopColor="#4d40d8" />
        </linearGradient>
        <radialGradient id={`${id}-glow`} cx="0.5" cy="0.55" r="0.5">
          <stop offset="0" stopColor="#8b7bff" stopOpacity="0.45" />
          <stop offset="1" stopColor="#8b7bff" stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx="70" cy="70" r="66" fill={`url(#${id}-glow)`} />
      <g className="zen-crystal__gem">
        <polygon points="70,8 100,58 70,108 40,58" fill={`url(#${id}-a)`} />
        <polygon points="70,8 100,58 70,62" fill="#ffffff" opacity="0.55" />
        <polygon points="70,62 100,58 70,108" fill={`url(#${id}-b)`} />
        <polygon points="40,58 70,62 70,108" fill="#7a6cf5" opacity="0.85" />
      </g>
      <ellipse cx="70" cy="126" rx="44" ry="9" fill="#d9d5fb" />
      <ellipse cx="70" cy="122" rx="36" ry="6.5" fill="#f2f0ff" />
      <ellipse cx="70" cy="121" rx="22" ry="3.5" fill="#b6acfb" opacity="0.6" />
    </svg>
  );
}

/** Ring gate with a figure walking toward it (mission banner). */
export function Gate({ className = '' }: { className?: string }) {
  const id = useId().replace(/:/g, '');
  return (
    <svg className={`zen-art ${className}`} viewBox="0 0 320 200" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <defs>
        <linearGradient id={`${id}-sky`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#f4f2ff" />
          <stop offset="1" stopColor="#d4cff8" />
        </linearGradient>
        <linearGradient id={`${id}-ring`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="1" stopColor="#9c90f6" />
        </linearGradient>
      </defs>
      <rect width="320" height="200" fill={`url(#${id}-sky)`} />
      <path d="M0,150 h30 v-50 h14 v34 h20 v-70 h12 v70 h24 v-30 h16 v46 H0Z M220,150 v-40 h18 v24 h16 v-60 h12 v60 h22 v-34 h32 v50Z" fill="#c4bdf3" opacity="0.6" />
      <g className="zen-gate">
        <ellipse cx="160" cy="92" rx="54" ry="62" fill="none" stroke={`url(#${id}-ring)`} strokeWidth="11" />
        <ellipse cx="160" cy="92" rx="40" ry="48" fill="none" stroke="#ffffff" strokeOpacity="0.7" strokeWidth="2" strokeDasharray="4 7" />
      </g>
      <rect x="0" y="150" width="320" height="50" fill="#e7e4fb" />
      <path d="M0,160 C80,152 240,168 320,158 L320,200 L0,200Z" fill="#d7d2f7" opacity="0.7" />
      <g fill="#4d468f">
        <circle cx="160" cy="150" r="3.4" />
        <path d="M156.3,154 h7.4 l1.3,14 h-2.6 l-1,-7 l-0.9,7 h-2.4 l-0.9,-7 l-1,7 h-2.6Z" />
      </g>
    </svg>
  );
}

/** Jarvis emblem used as the profile avatar. */
export function Emblem({ initials }: { initials: string }) {
  const id = useId().replace(/:/g, '');
  return (
    <svg className="zen-emblem" viewBox="0 0 120 120" aria-hidden="true">
      <defs>
        <linearGradient id={`${id}-bg`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#f7f5ff" />
          <stop offset="1" stopColor="#d6d0fb" />
        </linearGradient>
        <linearGradient id={`${id}-gem`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#b3a8ff" />
          <stop offset="1" stopColor="#5a4be6" />
        </linearGradient>
      </defs>
      <circle cx="60" cy="60" r="56" fill={`url(#${id}-bg)`} />
      <path
        d="M14,92 h10 v-20 h8 v14 h8 v-30 h6 v30 h10 v-16 h10 v24 h8 v-40 h6 v40 h12 v-18 h12 v22 h8 v-12 h8 v24 a56,56 0 0 1 -86,0Z"
        fill="#b9b1f5"
        opacity="0.5"
      />
      <polygon points="60,22 84,56 60,90 36,56" fill={`url(#${id}-gem)`} opacity="0.92" />
      <polygon points="60,22 84,56 60,58" fill="#ffffff" opacity="0.4" />
      <text x="60" y="62" textAnchor="middle" className="zen-emblem__text">{initials}</text>
    </svg>
  );
}

/** The Jarvis diamond (dock orb, brand). */
export function Diamond({ className = '' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true">
      <polygon points="12,2 21,11 12,22 3,11" fill="currentColor" opacity="0.9" />
      <polygon points="12,2 21,11 12,12" fill="#fff" opacity="0.45" />
      <polygon points="3,11 12,12 12,22" fill="#000" opacity="0.12" />
    </svg>
  );
}
