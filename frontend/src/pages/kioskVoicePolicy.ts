export type KioskVoiceCommand = 'start' | 'end' | 'unavailable' | 'noop';
export type KioskVoiceOwner = 'manual' | 'policy';

export function kioskVoiceCommand({
  micEnabled,
  voiceEnabled,
  owner,
}: {
  micEnabled: boolean;
  voiceEnabled: boolean;
  owner: KioskVoiceOwner | null;
}): KioskVoiceCommand {
  if (!micEnabled) return owner === 'policy' ? 'end' : 'noop';
  if (!voiceEnabled) return 'unavailable';
  return owner === null ? 'start' : 'noop';
}
