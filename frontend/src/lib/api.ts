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

/** Pre-fetch the API base URL from the Tauri backend (call once at init). */
export async function initApiBase(): Promise<void> {
  if (!isTauri()) return;
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    _tauriApiBase = await invoke<string>('get_api_base');
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
  source?: 'ollama' | 'custom'; // drives source-aware setup labels
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
// Approvals
// ---------------------------------------------------------------------------

export interface PendingApproval {
  id: string;
  source?: 'codex_task';
  task_id?: string;
  action_type: string;
  description: string;
  action?: string;
  target?: string;
  effect?: string;
  risk_level?: number;
  sandbox?: string;
  cwd?: string;
  undo?: string;
  payload: Record<string, unknown>;
  permission_key: string;
  tier: 'trivial' | 'low' | 'medium' | 'high';
  status: string;
  created_at: string;
  expires_at: string;
}

export async function fetchPendingApprovals(): Promise<PendingApproval[]> {
  const res = await apiFetch(`/v1/approvals/pending`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.actions || [];
}

export async function approveAction(actionId: string): Promise<void> {
  const res = await apiFetch(`/v1/approvals/${actionId}/approve`, {
    method: 'POST',
    headers: {
      'X-Correlation-ID': `ui-approval-${actionId}`,
      'Idempotency-Key': `ui-approval-${actionId}-allow`,
    },
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export async function denyAction(actionId: string): Promise<void> {
  const res = await apiFetch(`/v1/approvals/${actionId}/deny`, {
    method: 'POST',
    headers: {
      'X-Correlation-ID': `ui-approval-${actionId}`,
      'Idempotency-Key': `ui-approval-${actionId}-deny`,
    },
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
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

export interface TaskSummary {
  task: CanonicalTask;
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
    {},
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

// ---------------------------------------------------------------------------
// Isolated website staging pilot
// ---------------------------------------------------------------------------

export interface WebsiteFileDiff {
  relative_path: string;
  change: 'created' | 'modified' | 'unchanged';
  before_sha256: string | null;
  after_sha256: string;
  size_bytes: number;
}

export interface WebsiteFileProposalSummary {
  relative_path: string;
  media_type: string;
  size_bytes: number;
  proposed_sha256: string;
  expected_before_sha256: string | null;
}

export interface WebsiteStagingPlanInfo {
  request: {
    request_id: string;
    task_id: string;
    session_id: string;
    correlation_id: string;
    workspace_id: string;
    idempotency_key: string;
  };
  proposals: WebsiteFileProposalSummary[];
  file_diffs: WebsiteFileDiff[];
  risk_level: number;
  warnings: string[];
  external_urls: string[];
  script_files: string[];
  preview_hash: string;
  predicted_manifest_sha256: string;
}

export interface WebsiteStagingAction {
  action_id: string;
  status: string;
  verification_status: string;
  approval_id: string | null;
  risk_level: number;
  error: string;
}

export interface WebsiteStagingExecutionInfo {
  execution_id: string;
  status: string;
  no_op: boolean;
  after_manifest_sha256: string;
  artifact_manifest_sha256: string;
  verification_hash: string;
  trace_evaluation_hash: string | null;
}

export interface WebsiteVerificationInfo {
  status: 'passed' | 'warning' | 'failed';
  passed: boolean;
  file_count: number;
  total_bytes: number;
  manifest_sha256: string;
  errors: string[];
  warnings: string[];
  verification_hash: string;
}

export interface WebsiteArtifactManifestInfo {
  manifest_sha256: string;
  artifacts: Array<{
    artifact_id: string;
    relative_path: string;
    media_type: string;
    size_bytes: number;
    sha256: string;
    verification_status: string;
    warnings: string[];
  }>;
}

export interface WebsiteRollbackInfo {
  rollback_id: string;
  byte_identical: boolean;
  drift_detected: boolean;
  restore_probe_removed: boolean;
  record_hash: string;
}

export interface WebsiteStagingWorkspace {
  schema_version: string;
  workspace_id: string;
  plan: WebsiteStagingPlanInfo;
  execution?: WebsiteStagingExecutionInfo;
  verification?: WebsiteVerificationInfo;
  artifact_manifest?: WebsiteArtifactManifestInfo;
  rollback?: WebsiteRollbackInfo;
}

export async function fetchWebsiteStagingWorkspace(
  workspaceId: string,
): Promise<WebsiteStagingWorkspace> {
  return apiJson<WebsiteStagingWorkspace>(
    `/v1/website-staging/${encodeURIComponent(workspaceId)}`,
  );
}

function websiteMutationHeaders(workspace: WebsiteStagingWorkspace): Record<string, string> {
  return {
    'Content-Type': 'application/json',
    'X-Actor': 'local-ui',
    'X-Correlation-ID': workspace.plan.request.correlation_id,
    'Idempotency-Key': workspace.plan.request.idempotency_key,
  };
}

export async function applyWebsiteStaging(
  workspace: WebsiteStagingWorkspace,
  decision: 'request_approval' | 'allow_once' | 'deny',
): Promise<{ action: WebsiteStagingAction; execution: WebsiteStagingExecutionInfo | null; allow_once_only: true }> {
  return apiJson('/v1/website-staging/apply', {
    method: 'POST',
    headers: websiteMutationHeaders(workspace),
    body: JSON.stringify({
      workspace_id: workspace.workspace_id,
      request_id: workspace.plan.request.request_id,
      expected_preview_hash: workspace.plan.preview_hash,
      decision,
    }),
  });
}

export async function validateWebsiteStaging(
  workspace: WebsiteStagingWorkspace,
): Promise<WebsiteVerificationInfo> {
  if (!workspace.execution) throw new Error('Website staging has no execution to validate.');
  return apiJson('/v1/website-staging/validate', {
    method: 'POST',
    headers: websiteMutationHeaders(workspace),
    body: JSON.stringify({
      workspace_id: workspace.workspace_id,
      expected_manifest_hash: workspace.execution.after_manifest_sha256,
    }),
  });
}

export async function rollbackWebsiteStaging(
  workspace: WebsiteStagingWorkspace,
): Promise<{ action: WebsiteStagingAction; rollback: WebsiteRollbackInfo | null; allow_once_only: true }> {
  if (!workspace.execution) throw new Error('Website staging has no execution to roll back.');
  return apiJson('/v1/website-staging/rollback', {
    method: 'POST',
    headers: websiteMutationHeaders(workspace),
    body: JSON.stringify({
      workspace_id: workspace.workspace_id,
      execution_id: workspace.execution.execution_id,
      expected_manifest_hash: workspace.execution.after_manifest_sha256,
      decision: 'allow_once',
    }),
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

export async function approveToolAction(actionId: string): Promise<ToolActionInfo> {
  const res = await apiFetch(`/v1/actions/${encodeURIComponent(actionId)}/approve`, {
    method: 'POST',
    headers: {
      'X-Correlation-ID': `ui-tool-${actionId}`,
      'Idempotency-Key': `ui-tool-${actionId}-allow-once`,
    },
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function denyToolAction(actionId: string): Promise<ToolActionInfo> {
  const res = await apiFetch(`/v1/actions/${encodeURIComponent(actionId)}/deny`, {
    method: 'POST',
    headers: {
      'X-Correlation-ID': `ui-tool-${actionId}`,
      'Idempotency-Key': `ui-tool-${actionId}-deny`,
    },
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Phase-7 learning, shadow routing, feedback, and verified skills
// ---------------------------------------------------------------------------

export interface LearningHealth {
  status: 'healthy' | 'degraded';
  evaluator_version: string;
  extractor_version: string;
  migrations: Array<{ version: number; checksum: string }>;
  store_status: string;
  open_conflicts: number;
  quarantined_candidates: number;
  promotion_pending: number;
  active_skill_versions: number;
  last_verification: string | null;
  last_metric_revision: string | null;
  shadow_routing: {
    enabled: boolean;
    shadow_mode: true;
    productive_route_changes: false;
    recommendations: number;
  };
  feedback_store: {
    status: string;
    records: number;
    approval_authority: false;
  };
  integrity_errors: string[];
  recovery_status: string;
}

export interface TraceEvaluationInfo {
  evaluation_id: string;
  task_id: string;
  session_id: string;
  correlation_id: string;
  task_type: string;
  evaluation_class: string;
  verification_state: string;
  evidence_state: string;
  confidence: string;
  confidence_basis: string[];
  evidence_references: Array<Record<string, unknown>>;
  warnings: string[];
  evaluator_version: string;
  evaluation_hash: string;
  created_at: string;
}

export interface LearningCandidateInfo {
  candidate_id: string;
  revision: number;
  candidate_type: string;
  title: string;
  structured_content: Record<string, unknown>;
  scope: string;
  project: string;
  origin: string;
  provenance: Array<Record<string, unknown>>;
  source_evidence_ids: string[];
  confidence: string;
  confidence_basis: string[];
  independence_count: number;
  duplicate_signature: string;
  conflict_signature: string;
  risk_level: number;
  proposed_tests: string[];
  proposed_verification: string[];
  state: string;
  quarantine_reasons: string[];
  rejection_reason: string | null;
  content_hash: string;
}

export interface CandidateHistoryInfo {
  candidate_id: string;
  revisions: Array<Record<string, unknown>>;
  reviews: Array<Record<string, unknown>>;
}

export interface LearningConflictInfo {
  conflict_id: string;
  candidate_ids: [string, string];
  candidate_revisions?: [number, number];
  conflict_signature: string;
  conflict_type: string;
  priority: string;
  reason: string;
  is_open: boolean;
}

export interface RoutingRecommendationView {
  recommendation: {
    recommendation_id: string;
    task_id: string;
    task_type: string;
    recommended_route: string;
    alternative_routes: string[];
    evidence_references: Array<Record<string, unknown>>;
    skill_id: string | null;
    semantic_version: string | null;
    expected_risk: number;
    expected_cost: number;
    expected_latency: number;
    confidence: number;
    confidence_basis: string[];
    known_limitations: string[];
    sample_size: number;
    small_sample: boolean;
    shadow_mode: true;
    actual_route: string;
    comparison_result: 'pending';
    recommendation_hash: string;
    created_at: string;
  };
  comparison: null | {
    comparison_id: string;
    actual_route: string;
    actual_risk: number;
    actual_cost: number;
    actual_latency: number;
    verified_success: boolean;
    comparison_result: string;
    comparison_hash: string;
  };
}

export interface FeedbackRecordInfo {
  feedback_id: string;
  revision: number;
  task_id: string;
  session_id: string;
  correlation_id: string;
  answer_id: string | null;
  execution_id: string | null;
  actor: string;
  feedback_type: string;
  structured_content: Record<string, unknown>;
  source_digest: string;
  source_priority: string;
  supersedes_revision: number | null;
  created_at: string;
  revoked_at: string | null;
  feedback_hash: string;
}

export interface TaskFeedbackInfo {
  task_id: string;
  feedback: FeedbackRecordInfo[];
  history: Record<string, FeedbackRecordInfo[]>;
}

export interface SkillVersionView {
  version: {
    skill_id: string;
    semantic_version: string;
    registry_revision: number;
    manifest_hash: string;
    candidate_id: string;
    candidate_revision: number;
  };
  head: {
    lifecycle_state: string;
    state_revision: number;
    candidate_id: string;
    candidate_revision: number;
    manifest_hash: string;
  };
  manifest: {
    skill_id: string;
    semantic_version: string;
    scope: string;
    origin_candidate_id: string;
    origin_candidate_revision: number;
    allowed_tool_ids: string[];
    required_capabilities: string[];
    maximum_risk_level: number;
    known_limitations: string[];
    content_hash: string;
    deprecated_at: string | null;
  };
  metrics: Array<Record<string, unknown>>;
  verification: Array<Record<string, unknown>>;
  executions: Array<Record<string, unknown>>;
  rollbacks: Array<Record<string, unknown>>;
  promotions: Array<Record<string, unknown>>;
  activations: Array<Record<string, unknown>>;
  deprecations: Array<Record<string, unknown>>;
  packages: Array<Record<string, unknown>>;
  quarantined_imports: Array<Record<string, unknown>>;
}

export interface SkillDetailInfo {
  skill_id: string;
  versions: SkillVersionView[];
}

const phase7Mutation = <T>(
  path: string,
  body: Record<string, unknown>,
  mutation: MutationContext,
): Promise<T> => apiJson<T>(path, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-Correlation-ID': mutation.correlationId,
    'Idempotency-Key': mutation.idempotencyKey,
  },
  body: JSON.stringify(body),
});

export const fetchLearningHealth = (): Promise<LearningHealth> =>
  apiJson<LearningHealth>('/v1/learning/health');

export async function fetchLearningEvaluations(): Promise<TraceEvaluationInfo[]> {
  const data = await apiJson<{ evaluations: TraceEvaluationInfo[] }>(
    '/v1/learning/evaluations',
  );
  return data.evaluations || [];
}

export async function fetchLearningCandidates(): Promise<LearningCandidateInfo[]> {
  const data = await apiJson<{ candidates: LearningCandidateInfo[] }>(
    '/v1/learning/candidates',
  );
  return data.candidates || [];
}

export const fetchCandidateHistory = (candidateId: string): Promise<CandidateHistoryInfo> =>
  apiJson<CandidateHistoryInfo>(
    `/v1/learning/candidates/${encodeURIComponent(candidateId)}/history`,
  );

export async function fetchLearningConflicts(): Promise<LearningConflictInfo[]> {
  const data = await apiJson<{ conflicts: LearningConflictInfo[] }>(
    '/v1/learning/conflicts',
  );
  return data.conflicts || [];
}

export async function fetchRoutingRecommendations(
  taskId?: string,
): Promise<RoutingRecommendationView[]> {
  const suffix = taskId ? `?task_id=${encodeURIComponent(taskId)}` : '';
  const data = await apiJson<{ recommendations: RoutingRecommendationView[] }>(
    `/v1/learning/routing/recommendations${suffix}`,
  );
  return data.recommendations || [];
}

export async function fetchTaskFeedback(taskId: string): Promise<TaskFeedbackInfo> {
  return apiJson<TaskFeedbackInfo>(
    `/v1/tasks/${encodeURIComponent(taskId)}/feedback`,
  );
}

export async function fetchCanonicalSkills(): Promise<SkillDetailInfo[]> {
  const data = await apiJson<{ skills: SkillDetailInfo[] }>('/v1/skills');
  return data.skills || [];
}

export const reviewLearningCandidate = (
  candidateId: string,
  body: Record<string, unknown>,
  mutation: MutationContext,
) => phase7Mutation(
  `/v1/learning/candidates/${encodeURIComponent(candidateId)}/review`,
  body,
  mutation,
);

export const rejectLearningCandidate = (
  candidateId: string,
  body: Record<string, unknown>,
  mutation: MutationContext,
) => phase7Mutation(
  `/v1/learning/candidates/${encodeURIComponent(candidateId)}/reject`,
  body,
  mutation,
);

export const resolveLearningConflict = (
  conflictId: string,
  body: Record<string, unknown>,
  mutation: MutationContext,
) => phase7Mutation(
  `/v1/learning/conflicts/${encodeURIComponent(conflictId)}/resolve`,
  body,
  mutation,
);

export const testCanonicalSkill = (
  skillId: string,
  body: Record<string, unknown>,
  mutation: MutationContext,
) => phase7Mutation(`/v1/skills/${encodeURIComponent(skillId)}/test`, body, mutation);

export const requestSkillPromotion = (
  skillId: string,
  body: Record<string, unknown>,
  mutation: MutationContext,
) => phase7Mutation(
  `/v1/skills/${encodeURIComponent(skillId)}/request-promotion`,
  body,
  mutation,
);

export const decideSkillPromotion = (
  skillId: string,
  body: Record<string, unknown>,
  mutation: MutationContext,
) => phase7Mutation(
  `/v1/skills/${encodeURIComponent(skillId)}/decide-promotion`,
  body,
  mutation,
);

export const activateCanonicalSkill = (
  skillId: string,
  body: Record<string, unknown>,
  mutation: MutationContext,
) => phase7Mutation(
  `/v1/skills/${encodeURIComponent(skillId)}/activate`,
  body,
  mutation,
);

export const deprecateCanonicalSkill = (
  skillId: string,
  body: Record<string, unknown>,
  mutation: MutationContext,
) => phase7Mutation(
  `/v1/skills/${encodeURIComponent(skillId)}/deprecate`,
  body,
  mutation,
);

export const rollbackCanonicalSkill = (
  skillId: string,
  body: Record<string, unknown>,
  mutation: MutationContext,
) => phase7Mutation(
  `/v1/skills/${encodeURIComponent(skillId)}/rollback`,
  body,
  mutation,
);

export const recordTaskFeedback = (
  taskId: string,
  body: Record<string, unknown>,
  mutation: MutationContext,
) => phase7Mutation(
  `/v1/tasks/${encodeURIComponent(taskId)}/feedback`,
  body,
  mutation,
);

export const reviseTaskFeedback = (
  feedbackId: string,
  body: Record<string, unknown>,
  mutation: MutationContext,
) => phase7Mutation(
  `/v1/feedback/${encodeURIComponent(feedbackId)}/revise`,
  body,
  mutation,
);

export const revokeTaskFeedback = (
  feedbackId: string,
  body: Record<string, unknown>,
  mutation: MutationContext,
) => phase7Mutation(
  `/v1/feedback/${encodeURIComponent(feedbackId)}/revoke`,
  body,
  mutation,
);

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
