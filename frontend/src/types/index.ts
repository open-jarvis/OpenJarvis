// --- SSE Event Types ---

export interface SSEEvent {
  event?: string;
  data: string;
}

export interface AgentTurnStartEvent {
  agent: string;
  input: string;
}

export interface InferenceStartEvent {
  model: string;
  engine: string;
  turn: number;
}

export interface InferenceEndEvent {
  model: string;
  engine: string;
  turn: number;
}

export interface ToolCallStartEvent {
  tool: string;
  arguments: string;
}

export interface ToolCallEndEvent {
  tool: string;
  success: boolean;
  latency: number;
}

// --- Chat Types ---

export interface ToolCallInfo {
  id: string;
  tool: string;
  arguments: string;
  status: 'running' | 'success' | 'error';
  result?: string;
  latency?: number;
}

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface MessageTelemetry {
  engine?: string;
  model_id?: string;
  tokens_per_sec?: number;
  ttft_ms?: number;
  total_ms?: number;
  complexity_score?: number;
  complexity_tier?: string;
  suggested_max_tokens?: number;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  toolCalls?: ToolCallInfo[];
  usage?: TokenUsage;
  telemetry?: MessageTelemetry;
  audio?: { url: string };
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  model: string;
  messages: ChatMessage[];
}

export interface ConversationStore {
  version: 1;
  conversations: Record<string, Conversation>;
  activeId: string | null;
}

// --- Stream State ---

export interface StreamState {
  isStreaming: boolean;
  phase: string;
  elapsedMs: number;
  activeToolCalls: ToolCallInfo[];
  content: string;
}

// --- API Types ---

export interface ModelInfo {
  id: string;
  object: string;
  created: number;
  owned_by: string;
}

export interface ProviderSavings {
  provider: string;
  label: string;
  input_cost: number;
  output_cost: number;
  total_cost: number;
  energy_wh: number;
  energy_joules: number;
  flops: number;
}

export interface SavingsData {
  total_calls: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  local_cost: number;
  per_provider: ProviderSavings[];
  token_counting_version?: number;
}

export interface ServerInfo {
  model: string;
  agent: string | null;
  engine: string;
}

export type OpenClawComponentStatus = 'pass' | 'warn' | 'fail';

export interface OpenClawHealthComponent {
  id: string;
  label: string;
  status: OpenClawComponentStatus;
  detail: string;
  action: string;
  group: string;
  critical: boolean;
}

export interface OpenClawHealth {
  status: 'healthy' | 'degraded' | 'critical';
  score: number;
  generated_at: number;
  summary: {
    passes: number;
    warnings: number;
    failures: number;
  };
  primary_local_llm: {
    host: string;
    model: string;
  };
  paths: {
    openjarvis_root: string;
    openclaw_root: string;
    openclaw_home: string;
  };
  components: OpenClawHealthComponent[];
  recommendations: string[];
  latest_report: {
    exists: boolean;
    path: string;
    modified_at: number | null;
    age_seconds: number | null;
    security: {
      critical: number;
      warn: number;
      info: number;
    };
    highlights: string[];
  };
  project_agents?: {
    atop_dev?: ProjectAgentPerformance;
  };
}

export interface ProjectAgentPerformance {
  project_id: string;
  project_name: string;
  root: string;
  status: 'healthy' | 'attention' | 'unavailable';
  summary: {
    agents: number;
    healthy: number;
    attention: number;
    no_data: number;
    runs_last_24h: number;
    avg_success_rate: number;
  };
  agents: ProjectAgentScorecard[];
  error: string;
}

export interface ProjectAgentScorecard {
  agent_id: string;
  display_name: string;
  scorecard_status: string;
  catalog_status: string;
  stage: string;
  runs_last_24h: number;
  success_rate_last_20_runs: number;
  median_duration_ms_last_20_runs: number;
  last_run_status: string;
  last_run_started_at: string;
  latest_artifact_path: string;
  latest_failure_status: string;
}

// --- Log Types ---

export interface LogEntry {
  timestamp: number;
  level: 'info' | 'warn' | 'error';
  category: 'server' | 'model' | 'chat' | 'tool';
  message: string;
}
