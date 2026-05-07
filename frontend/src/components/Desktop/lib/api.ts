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
