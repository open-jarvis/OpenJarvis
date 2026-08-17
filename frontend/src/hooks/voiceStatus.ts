export type LocalVoiceStatus =
  | 'idle'
  | 'connecting'
  | 'listening'
  | 'speaking'
  | 'busy'
  | 'processing'
  | 'inference'
  | 'tool'
  | 'error'
  | 'ended';

export function voiceStatusText(
  status: LocalVoiceStatus,
  error: string | null,
): string {
  if (error) return error;
  let text = '';
  if (status === 'connecting') text = 'Connecting voice...';
  if (status === 'listening') text = 'Listening...';
  if (status === 'speaking') text = 'Speaking...';
  if (status === 'busy') text = 'Processing voice...';
  if (status === 'processing') text = 'Processing...';
  if (status === 'inference') text = 'Inferring...';
  if (status === 'tool') text = 'Running tool...';
  return text;
}
