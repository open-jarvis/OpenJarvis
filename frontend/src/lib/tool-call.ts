/** Convert tool-call arguments from API or persisted data into display-safe text. */
export function serializeToolCallArguments(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value == null) return '';

  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
}
