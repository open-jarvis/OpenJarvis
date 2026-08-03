# JARVIS star/core frontend and animation contract

The legacy filename is retained for documentation links. The visible runtime
contains no avatar, portrait, face, eyes, mouth or mouth animation.

## Visible modes

- **Talk** centers an abstract canvas star field and black/silver core with a
  microphone, Stop, state text, selected/actual provider and visible fallback.
- **Text** keeps the same canonical session and renders persisted user and
  assistant messages with Markdown and structured tool/action cards. A small
  core may remain as decoration; there is no large character graphic.
- **New** cancels current UI fetch, TTS, STT, processing audio and controllable
  desktop/MCP work before creating the new visible session.

## Voice-state boundary

`VoiceStateAdapter` maps the existing production hooks into one snapshot. It
does not capture, transcribe, synthesize or play audio itself. Listening volume
comes from the one real microphone stream. Speaking volume comes from the real
`HTMLAudioElement` analyser. Processing is derived from the canonical task
state, not a fake speech envelope.

The canvas has bounded particle tiers for full, reduced, hidden and constrained
rendering. It caps resolution, pauses when the page is hidden, releases its
animation frame and `ResizeObserver`, and respects reduced motion. Visual state
remains distinguishable with readable labels when animation is reduced.

## States

- Idle: slow drift, depth and a restrained shared breath.
- Listening: real level drives radial, vertical and turbulent response.
- Processing: magnetic convergence/swirl, with an optional quiet local Web
  Audio bass tone.
- Speaking: real playback level drives core and particle response.
- Interrupted/error/offline: restrained visual change plus explicit text;
  color is not the only signal.

The processing tone owns one reusable `AudioContext`, fades its gain, and stops
on response, error, Stop, barge-in, page hide or unmount.

## Controls and diagnostics

Talk/Text/New/menu controls remain outside the main particle interaction area
and use responsive safe spacing. Escape stops current output/action. Space,
when focus is not inside an interactive field, performs barge-in from speaking
or processing. Developer/settings surfaces show voice, desktop and MCP health;
the calm Talk surface does not dump raw traces.

See [`jarvis-manual-verification.md`](jarvis-manual-verification.md) for the
manual window-size, DPI, animation, audio and error checklist. No build or
visual smoke test is implied by this document.
