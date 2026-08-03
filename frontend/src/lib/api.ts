import type { ModelInfo, SavingsData, ServerInfo } from '../types';
import { SUPABASE_ANON_KEY, SUPABASE_URL } from './supabase';

// ---------------------------------------------------------------------------
// Supabase config
// ---------------------------------------------------------------------------

declare global {
  interface Window {
    __TAURI_INTERNALS__?: unknown;
  }
}

export const isTauri = () => typeof window !== 'undefined' && !!window.__TAURI_INTERNALS__;

export type CloudKeyStatus = Record<string, boolean>;

export async function getCloudKeyStatus(): Promise<CloudKeyStatus> {
  if (!isTauri()) return {};
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    const rows = await invoke<Array<{ key: string; set: boolean }>>('get_cloud_key_status');
    return Object.fromEntries(rows.map((row) => [row.key, row.set]));
  } catch (e: any) {
    throw new Error(e?.message ?? e ?? 'Failed to read cloud key status');
  }
}

export async function saveCloudKey(keyName: string, keyValue: string): Promise<void> {
  if (!isTauri()) {
    throw new Error('Cloud API keys can be saved in the desktop app only.');
  }
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    await invoke('save_cloud_key', { keyName, keyValue });
  } catch (e: any) {
    throw new Error(e?.message ?? e ?? 'Failed to save cloud key');
  }
}

// Cached API base URL fetched from the Tauri backend at startup.
// This avoids hardcoding the port — the Rust backend is the single
// source of truth for JARVIS_PORT.
let _tauriApiBase: string | null = null;
let _tauriFinalAttachOnly = false;

export const isFinalAttachOnly = (): boolean => isTauri() && _tauriFinalAttachOnly;

/** Pre-fetch the API base URL from the Tauri backend (call once at init). */
export async function initApiBase(): Promise<void> {
  if (!isTauri()) return;
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    _tauriApiBase = await invoke<string>('get_api_base');
    try {
      const status = await invoke<{ source?: string }>('get_setup_status');
      _tauriFinalAttachOnly = status?.source === 'codex';
    } catch {
      _tauriFinalAttachOnly = false;
    }
  } catch {
    // Command may not exist on older builds; fall through to default.
  }
}

const DESKTOP_API_FALLBACK = 'http://127.0.0.1:8000';

const getSettingsApiUrl = (): string => {
  try {
    const raw = localStorage.getItem('openjarvis-settings');
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed.apiUrl) return parsed.apiUrl.replace(/\/+$/, '');
    }
  } catch {}
  return '';
};

export const getBase = (): string => {
  if (isFinalAttachOnly()) {
    return _tauriApiBase || DESKTOP_API_FALLBACK;
  }
  const settingsUrl = getSettingsApiUrl();
  if (settingsUrl) return settingsUrl;
  if (import.meta.env.VITE_API_URL) return import.meta.env.VITE_API_URL;
  if (isTauri()) return _tauriApiBase || DESKTOP_API_FALLBACK;
  return '';
};

// Resolve the local server API key (OPENJARVIS_API_KEY). When `jarvis serve`
// is started with a key, AuthMiddleware 401s every /v1 and /api request that
// lacks a Bearer token — so the frontend must send it (#266). Sourced from the
// same settings blob as the API URL, with an optional build-time env override.
// Returns '' when unset, so a keyless local server keeps working unchanged.
export const getApiKey = (): string => {
  try {
    const raw = localStorage.getItem('openjarvis-settings');
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed.apiKey) return String(parsed.apiKey);
    }
  } catch {}
  if (import.meta.env.VITE_OPENJARVIS_API_KEY) {
    return import.meta.env.VITE_OPENJARVIS_API_KEY as string;
  }
  return '';
};

// Build request headers with the Bearer Authorization token when a local key
// is configured, merging any caller-supplied headers. Adds no Authorization
// header when no key is set, so keyless local dev is byte-for-byte unchanged.
export const authHeaders = (
  extra: Record<string, string> = {},
): Record<string, string> => {
  const key = getApiKey();
  return key ? { ...extra, Authorization: `Bearer ${key}` } : { ...extra };
};

// Centralized fetch for the local server: prepends getBase() and injects the
// Bearer auth header (when a key is set) on every call. Using this everywhere
// guarantees no /v1 or /api request is sent without auth — the bug in #266 was
// that direct fetch() calls omitted the header and 401'd. `path` is the
// server-relative path (e.g. "/v1/savings").
export const apiFetch = (
  path: string,
  init: RequestInit = {},
): Promise<Response> => {
  const headers = authHeaders(
    (init.headers as Record<string, string> | undefined) ?? {},
  );
  return fetch(`${getBase()}${path}`, { ...init, headers });
};

export type FlowMode = 'locked' | 'assistant' | 'flow';

export interface FlowStatus {
  mode: FlowMode;
  owner_authenticated: boolean;
  session_id: string | null;
  activated_at: string | null;
  expires_at: string | null;
  last_activity_at: string | null;
  remaining_seconds: number;
  capabilities: Record<string, string>;
  lock_reason: string;
}

export async function fetchFlowStatus(): Promise<FlowStatus> {
  return apiJson<FlowStatus>('/v1/flow/status');
}

export async function activateFlowMode(): Promise<FlowStatus> {
  if (!isTauri()) {
    throw new Error('Flow Mode kann nur in der nativen Desktop-App aktiviert werden.');
  }
  const { invoke } = await import('@tauri-apps/api/core');
  return invoke<FlowStatus>('activate_flow_mode');
}

export async function activateAssistantMode(): Promise<FlowStatus> {
  return apiJson<FlowStatus>('/v1/flow/assistant', { method: 'POST' });
}

export async function lockFlowMode(reason = 'user_locked'): Promise<FlowStatus> {
  return apiJson<FlowStatus>(`/v1/flow/lock?reason=${encodeURIComponent(reason)}`, {
    method: 'POST',
  });
}

export async function recordFlowActivity(sessionId?: string | null): Promise<FlowStatus> {
  return apiJson<FlowStatus>('/v1/flow/activity', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId ?? null }),
  });
}

export type ApiErrorCategory =
  | 'aborted'
  | 'timeout'
  | 'unauthorized'
  | 'conflict'
  | 'unavailable'
  | 'server'
  | 'network'
  | 'invalid_response';

export class JarvisApiError extends Error {
  constructor(
    message: string,
    public readonly category: ApiErrorCategory,
    public readonly status: number | null = null,
    public readonly retryable = false,
  ) {
    super(message);
    this.name = 'JarvisApiError';
  }
}

export interface MutationContext {
  correlationId: string;
  idempotencyKey: string;
}

export function createMutationContext(prefix: string): MutationContext {
  const safePrefix = prefix.replace(/[^A-Za-z0-9._:-]/g, '-').slice(0, 40) || 'ui';
  return {
    correlationId: `${safePrefix}-${crypto.randomUUID()}`,
    idempotencyKey: `${safePrefix}-${crypto.randomUUID()}`,
  };
}

async function apiJson<T>(
  path: string,
  init: RequestInit = {},
  { timeoutMs = 15_000, signal }: { timeoutMs?: number; signal?: AbortSignal } = {},
): Promise<T> {
  const controller = new AbortController();
  const onAbort = () => controller.abort(signal?.reason);
  signal?.addEventListener('abort', onAbort, { once: true });
  const timeout = window.setTimeout(() => controller.abort('timeout'), timeoutMs);
  try {
    const response = await apiFetch(path, { ...init, signal: controller.signal });
    if (!response.ok) {
      let detail = '';
      try {
        const payload = await response.json();
        detail = typeof payload?.detail === 'string' ? payload.detail : '';
      } catch {
        // A normalized status message is safer than reflecting arbitrary HTML.
      }
      const category: ApiErrorCategory = response.status === 401
        ? 'unauthorized'
        : response.status === 409
          ? 'conflict'
          : response.status === 502 || response.status === 503
            ? 'unavailable'
            : 'server';
      throw new JarvisApiError(
        detail || `OpenJarvis request failed (${response.status})`,
        category,
        response.status,
        response.status >= 500,
      );
    }
    try {
      return await response.json() as T;
    } catch {
      throw new JarvisApiError('OpenJarvis returned an invalid response.', 'invalid_response');
    }
  } catch (error) {
    if (error instanceof JarvisApiError) throw error;
    if (controller.signal.aborted) {
      const timedOut = !signal?.aborted;
      throw new JarvisApiError(
        timedOut ? 'OpenJarvis request timed out.' : 'Request canceled.',
        timedOut ? 'timeout' : 'aborted',
        null,
        timedOut,
      );
    }
    throw new JarvisApiError('OpenJarvis server is not reachable.', 'network', null, true);
  } finally {
    window.clearTimeout(timeout);
    signal?.removeEventListener('abort', onAbort);
  }
}

async function tauriInvoke<T>(command: string, args: Record<string, unknown> = {}): Promise<T> {
  const { invoke } = await import('@tauri-apps/api/core');
  const apiUrl = getBase();
  return invoke<T>(command, { apiUrl, ...args });
}

// ---------------------------------------------------------------------------
// Setup status (desktop only)
// ---------------------------------------------------------------------------

export interface SetupStatus {
  phase: string;
  detail: string;
  ollama_ready: boolean;
  server_ready: boolean;
  model_ready: boolean;
  error: string | null;
  source?: 'ollama' | 'custom' | 'codex'; // drives source-aware setup labels
}

export async function getSetupStatus(): Promise<SetupStatus | null> {
  if (!isTauri()) return null;
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    return await invoke<SetupStatus>('get_setup_status');
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export async function fetchModels(): Promise<ModelInfo[]> {
  if (isTauri()) {
    try {
      const result = await tauriInvoke<{ data?: ModelInfo[] }>('fetch_models');
      return result?.data || [];
    } catch {
      // Fall through to fetch
    }
  }
  const res = await apiFetch(`/v1/models`);
  if (!res.ok) throw new Error(`Failed to fetch models: ${res.status}`);
  const data = await res.json();
  return data.data || [];
}

export async function fetchRecommendedModel(): Promise<{ model: string; reason: string }> {
  const res = await apiFetch(`/v1/recommended-model`);
  if (!res.ok) return { model: '', reason: 'Failed to fetch' };
  return res.json();
}

export async function pullModel(modelName: string): Promise<void> {
  // In Tauri, go through the Rust backend directly (avoids CORS / timeout
  // issues with long model downloads via fetch).
  if (isTauri()) {
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      await invoke('pull_ollama_model', { modelName });
      return;
    } catch (e: any) {
      throw new Error(e?.message || e || 'Download failed');
    }
  }
  const res = await apiFetch(`/v1/models/pull`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: modelName }),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`Failed to pull model: ${detail}`);
  }
}

export async function deleteModel(modelName: string): Promise<void> {
  if (isTauri()) {
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      await invoke('delete_ollama_model', { modelName });
      return;
    } catch (e: any) {
      throw new Error(e?.message || e || 'Delete failed');
    }
  }
  const res = await apiFetch(`/v1/models/${encodeURIComponent(modelName)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`Failed to delete model: ${detail}`);
  }
}

const _CLOUD_PREFIXES = ['gpt-', 'o1-', 'o3-', 'o4-', 'claude-', 'gemini-', 'openrouter/'];

export async function preloadModel(modelName: string): Promise<void> {
  // Cloud models don't need Ollama preloading
  if (_CLOUD_PREFIXES.some(p => modelName.startsWith(p))) {
    return;
  }
  // Trigger Ollama to load the model into memory (empty prompt, no generation).
  const ollamaUrl = 'http://127.0.0.1:11434';
  try {
    const res = await fetch(`${ollamaUrl}/api/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: modelName, prompt: '', keep_alive: '5m' }),
      signal: AbortSignal.timeout(120_000),
    });
    if (!res.ok) throw new Error(`Preload failed: ${res.status}`);
  } catch (e: any) {
    if (e.name === 'TimeoutError') throw new Error('Model load timed out (120s)');
    throw e;
  }
}

export async function fetchSavings(): Promise<SavingsData> {
  const res = await apiFetch(`/v1/savings`);
  if (!res.ok) throw new Error(`Failed to fetch savings: ${res.status}`);
  return res.json();
}

export async function fetchServerInfo(): Promise<ServerInfo> {
  const res = await apiFetch(`/v1/info`);
  if (!res.ok) throw new Error(`Failed to fetch server info: ${res.status}`);
  return res.json();
}

export async function checkHealth(): Promise<boolean> {
  if (isTauri()) {
    try {
      await tauriInvoke('check_health', { apiUrl: getBase() });
      return true;
    } catch {
      return false;
    }
  }
  // In the browser, hit /health relative to the page origin so the request
  // flows through whatever path is already serving the SPA — the Vite
  // proxy in dev, FastAPI's static mount in prod. This avoids the
  // false-negative "Cannot reach backend" banner when getBase() points at
  // an absolute URL the browser can't reach directly.
  //
  // If /health itself fails for any reason (proxy quirk, stale service
  // worker, etc.) fall back to an arbitrary API endpoint we know the rest
  // of the app polls successfully. If THAT also fails we genuinely can't
  // reach the backend.
  const probe = async (url: string): Promise<boolean> => {
    try {
      const res = await fetch(url, { cache: 'no-store' });
      return res.ok;
    } catch {
      return false;
    }
  };
  if (await probe('/health')) return true;
  return probe('/v1/connectors');
}

export async function fetchEnergy(): Promise<unknown> {
  if (isTauri()) {
    try {
      return await tauriInvoke('fetch_energy', { apiUrl: getBase() });
    } catch {}
  }
  const res = await apiFetch(`/v1/telemetry/energy`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function fetchTelemetry(): Promise<unknown> {
  if (isTauri()) {
    try {
      return await tauriInvoke('fetch_telemetry', { apiUrl: getBase() });
    } catch {}
  }
  const res = await apiFetch(`/v1/telemetry/stats`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function fetchTraces(limit: number = 50): Promise<unknown> {
  if (isTauri()) {
    try {
      return await tauriInvoke('fetch_traces', { apiUrl: getBase(), limit });
    } catch {}
  }
  const res = await apiFetch(`/v1/traces?limit=${limit}`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Speech
// ---------------------------------------------------------------------------

export interface TranscriptionResult {
  text: string;
  language: string | null;
  confidence: number | null;
  duration_seconds: number;
}

export interface SpeechHealth {
  available: boolean;
  backend?: string;
  reason?: string;
  stt_available?: boolean;
  tts_available?: boolean;
  stt_provider?: string;
  tts_provider?: string;
  stt_location?: 'local' | 'external' | 'disabled';
  tts_location?: 'local' | 'external' | 'disabled';
  language?: string;
  microphone_permission?: 'client';
  degraded?: boolean;
  last_error?: string | null;
}

export interface VoiceProfileInfo {
  voice_id: string;
  number: number;
  label: string;
  backend: 'elevenlabs' | 'chatterbox' | 'piper';
  pitch_semitones: number;
  speed: number;
  exaggeration: number;
  cfg_weight: number;
  temperature: number;
  seed: number;
  description: string;
  audition_ready: boolean;
  audition_backend: string;
  audition_fallback_used: boolean;
}

export interface ElevenLabsUsage {
  month: string;
  characters_used: number;
}

export interface LocalVoiceStatus {
  selected_voice_id: string;
  primary_backend: string;
  local_fallback_backend: string;
  emergency_backend: string;
  elevenlabs_voice_id?: string | null;
  monthly_char_limit: number;
  per_response_char_limit: number;
  language: string;
  audition_text: string;
  profiles: VoiceProfileInfo[];
  worker: {
    elevenlabs_configured: boolean;
    elevenlabs_voice_id_set: boolean;
    elevenlabs_api_key_set: boolean;
    elevenlabs_usage: ElevenLabsUsage | null;
    chatterbox: boolean;
    piper: boolean;
    cuda: boolean;
    device: string;
    chatterbox_loaded?: boolean;
    reference_profiles_loaded?: number;
    piper_loaded?: boolean;
  };
}

export interface ElevenLabsVoiceInfo {
  voice_id: string;
  name: string;
  category: string;
  description: string;
  labels: Record<string, string>;
  verified_languages: Array<{ language: string; locale: string; accent: string }>;
}

export interface SynthesizedSpeech {
  audio: Blob;
  backend: string;
  fallbackUsed: boolean;
  cacheHit: boolean;
  synthesisMs: number;
}

export async function synthesizeSpeech(
  text: string,
  language = 'de-DE',
  signal?: AbortSignal,
  responseId = '',
): Promise<SynthesizedSpeech> {
  const res = await apiFetch('/v1/speech/synthesize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, language, speed: 1.0, response_id: responseId }),
    signal,
  });
  if (!res.ok) {
    let detail = '';
    try { detail = String((await res.json()).detail || ''); } catch { /* no response body */ }
    throw new Error(detail || `Sprachausgabe fehlgeschlagen (${res.status}).`);
  }
  return {
    audio: await res.blob(),
    backend: res.headers.get('x-openjarvis-tts-backend') || 'unknown',
    fallbackUsed: res.headers.get('x-openjarvis-fallback') === 'true',
    cacheHit: res.headers.get('x-openjarvis-cache') === 'hit',
    synthesisMs: Number(res.headers.get('x-openjarvis-synthesis-ms') || 0),
  };
}

export async function fetchLocalVoices(): Promise<LocalVoiceStatus> {
  const res = await apiFetch('/v1/speech/voices');
  if (!res.ok) throw new Error(`Local voice status failed (${res.status}).`);
  return res.json();
}

export async function selectLocalVoice(voiceId: string): Promise<void> {
  const res = await apiFetch('/v1/speech/voices/selected', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ voice_id: voiceId }),
  });
  if (!res.ok) throw new Error(`Voice selection failed (${res.status}).`);
}

export async function fetchElevenLabsVoices(): Promise<ElevenLabsVoiceInfo[]> {
  const res = await apiFetch('/v1/speech/elevenlabs/voices');
  if (!res.ok) {
    let detail = '';
    try { detail = String((await res.json()).detail || ''); } catch { /* no response body */ }
    throw new Error(detail || `ElevenLabs-Stimmen konnten nicht geladen werden (${res.status}).`);
  }
  const payload = await res.json();
  return Array.isArray(payload.voices) ? payload.voices : [];
}

export async function selectElevenLabsVoice(voiceId: string): Promise<void> {
  const res = await apiFetch('/v1/speech/elevenlabs/voice', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ voice_id: voiceId }),
  });
  if (!res.ok) {
    let detail = '';
    try { detail = String((await res.json()).detail || ''); } catch { /* no response body */ }
    throw new Error(detail || `ElevenLabs-Stimme konnte nicht gespeichert werden (${res.status}).`);
  }
}

export async function updateVoiceLimits(monthly: number, perResponse: number): Promise<void> {
  const res = await apiFetch('/v1/speech/limits', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ monthly_char_limit: monthly, per_response_char_limit: perResponse }),
  });
  if (!res.ok) throw new Error(`Kostenlimits konnten nicht gespeichert werden (${res.status}).`);
}

export async function generateVoiceAuditions(): Promise<void> {
  const res = await apiFetch('/v1/speech/auditions/generate', { method: 'POST' });
  if (!res.ok) throw new Error(`Voice audition generation failed (${res.status}).`);
}

export async function fetchVoiceAudition(voiceId: string): Promise<Blob> {
  const res = await apiFetch(`/v1/speech/auditions/${encodeURIComponent(voiceId)}`);
  if (!res.ok) throw new Error(`Voice audition is not ready (${res.status}).`);
  return res.blob();
}

export async function transcribeAudio(audioBlob: Blob, filename = 'recording.webm'): Promise<TranscriptionResult> {
  if (isTauri()) {
    try {
      const buffer = await audioBlob.arrayBuffer();
      return await tauriInvoke<TranscriptionResult>('transcribe_audio', {
        audioData: Array.from(new Uint8Array(buffer)),
        filename,
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      throw new Error(msg || 'Transcription failed');
    }
  }
  const formData = new FormData();
  formData.append('file', audioBlob, filename);
  const res = await apiFetch(`/v1/speech/transcribe`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    let detail = "";
    try {
      const body = await res.json();
      detail = typeof body.detail === 'string' ? body.detail : "";
    } catch {
      // Keep the status-only message below when the body is not JSON.
    }
    throw new Error(detail || `Transcription failed: ${res.status}`);
  }
  return res.json();
}

export async function fetchSpeechHealth(): Promise<SpeechHealth> {
  if (isTauri()) {
    try {
      return await tauriInvoke<SpeechHealth>('speech_health');
    } catch {
      return { available: false };
    }
  }
  const res = await apiFetch(`/v1/speech/health`);
  if (!res.ok) return { available: false };
  return res.json();
}

// ---------------------------------------------------------------------------
// Agent Manager
// ---------------------------------------------------------------------------

export interface ManagedAgent {
  id: string;
  name: string;
  agent_type: string;
  config: Record<string, unknown>;
  status: 'idle' | 'running' | 'paused' | 'error' | 'archived' | 'needs_attention' | 'budget_exceeded' | 'stalled';
  summary_memory: string;
  created_at: number;
  updated_at: number;
  // Runtime stats
  total_runs?: number;
  total_cost?: number;
  total_tokens?: number;
  input_tokens?: number;
  output_tokens?: number;
  last_run_at?: number | null;
  // Schedule
  schedule_type?: string;
  schedule_value?: string;
  // Budget
  budget?: number;
  // Learning
  learning_enabled?: boolean;
  // Live progress
  current_activity?: string;
}

export interface AgentTask {
  id: string;
  agent_id: string;
  description: string;
  status: 'pending' | 'active' | 'completed' | 'failed';
  progress: Record<string, unknown>;
  findings: unknown[];
  created_at: number;
}

export interface ChannelBinding {
  id: string;
  agent_id: string;
  channel_type: string;
  config: Record<string, unknown>;
  session_id: string;
  routing_mode: string;
}

export interface AgentTemplate {
  id: string;
  name: string;
  description: string;
  source: 'built-in' | 'user';
  agent_type: string;
  [key: string]: unknown;
}

export interface PersistedToolCall {
  tool: string;
  arguments: string;
  result?: string;
  success?: boolean;
  latency?: number;
}

export interface AgentMessage {
  id: string;
  agent_id: string;
  direction: 'user_to_agent' | 'agent_to_user';
  content: string;
  mode: 'immediate' | 'queued';
  status: 'pending' | 'delivered' | 'responded';
  created_at: number;
  tool_calls?: PersistedToolCall[] | null;
}

export async function fetchManagedAgents(): Promise<ManagedAgent[]> {
  const res = await apiFetch(`/v1/managed-agents`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.agents || [];
}

export async function fetchManagedAgent(agentId: string): Promise<ManagedAgent> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function createManagedAgent(body: {
  name: string;
  agent_type?: string;
  template_id?: string;
  config?: Record<string, unknown>;
}): Promise<ManagedAgent> {
  const res = await apiFetch(`/v1/managed-agents`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function updateManagedAgent(
  agentId: string,
  body: Partial<{ name: string; agent_type: string; config: Record<string, unknown> }>,
): Promise<ManagedAgent> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function deleteManagedAgent(agentId: string): Promise<void> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export async function pauseManagedAgent(agentId: string): Promise<void> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/pause`, { method: 'POST' });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export async function resumeManagedAgent(agentId: string): Promise<void> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/resume`, { method: 'POST' });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export async function fetchAgentTasks(agentId: string): Promise<AgentTask[]> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/tasks`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.tasks || [];
}

export async function createAgentTask(agentId: string, description: string): Promise<AgentTask> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/tasks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ description }),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function fetchAgentChannels(agentId: string): Promise<ChannelBinding[]> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/channels`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.bindings || [];
}

export async function bindAgentChannel(
  agentId: string,
  channelType: string,
  config?: Record<string, unknown>,
): Promise<ChannelBinding> {
  const res = await fetch(
    `${getBase()}/v1/managed-agents/${agentId}/channels`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        channel_type: channelType,
        config: config || {},
        routing_mode: 'dedicated',
      }),
    },
  );
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function unbindAgentChannel(
  agentId: string,
  bindingId: string,
): Promise<void> {
  const res = await fetch(
    `${getBase()}/v1/managed-agents/${agentId}/channels/${bindingId}`,
    { method: 'DELETE' },
  );
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

// -- SendBlue auto-setup helpers ------------------------------------------

export async function sendblueVerify(
  apiKeyId: string,
  apiSecretKey: string,
): Promise<{ valid: boolean; numbers: string[]; raw: unknown }> {
  const res = await apiFetch(`/v1/channels/sendblue/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key_id: apiKeyId, api_secret_key: apiSecretKey }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Verification failed: ${res.status}`);
  }
  return res.json();
}

export async function sendblueRegisterWebhook(
  apiKeyId: string,
  apiSecretKey: string,
  webhookUrl: string,
): Promise<{ registered: boolean; status: number }> {
  const res = await apiFetch(`/v1/channels/sendblue/register-webhook`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      api_key_id: apiKeyId,
      api_secret_key: apiSecretKey,
      webhook_url: webhookUrl,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Webhook registration failed: ${res.status}`);
  }
  return res.json();
}

export async function sendblueTest(
  apiKeyId: string,
  apiSecretKey: string,
  fromNumber: string,
  toNumber: string,
): Promise<{ sent: boolean; status: number }> {
  const res = await apiFetch(`/v1/channels/sendblue/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      api_key_id: apiKeyId,
      api_secret_key: apiSecretKey,
      from_number: fromNumber,
      to_number: toNumber,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Test message failed: ${res.status}`);
  }
  return res.json();
}

export async function sendblueHealth(): Promise<{ channel_connected: boolean; bridge_wired: boolean; ready: boolean }> {
  const res = await apiFetch(`/v1/channels/sendblue/health`);
  if (!res.ok) return { channel_connected: false, bridge_wired: false, ready: false };
  return res.json();
}

export async function fetchTemplates(): Promise<AgentTemplate[]> {
  const res = await apiFetch(`/v1/templates`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.templates || [];
}

export async function runManagedAgent(agentId: string): Promise<void> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/run`, { method: 'POST' });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Failed: ${res.status}`);
  }
}

export async function recoverManagedAgent(agentId: string): Promise<{ recovered: boolean; checkpoint: unknown }> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/recover`, { method: 'POST' });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Failed: ${res.status}`);
  }
  return res.json();
}

export async function fetchAgentState(agentId: string): Promise<{
  agent: ManagedAgent;
  tasks: AgentTask[];
  channels: ChannelBinding[];
  messages: AgentMessage[];
  checkpoint: unknown;
}> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/state`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export interface AgentToolCallStart {
  tool: string;
  arguments: string;
}

export interface AgentToolCallEnd {
  tool: string;
  success: boolean;
  latency: number;
  result?: string;
}

export async function sendAgentMessage(
  agentId: string,
  content: string,
  mode: 'immediate' | 'queued' = 'queued',
  callbacks?: {
    onProgress?: (label: string) => void;
    onContentDelta?: (delta: string, fullContent: string) => void;
    onToolCallStart?: (info: AgentToolCallStart) => void;
    onToolCallEnd?: (info: AgentToolCallEnd) => void;
    onDone?: (fullContent: string, usage?: Record<string, number>, telemetry?: Record<string, unknown>) => void;
  },
): Promise<AgentMessage> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, mode, stream: true }),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);

  // If streaming, consume the SSE response so the agent runs
  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('text/event-stream') && res.body) {
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let fullContent = '';
    let buffer = '';
    let lastUsage: Record<string, number> | undefined;
    let lastTelemetry: Record<string, unknown> | undefined;
    let currentEvent: string | undefined;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim();
            continue;
          }
          if (!line.startsWith('data: ')) {
            if (line.trim() === '') currentEvent = undefined;
            continue;
          }
          const data = line.slice(6);
          if (data === '[DONE]') {
            currentEvent = undefined;
            continue;
          }
          const evName = currentEvent;
          currentEvent = undefined;

          if (evName === 'tool_call_start') {
            try {
              const parsed = JSON.parse(data);
              callbacks?.onToolCallStart?.({
                tool: parsed.tool,
                arguments: parsed.arguments ?? '',
              });
            } catch {
              /* skip */
            }
            continue;
          }
          if (evName === 'tool_call_end') {
            try {
              const parsed = JSON.parse(data);
              callbacks?.onToolCallEnd?.({
                tool: parsed.tool,
                success: !!parsed.success,
                latency: typeof parsed.latency === 'number' ? parsed.latency : 0,
                result: parsed.result,
              });
            } catch {
              /* skip */
            }
            continue;
          }

          try {
            const chunk = JSON.parse(data);
            // Deep-research branch still uses tool_progress in a data chunk
            const toolProgress = chunk.choices?.[0]?.tool_progress;
            if (toolProgress) {
              callbacks?.onProgress?.(toolProgress);
            }
            const delta = chunk.choices?.[0]?.delta?.content || '';
            if (delta) {
              fullContent += delta;
              callbacks?.onContentDelta?.(delta, fullContent);
            }
            if (chunk.usage) lastUsage = chunk.usage;
            if (chunk.telemetry) lastTelemetry = chunk.telemetry;
          } catch {
            /* skip malformed chunks */
          }
        }
      }
    } catch { /* stream ended */ }

    callbacks?.onDone?.(fullContent, lastUsage, lastTelemetry);

    return {
      id: '',
      agent_id: agentId,
      direction: 'agent_to_user',
      content: fullContent,
      mode,
      status: 'delivered',
      created_at: Date.now() / 1000,
    };
  }

  return res.json();
}

/**
 * Ask the agent a question by triggering an ad-hoc run.
 *
 * Posts the question as an `immediate`, non-streamed message — the backend
 * stores it and spawns a real agent tick (`execute_tick`) that consumes it as
 * the run's input (tools, trace, and all), rather than a raw one-shot chat.
 * Returns immediately with the stored user message; progress is observed via
 * the `/v1/agents/events` WebSocket and the resulting trace.
 */
export async function askAgent(agentId: string, content: string): Promise<AgentMessage> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, mode: 'immediate', stream: false }),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function fetchAgentMessages(agentId: string): Promise<AgentMessage[]> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/messages`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.messages || [];
}

export async function fetchErrorAgents(): Promise<ManagedAgent[]> {
  const res = await apiFetch(`/v1/agents/errors`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.agents || [];
}

// ---------------------------------------------------------------------------
// Agent Learning + Traces
// ---------------------------------------------------------------------------

export interface LearningLogEntry {
  id: string;
  agent_id: string;
  event_type: string;
  description: string;
  data: Record<string, unknown>;
  created_at: number;
}

export interface AgentTrace {
  id: string;
  outcome: string;
  duration: number;
  started_at: number;
  steps: number;
  error_message?: string;
  metadata?: Record<string, unknown>;
}

export interface ToolInfo {
  name: string;
  description: string;
  category: string;
  source: 'tool' | 'channel';
  requires_credentials: boolean;
  credential_keys: string[];
  configured: boolean;
}

export async function fetchAvailableTools(): Promise<ToolInfo[]> {
  const res = await apiFetch(`/v1/tools`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.tools || [];
}

export async function saveToolCredentials(
  toolName: string,
  credentials: Record<string, string>,
): Promise<void> {
  const res = await apiFetch(`/v1/tools/${toolName}/credentials`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(credentials),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export interface AgentTraceDetail {
  id: string;
  agent: string;
  outcome: string;
  duration: number;
  started_at: number;
  steps: Array<{
    step_type: string;
    input: unknown;
    output: string;
    duration: number;
    metadata: Record<string, unknown>;
  }>;
}

export async function fetchLearningLog(agentId: string): Promise<LearningLogEntry[]> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/learning`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.learning_log || [];
}

export async function triggerLearning(agentId: string): Promise<void> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/learning/run`, { method: 'POST' });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export async function fetchAgentTraces(agentId: string, limit = 20): Promise<AgentTrace[]> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/traces?limit=${limit}`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.traces || [];
}

export async function fetchAgentTrace(agentId: string, traceId: string): Promise<AgentTraceDetail> {
  const res = await apiFetch(`/v1/managed-agents/${agentId}/traces/${traceId}`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Leaderboard savings submission (Supabase)
// ---------------------------------------------------------------------------

export interface SavingsSubmission {
  anon_id: string;
  display_name: string;
  email: string;
  total_calls: number;
  total_tokens: number;
  dollar_savings: number;
  energy_wh_saved: number;
  flops_saved: number;
  token_counting_version?: number;
}

export async function submitSavings(data: SavingsSubmission): Promise<boolean> {
  if (!SUPABASE_URL || !SUPABASE_ANON_KEY) return false;
  try {
    const res = await fetch(
      `${SUPABASE_URL}/rest/v1/savings_entries?on_conflict=anon_id`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          apikey: SUPABASE_ANON_KEY,
          Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
          Prefer: 'resolution=merge-duplicates',
        },
        body: JSON.stringify(data),
      },
    );
    return res.ok || res.status === 201 || res.status === 200;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Memory
// ---------------------------------------------------------------------------

export interface MemorySearchResult {
  content: string;
  score: number;
  metadata: Record<string, unknown>;
}

export interface MemoryStats {
  entries: number;
  backend: string;
  [key: string]: unknown;
}

export interface MemoryConfig {
  backend: string;
  // Set by the server when the native `openjarvis_rust` extension is missing,
  // so the UI can show the real cause instead of a healthy-looking config.
  available?: boolean;
  detail?: string | null;
  context_from_memory: boolean;
  context_top_k: number;
  context_min_score: number;
  context_max_tokens: number;
}

/**
 * Extract the server's `detail` message from a failed JSON response so the UI
 * surfaces the real cause (e.g. "openjarvis_rust extension is not installed")
 * instead of a blanket fallback string (#502).
 */
async function memoryErrorDetail(res: Response, fallback: string): Promise<string> {
  try {
    const data = await res.json();
    if (data && typeof data.detail === 'string' && data.detail) return data.detail;
  } catch {
    // Non-JSON body — fall through to the generic message below.
  }
  return fallback;
}

export async function getMemoryStats(): Promise<MemoryStats> {
  const res = await apiFetch(`/v1/memory/stats`);
  if (!res.ok) throw new Error('Failed to fetch memory stats');
  return res.json();
}

export async function searchMemory(query: string, topK: number = 5): Promise<MemorySearchResult[]> {
  const res = await apiFetch(`/v1/memory/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, top_k: topK }),
  });
  if (!res.ok) throw new Error('Failed to search memory');
  const data = await res.json();
  return data.results;
}

export async function storeMemory(content: string, metadata?: Record<string, unknown>): Promise<void> {
  const res = await apiFetch(`/v1/memory/store`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, metadata }),
  });
  if (!res.ok) throw new Error(await memoryErrorDetail(res, 'Failed to store memory'));
}

export async function indexMemoryPath(path: string): Promise<{ chunks_indexed: number; note?: string }> {
  const res = await apiFetch(`/v1/memory/index`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  });
  if (!res.ok) throw new Error(await memoryErrorDetail(res, 'Failed to index path'));
  return res.json();
}

export async function getMemoryConfig(): Promise<MemoryConfig> {
  const res = await apiFetch(`/v1/memory/config`);
  if (!res.ok) throw new Error('Failed to fetch memory config');
  return res.json();
}

// ---------------------------------------------------------------------------
// Evidence-bound Markdown vault memory
// ---------------------------------------------------------------------------

export interface VaultMemoryHealth {
  vault_configured: boolean;
  vault_reachable: boolean;
  mode: 'read-only' | 'writable-test' | 'unconfigured';
  index_available: boolean;
  fts5_available: boolean;
  note_count: number;
  parser_error_count: number;
  last_successful_index: string | null;
  last_error: string | null;
  embeddings_enabled: boolean;
  retrieval_mode: string;
  open_candidates: number;
  open_conflicts: number;
  discovered_count: number;
  frontmatter_parsed_count: number;
  schema_valid_count: number;
  type_supported_count: number;
  fts_document_count: number;
  retrieval_eligible_count: number;
  review_only_count: number;
  structural_count: number;
  authority_sensitive_count: number;
  rejected_count: number;
}

export interface VaultMemorySource {
  source_id: string;
  retrieval_id: string;
  note_id: string;
  path: string;
  title: string;
  relevant_text: string;
  line_start: number | null;
  line_end: number | null;
  section: string | null;
  score: number;
  selection_reason: string;
  content_hash: string;
  indexed_at: string;
  note_type: string;
  trust_class: string;
  retrieval_class: string;
  authority_class: string;
  scope_class: string;
}

export interface VaultMemoryCandidateResult {
  note_id: string;
  path: string;
  title: string;
  score: number;
  reason: string;
  content_hash: string;
  conflict_state: string;
  source_priority: number;
  note_type: string;
  trust_class: string;
  retrieval_class: string;
  authority_class: string;
  scope_class: string;
}

export interface VaultMemoryRetrieval {
  retrieval_id: string;
  query: string;
  normalized_query: string;
  candidates: VaultMemoryCandidateResult[];
  selected_sources: VaultMemorySource[];
  confidence: number;
  evidence_status: 'sufficient' | 'partial' | 'insufficient' | 'conflicting' | 'unavailable';
  evidence_code: string;
  retrieval_method: string;
  retrieval_purpose: 'normal' | 'explicit_review' | 'vault_structure';
  filters: Record<string, unknown>;
  warnings: string[];
}

export interface VaultMemoryCandidate {
  candidate_id: string;
  task_id: string;
  note_id: string;
  proposed_path: string;
  note_type: string;
  scope: string;
  source: string;
  planned_diff: string;
  risk_level: number;
  status: string;
  approval_id: string | null;
  conflict_state: string;
  created_at: string;
}

export interface VaultMemoryConflict {
  conflict_id: string;
  conflict_type: string;
  state: string;
  note_ids: string[];
  candidate_id: string | null;
  summary: string;
  winner_note_id: string | null;
  resolution: string | null;
  created_at: string;
  resolved_at: string | null;
}

export interface VaultMemoryNote {
  note_id: string;
  path: string;
  title: string;
  note_type: string;
  status: string;
  body: string;
  content_hash: string;
  conflict_state: string;
  identity_kind: string;
  trust_class: string;
  retrieval_class: string;
  authority_class: string;
  scope_class: string;
  parse_status: 'valid' | 'rejected';
  retrieval_eligible: boolean;
}

export interface VaultMemoryLinks {
  outgoing: Array<Record<string, unknown>>;
  backlinks: Array<Record<string, unknown>>;
}

export interface MemoryTaskContext {
  task_id: string;
  session_id: string;
  correlation_id: string;
}

function memoryTaskHeaders(context: MemoryTaskContext): Record<string, string> {
  return {
    'X-Task-ID': context.task_id,
    'X-Session-ID': context.session_id,
    'X-Correlation-ID': context.correlation_id,
  };
}

export async function fetchVaultMemoryHealth(): Promise<VaultMemoryHealth> {
  const res = await apiFetch('/v1/memory/health');
  if (!res.ok) throw new Error(await memoryErrorDetail(res, 'Failed to fetch vault memory health'));
  return res.json();
}

export async function searchVaultMemory(
  query: string,
  context: MemoryTaskContext,
  topK = 5,
): Promise<VaultMemoryRetrieval> {
  const params = new URLSearchParams({ query, top_k: String(topK) });
  const res = await apiFetch(`/v1/memory/search?${params}`, {
    headers: memoryTaskHeaders(context),
  });
  if (!res.ok) throw new Error(await memoryErrorDetail(res, 'Failed to search vault memory'));
  return res.json();
}

export async function reviewVaultMemory(
  query: string,
  topK = 5,
): Promise<VaultMemoryRetrieval> {
  const params = new URLSearchParams({ query, top_k: String(topK) });
  const res = await apiFetch(`/v1/memory/review/search?${params}`);
  if (!res.ok) throw new Error(await memoryErrorDetail(res, 'Failed to review vault sources'));
  return res.json();
}

export async function searchVaultStructure(
  query: string,
  topK = 5,
): Promise<VaultMemoryRetrieval> {
  const params = new URLSearchParams({ query, top_k: String(topK) });
  const res = await apiFetch(`/v1/memory/structure/search?${params}`);
  if (!res.ok) throw new Error(await memoryErrorDetail(res, 'Failed to inspect vault structure'));
  return res.json();
}

export async function fetchVaultMemoryCandidates(): Promise<VaultMemoryCandidate[]> {
  const res = await apiFetch('/v1/memory/candidates?open_only=false');
  if (!res.ok) throw new Error(await memoryErrorDetail(res, 'Failed to fetch memory candidates'));
  const data = await res.json();
  return data.candidates || [];
}

export async function fetchVaultMemoryConflicts(): Promise<VaultMemoryConflict[]> {
  const res = await apiFetch('/v1/memory/conflicts?open_only=true');
  if (!res.ok) throw new Error(await memoryErrorDetail(res, 'Failed to fetch memory conflicts'));
  const data = await res.json();
  return data.conflicts || [];
}

export async function fetchVaultMemoryNote(noteId: string): Promise<VaultMemoryNote> {
  const res = await apiFetch(`/v1/memory/notes/${encodeURIComponent(noteId)}`);
  if (!res.ok) throw new Error(await memoryErrorDetail(res, 'Failed to fetch memory note'));
  return res.json();
}

export async function fetchVaultMemoryLinks(noteId: string): Promise<VaultMemoryLinks> {
  const res = await apiFetch(`/v1/memory/notes/${encodeURIComponent(noteId)}/links`);
  if (!res.ok) throw new Error(await memoryErrorDetail(res, 'Failed to fetch note links'));
  return res.json();
}

// ---------------------------------------------------------------------------
// Canonical Codex tasks
// ---------------------------------------------------------------------------

export interface CanonicalTask {
  task_id: string;
  session_id: string;
  correlation_id: string;
  description: string;
  status: 'pending' | 'running' | 'waiting_approval' | 'paused' | 'recovering' | 'failed' | 'done' | 'canceled';
  outcome: string | null;
  execution_lane: 'model_lane' | 'interactive_lane';
  backend: string;
  risk_level: number;
  created_at: string;
  updated_at: string;
  result: string;
  error_category: string | null;
  active_thread_id: string | null;
  budget_warning: boolean;
}

export interface CanonicalTaskEvent {
  event_id: string;
  task_id: string;
  sequence: number;
  event_type: string;
  occurred_at: string;
  cause: string;
  component: string;
  status_from: string | null;
  status_to: string | null;
  thread_id: string | null;
  item_id: string | null;
  approval_id: string | null;
  artifact_id: string | null;
  payload: Record<string, unknown>;
}

export interface CanonicalTaskSource {
  source_id: string;
  task_id: string;
  source_kind: string;
  external_id: string;
  created_at: string;
  metadata: {
    title?: string;
    path?: string;
    line_start?: number;
    line_end?: number;
    section?: string;
    relevant_preview?: string;
    selection_reason?: string;
    score?: number;
    [key: string]: unknown;
  };
}

export interface TurnModelEvidence {
  requested: {
    model: string | null;
    effort: string | null;
  };
  resolved: {
    model: string;
    effort: string;
  };
  confirmed: {
    model: boolean;
    effort: boolean;
  };
  evidence_source: {
    model: string;
    effort: string;
  };
  backend: string;
  sdk_version: string;
  runtime_version: string;
  thread_id: string | null;
  turn_id: string | null;
}

export interface TaskSummary {
  task: CanonicalTask;
  turn_model_evidence: TurnModelEvidence;
  current_step: string | null;
  last_sequence: number;
  source_count: number;
  open_approvals: number;
  tool_action_count: number;
  effect_known: boolean;
  safe_to_present_as_success: boolean;
  can_resume: boolean;
}

export interface CanonicalChatResponse {
  task: CanonicalTask;
  content: string;
  idempotent_replay: boolean;
  pending: boolean;
}

export interface SessionSummary {
  session_id: string;
  active_task_id: string | null;
  task_count: number;
  updated_at: string;
  last_status: CanonicalTask['status'];
  title: string;
}

export interface TaskArtifactInfo {
  artifact_id: string;
  task_id: string;
  kind: string;
  media_type: string;
  byte_size: number;
  sha256: string;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface CodexRuntimeHealth {
  active_backend: string | null;
  active_task: CanonicalTask | null;
  chatgpt_authenticated: boolean;
  runtime_version: string | null;
  sandbox: string;
  approval_mode: string;
  persistent_threads: boolean;
  app_server_available: boolean;
  cli_fallback_enabled: boolean;
  degraded: boolean;
  open_approvals: number;
  last_error_category: string | null;
  turn_model_evidence: TurnModelEvidence;
}

export interface CanonicalTaskUsage {
  turns: Array<{
    turn_id: string | null;
    input_tokens: number;
    output_tokens: number;
    warning: boolean;
    hard_exceeded: boolean;
    reason: string | null;
  }>;
  cumulative_thread: {
    input_tokens: number;
    output_tokens: number;
  };
  task_total_tokens: number;
}

export interface ToolManifestInfo {
  tool_id: string;
  name: string;
  version: string;
  description: string;
  capability: string;
  risk_level: number;
  allowed_lanes: Array<'model_lane' | 'interactive_lane'>;
  supported_platforms: string[];
  timeout: number;
  max_retries: number;
  idempotency_policy: string;
  side_effect_class: string;
  verification_strategy: string;
  undo_strategy: string;
  required_approval: boolean;
  allowed_roots: string[];
  network_policy: string;
  enabled: boolean;
  degraded_reason: string;
  runtime_available: boolean;
  healthy: boolean;
}

export interface ToolHealth {
  healthy: boolean;
  registered: number;
  available: number;
  degraded: number;
  lanes: Record<string, { limit: number; active: number }>;
}

export interface ToolActionInfo {
  action_id: string;
  proposal_id: string;
  task_id: string;
  approval_id: string | null;
  tool_run_id: string | null;
  tool_id: string;
  capability: string;
  risk_level: number;
  target: string;
  expected_side_effect: string;
  verification_plan: string;
  undo_plan: string;
  status: string;
  verification_status: string;
  output_summary: string;
  error: string;
  retry_count: number;
  effect_known: boolean;
  parameter_summary: Record<string, unknown>;
  expected_result: string;
  updated_at: string;
}

export interface ToolArtifactInfo {
  artifact_id: string;
  action_id: string;
  kind: string;
  path: string;
  sha256: string;
  size_bytes: number;
  media_type: string;
  redacted: boolean;
  restore_of: string | null;
}

export interface BrowserSessionInfo {
  session_id: string;
  status: string;
  profile_path: string;
  control_port: number;
  browser_pid: number | null;
  control_service_pid: number | null;
  recovery_attempts: number;
  maximum_recovery_attempts: number;
  safe_checkpoint: string;
  effect_known: boolean;
  owned_process: boolean;
}

export interface BrowserHealthInfo {
  session_id: string;
  healthy: boolean;
  browser_process_present: boolean;
  browser_pid: number | null;
  control_service_present: boolean;
  control_service_pid: number | null;
  control_port: number;
  port_open: boolean;
  port_owner_matches: boolean;
  connection_ok: boolean;
  cause: string;
}

export interface SystemHealthComponent {
  status: 'healthy' | 'unavailable';
  available: boolean;
  [key: string]: unknown;
}

export interface SystemHealth {
  status: 'healthy' | 'degraded';
  version: string;
  components: Record<string, SystemHealthComponent>;
  pending_approvals: number;
  open_tasks: number;
  unavailable: string[];
  last_error_category: string | null;
  credential_safe: boolean;
}

export async function fetchCanonicalTasks(limit = 50): Promise<CanonicalTask[]> {
  const data = await apiJson<{ tasks: CanonicalTask[] }>(`/v1/tasks?limit=${limit}`);
  return data.tasks || [];
}

export async function fetchTaskTimeline(
  taskId: string,
  afterSequence = 0,
  signal?: AbortSignal,
): Promise<CanonicalTaskEvent[]> {
  const data = await apiJson<{ events: CanonicalTaskEvent[] }>(
    `/v1/tasks/${encodeURIComponent(taskId)}/timeline?after_sequence=${afterSequence}`,
    {},
    { signal },
  );
  return data.events || [];
}

export async function fetchTaskSources(
  taskId: string,
  signal?: AbortSignal,
): Promise<CanonicalTaskSource[]> {
  const data = await apiJson<{ sources: CanonicalTaskSource[] }>(
    `/v1/tasks/${encodeURIComponent(taskId)}/sources`,
    {},
    { signal },
  );
  return data.sources || [];
}

export async function fetchTaskSummary(
  taskId: string,
  signal?: AbortSignal,
): Promise<TaskSummary> {
  return apiJson<TaskSummary>(
    `/v1/tasks/${encodeURIComponent(taskId)}/summary`,
    { cache: 'no-store' },
    { signal },
  );
}

export async function fetchTaskArtifacts(
  taskId: string,
  signal?: AbortSignal,
): Promise<TaskArtifactInfo[]> {
  const data = await apiJson<{ artifacts: TaskArtifactInfo[] }>(
    `/v1/tasks/${encodeURIComponent(taskId)}/artifacts`,
    {},
    { signal },
  );
  return data.artifacts || [];
}

export async function fetchSessions(signal?: AbortSignal): Promise<SessionSummary[]> {
  const data = await apiJson<{ sessions: SessionSummary[] }>(
    '/v1/sessions',
    {},
    { signal },
  );
  return data.sessions || [];
}

export async function sendCanonicalChat(
  body: {
    message: string;
    session_id: string;
    task_id: string;
    input_mode: 'text' | 'voice';
    use_memory?: boolean;
  },
  mutation: MutationContext,
  signal?: AbortSignal,
): Promise<CanonicalChatResponse> {
  return apiJson<CanonicalChatResponse>(
    '/v1/chat',
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Correlation-ID': mutation.correlationId,
        'Idempotency-Key': mutation.idempotencyKey,
      },
      body: JSON.stringify(body),
    },
    { timeoutMs: 310_000, signal },
  );
}

async function mutateTask(
  taskId: string,
  action: 'pause' | 'resume' | 'interrupt' | 'cancel',
  mutation: MutationContext,
  signal?: AbortSignal,
): Promise<CanonicalTask> {
  const result = await apiJson<CanonicalTask | { task: CanonicalTask }>(
    `/v1/tasks/${encodeURIComponent(taskId)}/${action}`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Correlation-ID': mutation.correlationId,
        'Idempotency-Key': mutation.idempotencyKey,
      },
      body: action === 'resume' ? JSON.stringify({ finalize_task: false }) : undefined,
    },
    { timeoutMs: action === 'resume' ? 310_000 : 15_000, signal },
  );
  return 'task' in result ? result.task : result;
}

export const pauseCanonicalTask = (
  taskId: string,
  mutation: MutationContext,
  signal?: AbortSignal,
) => mutateTask(taskId, 'pause', mutation, signal);

export const resumeCanonicalTask = (
  taskId: string,
  mutation: MutationContext,
  signal?: AbortSignal,
) => mutateTask(taskId, 'resume', mutation, signal);

export const interruptCanonicalTask = (
  taskId: string,
  mutation: MutationContext,
  signal?: AbortSignal,
) => mutateTask(taskId, 'interrupt', mutation, signal);

export const cancelCanonicalTask = (
  taskId: string,
  mutation: MutationContext,
  signal?: AbortSignal,
) => mutateTask(taskId, 'cancel', mutation, signal);

export async function fetchTaskUsage(taskId: string): Promise<CanonicalTaskUsage> {
  const res = await apiFetch(`/v1/tasks/${encodeURIComponent(taskId)}/usage`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function fetchCodexRuntimeHealth(): Promise<CodexRuntimeHealth> {
  const res = await apiFetch(`/v1/codex/health`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function fetchRegisteredTools(): Promise<ToolManifestInfo[]> {
  const res = await apiFetch('/v1/tools');
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.tools || [];
}

export async function fetchToolHealth(): Promise<ToolHealth> {
  const res = await apiFetch('/v1/tools/health');
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export interface McpToolStatus {
  name: string;
  tool_id: string;
  policy: 'read' | 'prepare' | 'write' | 'blocked';
}

export interface McpServerStatus {
  server_id: string;
  label: string;
  transport: 'http' | 'stdio';
  enabled: boolean;
  url: string;
  command: string;
  args: string[];
  token_env: string;
  token_configured: boolean;
  include_tools: string[];
  exclude_tools: string[];
  tool_policies: Record<string, McpToolStatus['policy']>;
  connected: boolean;
  tool_count: number;
  tools: McpToolStatus[];
  last_connected_at: string;
  last_error: string;
}

export interface McpStatus {
  available: boolean;
  servers: McpServerStatus[];
  connected_servers: number;
  disconnected_servers: number;
  discovered_tools: number;
  active_provider: 'mcp' | 'none';
}

export type McpServerInput = Pick<
  McpServerStatus,
  | 'server_id'
  | 'label'
  | 'transport'
  | 'enabled'
  | 'url'
  | 'command'
  | 'args'
  | 'token_env'
  | 'include_tools'
  | 'exclude_tools'
  | 'tool_policies'
>;

const mutationHeaders = (mutation: MutationContext): Record<string, string> => ({
  'Content-Type': 'application/json',
  'X-Correlation-ID': mutation.correlationId,
  'Idempotency-Key': mutation.idempotencyKey,
});

export const fetchMcpStatus = (): Promise<McpStatus> => apiJson('/v1/mcp/status');

export async function saveMcpServer(server: McpServerInput): Promise<void> {
  const mutation = createMutationContext('mcp-save');
  await apiJson(`/v1/mcp/servers/${encodeURIComponent(server.server_id)}`, {
    method: 'PUT',
    headers: mutationHeaders(mutation),
    body: JSON.stringify(server),
  });
}

export async function removeMcpServer(serverId: string): Promise<void> {
  const mutation = createMutationContext('mcp-remove');
  await apiJson(`/v1/mcp/servers/${encodeURIComponent(serverId)}`, {
    method: 'DELETE',
    headers: mutationHeaders(mutation),
  });
}

export async function reconnectMcpServer(serverId: string): Promise<McpStatus> {
  const mutation = createMutationContext('mcp-reconnect');
  return apiJson(`/v1/mcp/servers/${encodeURIComponent(serverId)}/reconnect`, {
    method: 'POST',
    headers: mutationHeaders(mutation),
  }, { timeoutMs: 90_000 });
}

export async function interruptMcp(): Promise<void> {
  const mutation = createMutationContext('mcp-interrupt');
  await apiJson('/v1/mcp/interrupt', {
    method: 'POST',
    headers: mutationHeaders(mutation),
  });
}

export interface DesktopTargetStatus {
  target_id: string;
  label: string;
  executable: string;
  title_contains: string;
  mode: 'off' | 'observe' | 'interact';
  capabilities: string[];
  connected: boolean;
}

export interface DesktopStatus {
  available: boolean;
  mode: 'off' | 'configured';
  secure_desktop: string;
  secure_desktop_blocked: boolean;
  interrupt_requested: boolean;
  interrupt_available: boolean;
  current_target_id: string | null;
  current_window: string;
  target_monitor: string;
  target_dpi: number | null;
  target_scale: number | null;
  semantic_backend: 'not_checked' | 'windows_uia' | 'win32_fallback';
  last_action: { action: string; verified: boolean; timestamp: number } | null;
  targets: DesktopTargetStatus[];
  unsupported_boundaries: string[];
}

export type DesktopTargetInput = Omit<DesktopTargetStatus, 'connected'>;

export const fetchDesktopStatus = (): Promise<DesktopStatus> => apiJson('/v1/desktop/status');

export async function saveDesktopTarget(target: DesktopTargetInput): Promise<void> {
  const mutation = createMutationContext('desktop-save');
  await apiJson(`/v1/desktop/targets/${encodeURIComponent(target.target_id)}`, {
    method: 'PUT',
    headers: mutationHeaders(mutation),
    body: JSON.stringify(target),
  });
}

export async function connectDesktopTarget(targetId: string): Promise<void> {
  const mutation = createMutationContext('desktop-connect');
  await apiJson('/v1/desktop/connect', {
    method: 'POST',
    headers: mutationHeaders(mutation),
    body: JSON.stringify({ target_id: targetId }),
  });
}

export async function interruptDesktop(): Promise<void> {
  const mutation = createMutationContext('desktop-interrupt');
  await apiJson('/v1/desktop/interrupt', {
    method: 'POST',
    headers: mutationHeaders(mutation),
  });
}

export async function fetchTaskActions(taskId: string): Promise<ToolActionInfo[]> {
  const res = await apiFetch(`/v1/tasks/${encodeURIComponent(taskId)}/actions`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.actions || [];
}

export async function fetchActionArtifacts(actionId: string): Promise<ToolArtifactInfo[]> {
  const res = await apiFetch(`/v1/actions/${encodeURIComponent(actionId)}/artifacts`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.artifacts || [];
}

export async function fetchBrowserSessions(): Promise<BrowserSessionInfo[]> {
  const res = await apiFetch('/v1/browser/sessions');
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.sessions || [];
}

export async function fetchBrowserHealth(): Promise<BrowserHealthInfo[]> {
  const res = await apiFetch('/v1/browser/health');
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.sessions || [];
}

export async function fetchSystemHealth(signal?: AbortSignal): Promise<SystemHealth> {
  return apiJson<SystemHealth>('/v1/system/health', {}, { signal });
}

// ---------------------------------------------------------------------------
// Inference source (desktop only)
// ---------------------------------------------------------------------------

export type InferenceSource = {
  kind: 'ollama' | 'custom';
  model?: string;
  host?: string;
  engine?: string;
};

export async function getInferenceSource(): Promise<InferenceSource> {
  if (isTauri()) {
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      return await invoke<InferenceSource>('get_inference_source');
    } catch (e: any) {
      throw new Error(e?.message ?? e ?? 'Failed to read inference source');
    }
  }
  return { kind: 'ollama' };
}

export async function setInferenceSource(
  src: InferenceSource & { apiKey?: string },
): Promise<void> {
  if (!isTauri()) throw new Error('Inference source is configurable in the desktop app only.');
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    await invoke<void>('set_inference_source', {
      kind: src.kind,
      model: src.model ?? null,
      host: src.host ?? null,
      engine: src.engine ?? null,
      apiKey: src.apiKey ?? null,
    });
  } catch (e: any) {
    // Surface the backend's actionable error strings (e.g. "A server URL is
    // required…", "Could not store the API key…") as proper Error instances.
    throw new Error(e?.message ?? e ?? 'Failed to save inference source');
  }
}
