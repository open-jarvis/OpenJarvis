const CLOUD_PREFIXES = [
  'gpt-',
  'o1-',
  'o3-',
  'o4-',
  'claude-',
  'gemini-',
  'openrouter/',
  'MiniMax-',
  'chatgpt-',
];

export function engineFromCompletionChunk(data: unknown): string | undefined {
  if (!data || typeof data !== 'object') return undefined;
  const telemetry = (data as { telemetry?: unknown }).telemetry;
  if (!telemetry || typeof telemetry !== 'object') return undefined;
  const engine = (telemetry as { engine?: unknown }).engine;
  if (typeof engine !== 'string' || !engine.trim()) return undefined;
  return engine.trim();
}

/**
 * Audio this completion produced, if any.
 *
 * Read it from the completion itself. Asking /api/digest instead answers a
 * different question -- whether a digest exists at all -- so once the morning
 * digest had ever written a .wav, every ordinary reply rendered a player for
 * that recording.
 */
export function audioFromCompletionChunk(
  data: unknown,
): { url: string } | undefined {
  if (!data || typeof data !== 'object') return undefined;
  const audio = (data as { audio?: unknown }).audio;
  if (!audio || typeof audio !== 'object') return undefined;
  const url = (audio as { url?: unknown }).url;
  if (typeof url !== 'string' || !url.trim()) return undefined;
  return { url: url.trim() };
}

export function resolveChatEngine({
  routedEngine,
  serverEngine,
  selectedModel,
  selectedOwner,
}: {
  routedEngine?: string;
  serverEngine?: string;
  selectedModel: string;
  selectedOwner?: string;
}): string {
  // The finish chunk describes the backend that handled this exact request.
  // /v1/info describes only the server's configured wrapper (often "multi").
  if (routedEngine?.trim()) return routedEngine.trim();
  if (serverEngine?.trim()) return serverEngine.trim();
  if (selectedOwner === 'litellm') return 'litellm';
  return CLOUD_PREFIXES.some((prefix) => selectedModel.startsWith(prefix))
    ? 'cloud'
    : 'ollama';
}
