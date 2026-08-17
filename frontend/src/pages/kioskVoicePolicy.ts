export type KioskVoiceCommand = 'start' | 'end' | 'unavailable' | 'noop';

export function kioskVoiceCommand({
  micEnabled,
  voiceEnabled,
  started,
}: {
  micEnabled: boolean;
  voiceEnabled: boolean;
  started: boolean;
}): KioskVoiceCommand {
  if (!micEnabled) return started ? 'end' : 'noop';
  if (!voiceEnabled) return 'unavailable';
  return started ? 'noop' : 'start';
}
