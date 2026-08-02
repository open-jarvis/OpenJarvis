# JARVIS frontend, avatar, and animation contract

This document describes the visible Jarvis experience. It deliberately does not define or
replace text-to-speech, speech-to-text, microphone capture, audio encoding, or model
implementation.

## Visible modes

- **Talk** is the default final-attach view. It renders the wide cosmic entity, live visual
  state, microphone and interruption controls, the mode switcher, and the collapsed menu. It
  never renders chat messages, transcripts, tool output, model information, paths, raw JSON,
  plans, or task timelines.
- **Text** keeps the same session and renders only persisted `chat.user_message` and
  `chat.assistant_message` events. The same wide entity remains alive as a blended background
  scene instead of becoming a square corner image.
- A new conversation calls the existing canonical interrupt boundary when needed, stops the
  current UI speech state, creates a new session ID, and clears the visible timeline.

## Avatar assets

- Runtime path: `frontend/public/assets/jarvis/cosmic-entity-wide-v2.png`
- SHA-256: `3A07A106E2481DC016CED0350B349615AAA02A1DC1566F5305DEF7D9C65F438A`
- Resolution: 1672 x 941 (16:9)
- Reference archive: `frontend/public/assets/jarvis/cosmic-face.png`, still byte-identical to the
  supplied 1254 x 1254 reference with SHA-256
  `BE9B0A872B6A853D178B3D56465C881DE4EA2070E034B5E8AFE2CFFBF2A84C1B`.

The runtime source was generated with the built-in ImageGen workflow as a wide monochrome cosmic
entity: one centered face and upper torso, empty black eyes, no iris, pupil, forehead mark, text,
logo, extra face, or hard picture-frame edge. The reference was treated as visual direction, not
as an edit target.

The source is one stable layer. CSS nebula, aura, scan, orbit, and voice-wave layers plus the
bounded `CosmicField` canvas sit around it. The canvas animates deterministic stars and reacts to
Idle, Listening, Processing, and Speaking. No overlay targets the eyes.

## Voice integration contract

`VoiceStateAdapter` is the frontend boundary. A production adapter supplies a
`VoiceAdapterSnapshot`:

```ts
type JarvisVoiceState =
  | 'idle'
  | 'listening'
  | 'processing'
  | 'speaking'
  | 'interrupted'
  | 'error'
  | 'offline'
  | 'reconnecting';

interface VoiceAdapterSnapshot {
  state: JarvisVoiceState;
  microphoneState: 'unavailable' | 'off' | 'on' | 'processing' | 'error';
  playbackState: 'idle' | 'playing' | 'paused' | 'interrupted' | 'error';
  volumeLevel: number;          // normalized 0..1
  speakingProgress: number | null;
  transcriptReady: boolean;
  errorMessage: string | null;  // user-safe message only
  interruptRequested: boolean;
  updatedAt: number;
}
```

The existing `useSpeech` and `useTextToSpeech` hooks are mapped into this snapshot by
`deriveVoiceSnapshot`; no second production voice pipeline exists. Productive TTS publishes
`openjarvis:audio-start`, `openjarvis:audio-level`, and `openjarvis:audio-end`. The avatar consumes
the normalized level without renaming or replacing that contract.

`MockVoiceAdapter` is development-only. It captures and plays no audio. It simulates state and
bounded volume values so animation and fallback behavior can be tested.

## Mouth and voice animation

Mouth movement defaults to **Subtle**. A small black aperture may open by at most 2.4 CSS pixels
from normalized volume data; it never reveals teeth, deforms the face, or touches the eye region.
The more visible speaking response is intentionally carried by the live particle field, aura,
breathing portrait, and nine-bar voice wave. Listening draws particles inward, Processing rotates
the orbital field, and Speaking uses the real audio level when present plus a visual fallback
envelope so supported voices never look static.

## Performance and fallback

The visual layer uses CSS transforms, opacity, gradients, and one bounded 2D canvas with 34-88
deterministic particles. It does not run WebGL, an external video generator, or a per-answer
process. Canvas resolution is capped at 1.5 device pixels, pauses when the document is hidden, and
disconnects its `ResizeObserver` and animation frame during cleanup. The performance hook samples
`requestAnimationFrame`, observes page visibility and reduced-motion preferences, and selects:

1. full canvas, mouth, orbit, scan, and background animation;
2. reduced particle count and no mouth movement;
3. CSS-only portrait, aura, and one orbit;
4. fully static portrait.

Hidden windows, disabled animation, and reduced motion use tier 4. Audio analysis remains owned by
the existing voice provider; this frontend only consumes its normalized events.

## Settings and diagnostics

The collapsed menu exposes new conversation, Talk, Text, Avatar & Animations, Settings, and
Developer Mode. Appearance settings persist locally. Developer Mode is off by default and shows
only session suffix, UI voice state, normalized volume, FPS, and fallback tier. The Voice section
embeds the existing voice audition panel instead of implementing another voice system.

## Commands

From `frontend/`:

```powershell
npm ci
npm test
npm run build
npm run build:tauri
```

The native Rust/Tauri packaging command remains `npm run tauri build`; it additionally requires
the Rust/Cargo toolchain to be available in the caller's environment.
