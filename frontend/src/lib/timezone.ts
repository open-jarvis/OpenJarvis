// ---------------------------------------------------------------------------
// The user's time zone, sent to the server so answers use local time.
// ---------------------------------------------------------------------------
//
// Settings stores an IANA zone name, or '' for "use this device's zone".
// Chat and agent requests carry the resolved zone in X-OpenJarvis-Timezone;
// the server tells the model, so UTC times from tools (mail, calendar) are
// shown in the user's time.

export const TIMEZONE_HEADER = 'X-OpenJarvis-Timezone';

export function deviceTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

export function isValidTimeZone(zone: string): boolean {
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: zone });
    return true;
  } catch {
    return false;
  }
}

/** The zone to use: the one picked in Settings, else the device's. */
export function resolveTimeZone(setting: string | undefined): string {
  return setting && isValidTimeZone(setting) ? setting : deviceTimeZone();
}

/** The header to send with chat and agent requests. */
export function timeZoneHeaders(): Record<string, string> {
  let setting = '';
  try {
    const raw = localStorage.getItem('openjarvis-settings');
    if (raw) setting = String(JSON.parse(raw).timeZone || '');
  } catch {
    setting = '';
  }
  return { [TIMEZONE_HEADER]: resolveTimeZone(setting) };
}

/** Zone names for the Settings picker, always including the device's zone. */
export function listTimeZones(): string[] {
  let zones: string[] = [];
  try {
    zones = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] })
      .supportedValuesOf?.('timeZone') ?? [];
  } catch {
    zones = [];
  }
  const device = deviceTimeZone();
  return zones.includes(device) ? zones : [device, ...zones];
}

/** "UTC+02:00" for a zone at the given moment. */
export function utcOffsetLabel(zone: string, at: Date = new Date()): string {
  try {
    const part = new Intl.DateTimeFormat('en-US', { timeZone: zone, timeZoneName: 'longOffset' })
      .formatToParts(at)
      .find((p) => p.type === 'timeZoneName')?.value;
    if (!part || part === 'GMT') return 'UTC+00:00';
    return part.replace('GMT', 'UTC');
  } catch {
    return '';
  }
}
