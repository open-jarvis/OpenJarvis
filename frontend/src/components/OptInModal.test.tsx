import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  joined: false,
  fetchIdentity: vi.fn(),
  savePreference: vi.fn(),
  setOptIn: vi.fn(),
}));
vi.mock('../lib/store', () => ({
  useAppStore: (selector: (state: Record<string, unknown>) => unknown) => selector({
    setOptIn: mocks.setOptIn,
    optInDisplayName: '',
    optInEmail: '',
    optInEnabled: mocks.joined,
  }),
}));
vi.mock('../lib/analytics', () => ({
  fetchAnalyticsIdentity: mocks.fetchIdentity,
  saveAnalyticsPreference: mocks.savePreference,
}));

import { OptInModal } from './OptInModal';

beforeEach(() => {
  mocks.joined = false;
  vi.clearAllMocks();
});

describe('existing sharing modal', () => {
  it('offers explicit analytics actions without a checkbox or side effects on render', () => {
    const html = renderToStaticMarkup(<OptInModal onClose={vi.fn()} />);
    expect(html).not.toContain('type="checkbox"');
    expect(html).toContain('Enable analytics &amp; enter giveaway');
    expect(html).toContain('Enter giveaway only');
    expect(html).toContain('Enable analytics only');
    expect(html).toContain('Continue without sharing');
    expect(html).toContain('Win a Mac mini');
    expect(html).toContain('Your name and savings are public');
    expect(mocks.savePreference).not.toHaveBeenCalled();
    expect(mocks.setOptIn).not.toHaveBeenCalled();
  });

  it('allows existing leaderboard members to change analytics independently', () => {
    mocks.joined = true;
    const html = renderToStaticMarkup(<OptInModal onClose={vi.fn()} />);
    expect(html).toContain('Enable analytics');
    expect(html).toContain('Stop leaderboard updates');
    expect(mocks.savePreference).not.toHaveBeenCalled();
  });
});
