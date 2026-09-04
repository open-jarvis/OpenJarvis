import { describe, expect, it } from 'vitest';

import { getAgentSchedule, normalizeAgentSchedule } from './agent-schedule';

describe('getAgentSchedule', () => {
  it('reads schedule fields from the nested agent config', () => {
    expect(
      getAgentSchedule({
        config: {
          schedule_type: 'cron',
          schedule_value: '0 9 * * *',
        },
      }),
    ).toEqual({ type: 'cron', value: '0 9 * * *' });
  });

  it('normalizes numeric interval values for display', () => {
    expect(
      getAgentSchedule({
        config: { schedule_type: 'interval', schedule_value: 300 },
      }),
    ).toEqual({ type: 'interval', value: '300' });
  });

  it('prefers nested config over legacy top-level fields', () => {
    expect(
      getAgentSchedule({
        config: {
          schedule_type: 'cron',
          schedule_value: '0 9 * * *',
        },
        schedule_type: 'manual',
        schedule_value: '',
      }),
    ).toEqual({ type: 'cron', value: '0 9 * * *' });
  });

  it('falls back to legacy top-level fields for older servers', () => {
    expect(
      getAgentSchedule({
        config: {},
        schedule_type: 'interval',
        schedule_value: '60',
      }),
    ).toEqual({ type: 'interval', value: '60' });
  });
});

describe('normalizeAgentSchedule', () => {
  it('fills the displayed one-hour default for an untouched hourly preset', () => {
    expect(normalizeAgentSchedule('hourly', '')).toEqual({
      type: 'interval',
      value: '3600',
    });
  });

  it('does not reuse a cron value as an interval', () => {
    expect(normalizeAgentSchedule('hourly', '0 9 * * *')).toEqual({
      type: 'interval',
      value: '3600',
    });
  });

  it('replaces a non-positive interval with the one-hour default', () => {
    expect(normalizeAgentSchedule('hourly', 0)).toEqual({
      type: 'interval',
      value: '3600',
    });
  });

  it('does not reuse an interval value as a daily cron expression', () => {
    expect(normalizeAgentSchedule('daily', '3600')).toEqual({
      type: 'cron',
      value: '0 9 * * *',
    });
  });

  it('preserves a user-selected hourly interval', () => {
    expect(normalizeAgentSchedule('hourly', '7200')).toEqual({
      type: 'interval',
      value: '7200',
    });
  });

  it('uses a safe weekly default when no day has been selected', () => {
    expect(normalizeAgentSchedule('weekly', '')).toEqual({
      type: 'cron',
      value: '0 9 * * 1',
    });
  });

  it('clears the value for a manual schedule', () => {
    expect(normalizeAgentSchedule('manual', '3600')).toEqual({
      type: 'manual',
      value: '',
    });
  });
});
