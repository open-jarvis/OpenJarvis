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

export interface PersonalCockpitRecord {
  [key: string]: unknown;
}

export interface PersonalCockpitFileHealth {
  exists: boolean;
  path: string;
  modified_at: string;
}

export interface PersonalCockpitSnapshot {
  meta: {
    generated_at: string;
    personal_root: string;
    voice_runtime: string;
  };
  general_state: {
    status: string;
    live_status: string;
    paused: boolean;
    active_until: string;
    updated_at: string;
    age_seconds: number | null;
    turn_count: number;
    last_transcription: string;
    last_response: string;
    pending_validation?: PersonalCockpitRecord | null;
    last_validated_action?: PersonalCockpitRecord | null;
  };
  voice_live: {
    config_status: string;
    wake_word: string;
    vad: string;
    stt: string;
    tts: string;
    commands: string[];
    last_updated_at: string;
  };
  latest_transcription: string;
  latest_response: string;
  pending_validation?: PersonalCockpitRecord | null;
  last_live_brief?: PersonalCockpitRecord | null;
  yahoo_targeted_move?: PersonalCockpitRecord | null;
  yahoo_dynamic_candidate?: PersonalCockpitRecord | null;
  yahoo_dynamic_result?: PersonalCockpitRecord | null;
  session_history: Array<{
    timestamp: string;
    intent: string;
    user: string;
    assistant: string;
  }>;
  recent_actions: Array<Record<string, unknown>>;
  connectors: Array<{
    name: string;
    status: string;
    services: Record<string, string>;
    updated_at: string;
    details: PersonalCockpitRecord;
  }>;
  alerts: Array<{
    level: string;
    title: string;
    detail: string;
  }>;
  continuity: Array<{
    heading: string;
    summary: string;
  }>;
  file_health: Record<string, PersonalCockpitFileHealth>;
}

// --- Log Types ---

export interface LogEntry {
  timestamp: number;
  level: 'info' | 'warn' | 'error';
  category: 'server' | 'model' | 'chat' | 'tool';
  message: string;
}
