// Desktop API helpers — thin wrappers around the OpenJarvis REST API.
// All functions accept an explicit apiUrl so the desktop can be pointed at any server.

// ---------------------------------------------------------------------------
// Types
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
  total_runs?: number;
  total_cost?: number;
  total_tokens?: number;
  last_run_at?: number | null;
  schedule_type?: string;
  schedule_value?: string;
  budget?: number;
  learning_enabled?: boolean;
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

export interface AgentMessage {
  id: string;
  agent_id: string;
  direction: 'user_to_agent' | 'agent_to_user';
  content: string;
  mode: 'immediate' | 'queued';
  status: 'pending' | 'delivered' | 'responded';
  created_at: number;
}

export interface AgentTemplate {
  id: string;
  name: string;
  description: string;
  source: 'built-in' | 'user';
  agent_type: string;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

async function request<T>(apiUrl: string, path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${apiUrl}${path}`, init);
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
  return res.json() as Promise<T>;
}

export async function fetchManagedAgents(apiUrl: string): Promise<ManagedAgent[]> {
  const data = await request<{ agents: ManagedAgent[] }>(apiUrl, '/v1/managed-agents');
  return data.agents || [];
}

export async function fetchAgentTasks(apiUrl: string, agentId: string): Promise<AgentTask[]> {
  const data = await request<{ tasks: AgentTask[] }>(apiUrl, `/v1/managed-agents/${agentId}/tasks`);
  return data.tasks || [];
}

export async function fetchAgentMessages(apiUrl: string, agentId: string): Promise<AgentMessage[]> {
  const data = await request<{ messages: AgentMessage[] }>(apiUrl, `/v1/managed-agents/${agentId}/messages`);
  return data.messages || [];
}

export async function fetchTemplates(apiUrl: string): Promise<AgentTemplate[]> {
  const data = await request<{ templates: AgentTemplate[] }>(apiUrl, '/v1/templates');
  return data.templates || [];
}

export async function createManagedAgent(
  apiUrl: string,
  body: { name: string; template_id?: string; config?: Record<string, unknown> },
): Promise<ManagedAgent> {
  return request<ManagedAgent>(apiUrl, '/v1/managed-agents', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export async function pauseManagedAgent(apiUrl: string, agentId: string): Promise<void> {
  await fetch(`${apiUrl}/v1/managed-agents/${agentId}/pause`, { method: 'POST' });
}

export async function resumeManagedAgent(apiUrl: string, agentId: string): Promise<void> {
  await fetch(`${apiUrl}/v1/managed-agents/${agentId}/resume`, { method: 'POST' });
}

export async function runManagedAgent(apiUrl: string, agentId: string): Promise<void> {
  await fetch(`${apiUrl}/v1/managed-agents/${agentId}/run`, { method: 'POST' });
}

export async function recoverManagedAgent(apiUrl: string, agentId: string): Promise<unknown> {
  return request<unknown>(apiUrl, `/v1/managed-agents/${agentId}/recover`, { method: 'POST' });
}

export async function deleteManagedAgent(apiUrl: string, agentId: string): Promise<void> {
  await fetch(`${apiUrl}/v1/managed-agents/${agentId}`, { method: 'DELETE' });
}

export async function sendAgentMessage(
  apiUrl: string,
  agentId: string,
  content: string,
  mode: 'immediate' | 'queued' = 'queued',
): Promise<AgentMessage> {
  return request<AgentMessage>(apiUrl, `/v1/managed-agents/${agentId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, mode }),
  });
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
}

export async function fetchLearningLog(apiUrl: string, agentId: string): Promise<LearningLogEntry[]> {
  const data = await request<{ learning_log: LearningLogEntry[] }>(apiUrl, `/v1/managed-agents/${agentId}/learning`);
  return data.learning_log || [];
}

export async function triggerLearning(apiUrl: string, agentId: string): Promise<void> {
  await fetch(`${apiUrl}/v1/managed-agents/${agentId}/learning/run`, { method: 'POST' });
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

export async function fetchAgentTraces(apiUrl: string, agentId: string, limit = 20): Promise<AgentTrace[]> {
  const data = await request<{ traces: AgentTrace[] }>(apiUrl, `/v1/managed-agents/${agentId}/traces?limit=${limit}`);
  return data.traces || [];
}

export async function fetchAgentTrace(apiUrl: string, agentId: string, traceId: string): Promise<AgentTraceDetail> {
  return request<AgentTraceDetail>(apiUrl, `/v1/managed-agents/${agentId}/traces/${traceId}`);
}

// ---------------------------------------------------------------------------
// OSINT Arsenal + Watchdog
// ---------------------------------------------------------------------------

export interface OsintToolResult {
  name: string;
  category: string;
  description: string;
  url: string | null;
  install_command: string | null;
  tags: string[];
}

export interface OsintSearchResponse {
  query: string;
  results: OsintToolResult[];
  count: number;
}

export async function searchOsintTools(
  apiUrl: string,
  query: string,
  limit = 5,
  category = "",
): Promise<OsintSearchResponse> {
  return request<OsintSearchResponse>(apiUrl, '/v1/osint/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, limit, category }),
  });
}

export interface WatchdogScanResponse {
  target: string;
  timestamp: string;
  modules: string[];
  results: Record<string, unknown>;
  summary: {
    reachable: boolean;
    privacy_protected: boolean;
    seizure_detected: boolean;
    errors: number;
  };
}

export async function fetchOsintCategories(apiUrl: string): Promise<string[]> {
  const data = await request<{ categories: string[] }>(apiUrl, '/v1/osint/categories');
  return data.categories || [];
}

export async function runWatchdogScan(
  apiUrl: string,
  target: string,
  modules: string[] = ['dns', 'http', 'whois', 'ip'],
): Promise<WatchdogScanResponse> {
  return request<WatchdogScanResponse>(apiUrl, '/v1/osint/watch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target, modules }),
  });
}

// ---------------------------------------------------------------------------
// OSINT Execution + Export
// ---------------------------------------------------------------------------

export interface OsintExecResponse {
  tool: string;
  target: string;
  type: string;
  output: string;
  success: boolean;
  metadata: Record<string, unknown>;
}

export async function execOsintTool(
  apiUrl: string,
  toolName: string,
  target: string,
  timeout = 60,
): Promise<OsintExecResponse> {
  return request<OsintExecResponse>(apiUrl, '/v1/osint/exec', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tool_name: toolName, target, timeout }),
  });
}

export interface OsintToolDetail {
  name: string;
  category: string;
  description: string;
  url: string | null;
  install_command: string | null;
  tags: string[];
}

export async function fetchOsintToolDetail(apiUrl: string, name: string): Promise<OsintToolDetail> {
  return request<OsintToolDetail>(apiUrl, `/v1/osint/tool/${encodeURIComponent(name)}`);
}

export interface WatchdogExportResponse {
  format: string;
  filename: string;
  data: Record<string, unknown> | string;
}

export async function exportWatchdogScan(
  apiUrl: string,
  target: string,
  modules: string[] = ['dns', 'http', 'whois', 'ip'],
  format: 'json' | 'csv' = 'json',
): Promise<WatchdogExportResponse> {
  return request<WatchdogExportResponse>(apiUrl, '/v1/osint/watch/export', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target, modules, format }),
  });
}

// ---------------------------------------------------------------------------
// OSINT History + Favorites
// ---------------------------------------------------------------------------

export interface HistoryEntry {
  id: string;
  type: string;
  user_id: string;
  timestamp: string;
  target: string | null;
  tool_name: string | null;
  modules: string[] | null;
  results: Record<string, unknown> | null;
  output: string | null;
  success: boolean;
  metadata: Record<string, unknown>;
}

export interface OsintHistoryResponse {
  entries: HistoryEntry[];
  count: number;
}

export async function fetchOsintHistory(apiUrl: string, limit = 50): Promise<OsintHistoryResponse> {
  return request<OsintHistoryResponse>(apiUrl, `/v1/osint/history?limit=${limit}`);
}

export async function deleteHistoryEntry(apiUrl: string, entryId: string): Promise<{ removed: boolean }> {
  return request<{ removed: boolean }>(apiUrl, `/v1/osint/history/${encodeURIComponent(entryId)}`, { method: 'DELETE' });
}

export interface FavoriteResponse {
  tool_name: string;
  favorited: boolean;
}

export async function toggleFavorite(apiUrl: string, toolName: string): Promise<FavoriteResponse> {
  return request<FavoriteResponse>(apiUrl, '/v1/osint/favorites', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tool_name: toolName }),
  });
}

export interface FavoritesListResponse {
  favorites: string[];
  count: number;
}

export async function fetchFavorites(apiUrl: string): Promise<FavoritesListResponse> {
  return request<FavoritesListResponse>(apiUrl, '/v1/osint/favorites');
}

export interface DashboardStats {
  total_scans: number;
  total_execs: number;
  total_actions: number;
  unique_targets: number;
  success_rate: number;
  top_targets: Array<{ target: string; count: number }>;
  tool_usage: Array<{ tool_name: string; count: number }>;
  module_usage: Array<{ module: string; count: number }>;
  activity_timeline: Array<{
    date: string;
    scans: number;
    execs: number;
  }>;
}

export async function fetchDashboardStats(
  apiUrl: string,
): Promise<DashboardStats> {
  return request<DashboardStats>(apiUrl, '/v1/osint/dashboard/stats');
}

export interface ScheduleJob {
  id: string;
  target: string;
  modules: string[];
  interval_minutes: number;
  last_run: string | null;
  next_run: string | null;
  enabled: boolean;
  created_at: string;
}

export interface ScheduleListResponse {
  schedules: ScheduleJob[];
  count: number;
}

export interface ScheduleCreateRequest {
  target: string;
  modules: string[];
  interval_minutes: number;
}

export async function createSchedule(
  apiUrl: string,
  body: ScheduleCreateRequest,
): Promise<ScheduleJob> {
  return request<ScheduleJob>(apiUrl, '/v1/osint/schedule', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export async function fetchSchedules(apiUrl: string): Promise<ScheduleListResponse> {
  return request<ScheduleListResponse>(apiUrl, '/v1/osint/schedule');
}

export async function deleteSchedule(
  apiUrl: string,
  scheduleId: string,
): Promise<{ removed: boolean }> {
  return request<{ removed: boolean }>(apiUrl, `/v1/osint/schedule/${scheduleId}`, {
    method: 'DELETE',
  });
}

export async function toggleSchedule(
  apiUrl: string,
  scheduleId: string,
): Promise<{ schedule_id: string; enabled: boolean }> {
  return request(apiUrl, `/v1/osint/schedule/${scheduleId}/toggle`, {
    method: 'POST',
  });
}

export interface AlertsResponse {
  alerts: Array<
    HistoryEntry & {
      metadata: {
        diff?: {
          changed?: Record<string, unknown>;
          added?: Record<string, unknown>;
          removed?: Record<string, unknown>;
        };
      };
    }
  >;
  count: number;
  unread: number;
}

export async function fetchAlerts(apiUrl: string, limit = 20): Promise<AlertsResponse> {
  return request<AlertsResponse>(apiUrl, `/v1/osint/alerts?limit=${limit}`);
}
