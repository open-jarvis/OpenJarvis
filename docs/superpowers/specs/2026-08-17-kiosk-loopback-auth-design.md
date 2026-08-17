# Kiosk Loopback Authentication Design

## Goal

Make the local Kiosk flow work without copying the OpenJarvis API key into the
browser. A person detected by the Vision WebSocket inside the configured zone
must drive the Kiosk FSM from `idle` to `approaching` to `prompting`, where the
browser shows the existing Yes/No consent popup.

## Scope

- Enable the Kiosk subsystem at runtime with `KIOSK_ENABLED=true` and
  `KIOSK_VISION_URL=ws://127.0.0.1:9876`.
- Exempt Kiosk browser traffic from API-key authentication only when the remote
  peer is loopback (`127.0.0.1` or `::1`).
- Keep authentication mandatory for non-loopback clients.
- Do not change Vision event schema, Kiosk FSM timing, popup visuals, voice
  policy, model selection, or provider credentials.

## Authentication Design

The existing HTTP authentication middleware will accept the request without a
Bearer token only when both conditions hold:

1. The client address is loopback.
2. The path starts with `/api/kiosk/`.

The existing `/v1/agents/events` WebSocket handler will accept a tokenless
connection when its client address is loopback. Non-loopback WebSocket clients
continue to require the configured API key.

`/v1/agents/events` is a shared agent-event stream rather than a Kiosk-only
stream. Therefore a local process or browser can observe all events published
on that endpoint. This is the explicitly accepted security trade-off of the
simple loopback exemption. Creating a Kiosk-only WebSocket is out of scope.

Loopback decisions use the request or WebSocket peer address, not the `Host`,
`Origin`, or forwarded headers. Proxies cannot opt a remote client into the
exemption by changing headers.

## Runtime Data Flow

1. Vision publishes `person_near` events at `ws://127.0.0.1:9876`.
2. `VisionClient` consumes those events and feeds `kiosk_main`.
3. The existing FSM applies the configured 1 m threshold, 0.4 s entry debounce,
   and 2 s approach sustain.
4. `kiosk_main` publishes `kiosk_state_changed` events.
5. The local Kiosk page consumes `/v1/agents/events` without a token.
6. On `prompting`, the existing overlay shows Yes/No.
7. A local response posts to `/api/kiosk/respond` without a token; remote
   responses still require authentication.

## Tests

Regression tests will prove:

- A loopback HTTP request to `/api/kiosk/respond` is allowed without a token.
- A non-loopback HTTP request to the same path still receives `401`.
- Other protected loopback API paths still require authentication.
- A loopback `/v1/agents/events` WebSocket is accepted without a token.
- A non-loopback WebSocket still requires the configured key.
- Existing authenticated HTTP and WebSocket behavior remains valid.

Tests are written and observed failing before production changes.

## Manual Acceptance

Run the backend with Kiosk enabled and the existing provider credentials, then
open `http://localhost:5173/kiosk`. With Vision reporting a stable distance
below 1 m:

- the banner transitions `idle -> approaching -> prompting`;
- the Yes/No popup appears after the existing sustain interval;
- selecting Yes or No returns HTTP 200 and advances the existing FSM policy;
- moving out of the zone returns the system to the appropriate idle/cleanup
  state according to the existing timers.

## Non-goals

- No public unauthenticated Kiosk deployment.
- No trust in `X-Forwarded-For` or similar headers.
- No new Kiosk-only event endpoint.
- No changes to the Vision process or depth calculation.
- No automatic Voice/Live behavior beyond what current Kiosk side effects
  already implement.
