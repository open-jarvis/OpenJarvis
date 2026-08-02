# JARVIS frontend, avatar, and animation contract

This document describes the visible Jarvis experience. It deliberately does not define or
replace the text-to-speech, speech-to-text, microphone capture, audio encoding, or model
implementation.

## Visible modes

- **Talk** is the default final-attach view. It renders the approved cosmic portrait, a quiet
  visual state, microphone control, interruption control, the mode switcher, and the collapsed
  menu. It never renders chat messages, transcripts, tool output, model information, paths,
  raw JSON, plans, or task timelines.
- **Text** keeps the same session and renders only persisted `chat.user_message` and
  `chat.assistant_message` events. Markdown, code blocks, tables, links, and bidirectional text
  are supported. Other canonical task events remain persisted but invisible here.
- A new conversation calls the existing canonical interrupt boundary when needed, stops the
  current UI speech state, creates a new session ID, and clears the visible timeline.

## Approved avatar asset

- Runtime path: `frontend/public/assets/jarvis/cosmic-face.png`
- SHA-256: `BE9B0A872B6A853D178B3D56465C881DE4EA2070E034B5E8AFE2CFFBF2A84C1B`
- Resolution: 1254 × 1254
- The approved PNG is byte-identical to the supplied reference. The face, eyes, forehead, and
  mouth are not regenerated, retouched, or filtered.

The base image is a single stable layer. CSS-only stars, nebula, particles, aura, and rim layers
sit behind or around it. No overlay targets the eyes. The portrait image is always rendered with
`object-fit: contain` and `filter: none`.

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
  errorMessage: string | null; // user-safe message only
  interruptRequested: boolean;
  updatedAt: number;
}
```

Frontend actions are `startListening`, `stopListening`, `cancelListening`,
`interruptSpeech`, and `startNewConversation`. The existing `useSpeech` and
`useTextToSpeech` hooks are mapped into this snapshot by `deriveVoiceSnapshot`; no second
production voice pipeline exists.

`MockVoiceAdapter` is development-only. It captures and plays no audio. It simulates state and
bounded volume values so animation, interruption, and fallback behavior can be tested. It is
available only after the user enables Developer Mode and the mock explicitly.

## Mouth animation

Mouth movement defaults to **Off** because the approved portrait has a textured, closed mouth.
When the user explicitly selects Subtle or Normal, a small black aperture layer may open by at
most 2.4 CSS pixels from normalized volume data. It never reveals teeth, deforms the face, or
touches the eye region. It closes immediately outside `speaking` and is disabled in fallback
tiers 2–4.

## Performance and fallback

The visual layer uses CSS transforms, opacity, gradients, and a bounded set of 16 particles.
It does not run a canvas, WebGL context, external video generator, or per-answer frame process.
The performance hook samples `requestAnimationFrame`, observes page visibility and operating
system reduced-motion preferences, and selects:

1. mouth plus background animation;
2. background animation only;
3. static portrait with a quiet aura;
4. fully static portrait.

Hidden windows, disabled animation, and reduced motion use tier 4. Listeners and animation-frame
callbacks are removed during cleanup. Audio analysis is not started by this frontend.

## Settings and diagnostics

The collapsed top-left menu exposes only working actions: new conversation, Talk, Text, Avatar &
Animations, Settings, and (when enabled) Developer Mode. Appearance settings persist locally.
Developer Mode is off by default and shows only session suffix, UI voice state, normalized volume,
FPS, and fallback tier. It does not expose prompts, tool payloads, model routing, private content,
or secrets.

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
