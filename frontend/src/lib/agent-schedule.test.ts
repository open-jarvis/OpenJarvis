import { describe, expect, it } from 'vitest';

import { getAgentSchedule } from './agent-schedule';

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
