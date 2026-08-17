export type VoiceActivity =
  | { phase: 'processing' }
  | { phase: 'inference'; model: string }
  | { phase: 'tool'; toolName: string };

export function voiceActivityFromServerMessage(
  value: unknown,
): VoiceActivity | null {
  if (!value || typeof value !== 'object') return null;
  const data = (value as { data?: unknown }).data;
  if (!data || typeof data !== 'object') return null;
  const activity = data as {
    type?: unknown;
    phase?: unknown;
    model?: unknown;
    tool_name?: unknown;
  };
  if (activity.type !== 'voice_activity') return null;
  if (activity.phase === 'processing') return { phase: 'processing' };
  if (
    activity.phase === 'inference' &&
    typeof activity.model === 'string' &&
    activity.model
  ) {
    return { phase: 'inference', model: activity.model };
  }
  if (
    activity.phase === 'tool' &&
    typeof activity.tool_name === 'string' &&
    activity.tool_name
  ) {
    return { phase: 'tool', toolName: activity.tool_name };
  }
  return null;
}
