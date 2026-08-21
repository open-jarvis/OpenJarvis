export interface AgentScheduleSource {
  config?: Record<string, unknown> | null;
  // Retained as fallbacks for compatibility with older API responses.
  schedule_type?: unknown;
  schedule_value?: unknown;
}

export interface AgentSchedule {
  type?: string;
  value?: string;
}

function scheduleValue(value: unknown): string | undefined {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return undefined;
}

/** Read schedule fields from the managed-agent API response. */
export function getAgentSchedule(agent: AgentScheduleSource): AgentSchedule {
  const nestedType = agent.config?.schedule_type;

  return {
    type:
      typeof nestedType === 'string'
        ? nestedType
        : scheduleValue(agent.schedule_type),
    value:
      scheduleValue(agent.config?.schedule_value) ??
      scheduleValue(agent.schedule_value),
  };
}
