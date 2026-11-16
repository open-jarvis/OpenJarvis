/**
 * Frontend analytics client.
 *
 * Thin wrapper around posthog-js that:
 *   - Pulls its identity (anon_id, host, project key) from the backend
 *     via GET /v1/analytics/identity, so all backend / install.sh /
 *     frontend events tie to the same person.
 *   - Initializes posthog-js with autocapture, session replay, and
 *     pageviews disabled — we send only events we explicitly call out.
 *   - Registers the app version as a super-property so every event
 *     carries it uniformly (no per-event repetition needed).
 *   - Fails silently when the backend isn't reachable, when analytics
 *     is disabled, or when the SDK throws — must never break the UI.
 *
 * Opt-out matches the backend: if /identity returns enabled=false
 * (analytics disabled in config), the SDK is never
 * initialized and track() becomes a no-op.
 */

import posthog from 'posthog-js';
import { apiFetch } from './api';

/**
 * Mirror of the Python event catalog (src/openjarvis/analytics/events.py
 * REGISTRY). Anything not in this set is dropped with a console.warn at
 * track() time, so typos and unallowed events don't silently ship.
 *
 * KEEP IN SYNC with the Python REGISTRY. CI could enforce this later.
 */
const KNOWN_EVENTS = new Set<string>([
  'install_started',
  'install_stage_completed',
  'install_completed',
  'install_failed',
  'uninstall_started',
  'app_opened',
  'setup_completed',
  'first_chat_sent',
  'chat_session_ended',
  'tool_first_used',
  'model_changed',
  'connector_auth_completed',
  'feature_used',
  'feedback_submitted',
  'error_shown_to_user',
  'settings_changed',
  'usage_daily_summary',
]);

// Hardcoded app version — should match the backend.
// TODO: wire to Vite define() so this comes from package.json at build time.
const APP_VERSION = '0.1.0';

export interface AnalyticsIdentity {
  enabled: boolean;
  anon_id: string;
  host: string;
  key: string;
  choice_recorded?: boolean;
}

let initialized = false;
let enabledState = false;
let cachedAnonId = '';
let generation = 0;
let sdkReady: Promise<void> | null = null;

export async function fetchAnalyticsIdentity(): Promise<AnalyticsIdentity> {
  const response = await apiFetch('/v1/analytics/identity');
  if (!response.ok) throw new Error('Could not load the analytics setting.');
  return response.json();
}

export async function saveAnalyticsPreference(enabled: boolean): Promise<void> {
  if (!enabled) {
    // Stop the browser sender before waiting for the persistence request.
    generation += 1;
    initialized = false;
    enabledState = false;
    cachedAnonId = '';
    try { posthog.opt_out_capturing(); } catch { /* never break the UI */ }
  }
  const response = await apiFetch('/v1/analytics/preference', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  });
  if (!response.ok) throw new Error('Could not save your analytics choice. Please try again.');
  const identity: AnalyticsIdentity = await response.json();
  if (identity.enabled !== enabled) throw new Error('Analytics choice was not saved.');
  if (enabled) {
    await initAnalytics(true);
  }
}

/**
 * Fetch identity from the backend and initialize the SDK.
 * Idempotent — safe to call multiple times.
 */
export async function initAnalytics(force = false): Promise<void> {
  if (initialized && !force) return;
  const currentGeneration = ++generation;
  initialized = true; // claim the slot even on failure paths

  try {
    const identity = await fetchAnalyticsIdentity();
    if (currentGeneration !== generation) return;
    if (!identity.enabled || !identity.key || !identity.anon_id) {
      return;
    }

    cachedAnonId = identity.anon_id;

    // PostHog ignores repeated init() calls. Share the first initialization,
    // then explicitly resume capture for every later opt-in.
    if (!sdkReady) {
      sdkReady = new Promise<void>((resolve) => {
        posthog.init(identity.key, {
          api_host: identity.host,
          bootstrap: { distinctID: identity.anon_id },
          // No surprise data collection — only events we call out by name.
          autocapture: false,
          capture_pageview: false,
          capture_pageleave: false,
          disable_session_recording: true,
          // No /decide call for feature flags (saves a request, we don't use them yet).
          advanced_disable_decide: true,
          // No PostHog person profiles — we're not making accounts, just sending events.
          person_profiles: 'never',
          // Don't try to load IP geolocation; backend disables this too.
          ip: false,
          loaded: () => resolve(),
        });
      });
    }
    await sdkReady;
    if (currentGeneration !== generation) return;
    posthog.opt_in_capturing({ captureEventName: false });
    enabledState = true;

    // Set distinct_id explicitly in case bootstrap raced.
    posthog.identify(identity.anon_id);

    // Register version + platform as super-properties so they're attached
    // to every event automatically, without per-call-site repetition.
    posthog.register({
      version: APP_VERSION,
      platform: detectPlatform(),
    });
  } catch {
    // Any failure → analytics off, silently.
  }
}

/**
 * Send one event. Properties are passed through to PostHog; redaction
 * happens server-side for backend events. Unknown event names are
 * dropped here with a console.warn so typos surface in dev rather than
 * silently landing in the analytics warehouse.
 */
export function track(
  event: string,
  properties: Record<string, unknown> = {},
): void {
  if (!enabledState) return;
  if (!KNOWN_EVENTS.has(event)) {
    if (import.meta.env.DEV) {
      console.warn(
        `[analytics] Unknown event "${event}" dropped. ` +
          `Add it to KNOWN_EVENTS in lib/analytics.ts and to the Python ` +
          `REGISTRY in src/openjarvis/analytics/events.py.`,
      );
    }
    return;
  }
  try {
    posthog.capture(event, properties);
  } catch {
    // never throw
  }
}

/** Force-flush queued events. Call on visibilitychange / pagehide. */
export function flush(): void {
  if (!enabledState) return;
  try {
    // posthog-js queues then flushes async; this is best-effort.
    // The SDK doesn't expose a direct flush, but the page lifecycle
    // hooks below cause a beacon-style flush automatically.
  } catch {
    // never throw
  }
}

export function isAnalyticsEnabled(): boolean {
  return enabledState;
}

export function getAnonId(): string {
  return cachedAnonId;
}

/**
 * Hash an identifier to a 16-char sha256 hex prefix.
 *
 * Used for model / tool names that we want to cohort on without
 * actually shipping the raw value (e.g. proprietary model names a
 * power user has configured). Mirror of the backend's
 * :func:`openjarvis.analytics.redaction.hash_id`.
 */
export async function hashId(s: string): Promise<string> {
  if (!s) return '';
  try {
    const data = new TextEncoder().encode(s);
    const buf = await crypto.subtle.digest('SHA-256', data);
    return Array.from(new Uint8Array(buf))
      .slice(0, 8)
      .map((b) => b.toString(16).padStart(2, '0'))
      .join('');
  } catch {
    return '';
  }
}

/**
 * Detect platform string conforming to the events.py allowlist:
 * "tauri-macos" | "tauri-linux" | "tauri-windows" | "web".
 */
export function detectPlatform(): string {
  const ua =
    typeof navigator !== 'undefined' ? navigator.userAgent.toLowerCase() : '';
  const isTauri =
    typeof window !== 'undefined' &&
    !!(window as unknown as { __TAURI_INTERNALS__?: unknown })
      .__TAURI_INTERNALS__;
  if (isTauri) {
    if (ua.includes('mac')) return 'tauri-macos';
    if (ua.includes('windows')) return 'tauri-windows';
    return 'tauri-linux';
  }
  return 'web';
}
